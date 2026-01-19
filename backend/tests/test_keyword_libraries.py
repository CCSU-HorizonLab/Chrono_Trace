"""
关键词库管理服务测试
测试KeywordLibraries的CRUD操作和关键词匹配功能
"""

import pytest
import sqlite3
from unittest.mock import Mock, patch

from app.services.analysis.keyword_libraries import KeywordLibraries


class TestKeywordLibraries:
    """关键词库测试类"""

    @pytest.fixture
    def mock_db(self):
        """创建模拟数据库连接"""
        conn = sqlite3.connect(':memory:')  # 内存数据库
        cursor = conn.cursor()

        # 创建keyword_libraries表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS keyword_libraries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                category TEXT NOT NULL,
                keyword TEXT NOT NULL,
                is_custom INTEGER DEFAULT 0,
                created_at INTEGER NOT NULL,
                UNIQUE(category, keyword)
            )
        """)

        # 插入测试数据
        cursor.execute("""
            INSERT INTO keyword_libraries (category, keyword, is_custom, created_at) VALUES
            ('positive', '开心', 0, 1000),
            ('positive', '哈哈', 0, 1000),
            ('negative', '难过', 0, 1000),
            ('empathy', '理解', 0, 1000),
            ('soothing', '抱抱', 0, 1000),
            ('privacy', '电话', 0, 1000),
            ('holiday', '新年快乐', 0, 1000),
            ('nickname', '宝宝', 0, 1000)
        """)
        conn.commit()

        return conn

    @pytest.fixture
    def keyword_lib(self, mock_db):
        """创建KeywordLibraries实例并注入模拟数据库"""

        # Patch get_db to return our mock connection
        with patch('app.services.analysis.keyword_libraries.get_db', return_value=mock_db):
            lib = KeywordLibraries()
            lib.reload_cache()  # 强制加载缓存
            yield lib

    # ===== 测试get_keywords =====

    def test_get_keywords_valid_category(self, keyword_lib):
        """测试获取有效分类的关键词"""
        keywords = keyword_lib.get_keywords('positive')
        assert isinstance(keywords, list)
        assert len(keywords) == 2
        assert '开心' in keywords
        assert '哈哈' in keywords

    def test_get_keywords_empty_category(self, keyword_lib, mock_db):
        """测试获取空分类的关键词"""
        # 确保某个分类是空的
        cursor = mock_db.cursor()
        cursor.execute("DELETE FROM keyword_libraries WHERE category = 'soothing'")
        mock_db.commit()

        # 重新加载缓存
        keyword_lib.reload_cache()

        keywords = keyword_lib.get_keywords('soothing')
        assert keywords == []

    def test_get_keywords_invalid_category(self, keyword_lib):
        """测试获取无效分类的关键词"""
        with pytest.raises(ValueError, match="Invalid category"):
            keyword_lib.get_keywords('invalid_category')

    def test_get_keywords_returns_copy(self, keyword_lib):
        """测试get_keywords返回的是副本,不是原始列表"""
        keywords1 = keyword_lib.get_keywords('positive')
        keywords2 = keyword_lib.get_keywords('positive')

        # 修改返回的列表不应该影响缓存
        keywords1.append('新词')
        assert '新词' not in keywords2
        assert '新词' not in keyword_lib.get_keywords('positive')

    # ===== 测试add_keywords =====

    def test_add_keywords_new(self, keyword_lib):
        """测试添加新关键词"""
        count = keyword_lib.add_keywords('positive', ['棒极了', '赞'])
        assert count == 2

        keywords = keyword_lib.get_keywords('positive')
        assert '棒极了' in keywords
        assert '赞' in keywords
        assert len(keywords) == 4  # 原来2个 + 新增2个

    def test_add_keywords_duplicate(self, keyword_lib):
        """测试添加已存在的关键词"""
        count = keyword_lib.add_keywords('positive', ['开心', '新词'])
        assert count == 1  # 只添加了'新词'

        keywords = keyword_lib.get_keywords('positive')
        assert len(keywords) == 3  # 原来2个 + 新增1个

    def test_add_keywords_empty_list(self, keyword_lib):
        """测试添加空列表"""
        count = keyword_lib.add_keywords('positive', [])
        assert count == 0

    def test_add_keywords_whitespace(self, keyword_lib):
        """测试添加包含空格的关键词"""
        count = keyword_lib.add_keywords('positive', ['  棒极了  ', '', '  '])
        assert count == 1  # 只添加了'棒极了'(去空格后)

        keywords = keyword_lib.get_keywords('positive')
        assert '棒极了' in keywords

    def test_add_keywords_invalid_category(self, keyword_lib):
        """测试向无效分类添加关键词"""
        with pytest.raises(ValueError, match="Invalid category"):
            keyword_lib.add_keywords('invalid', ['测试'])

    # ===== 测试remove_keywords =====

    def test_remove_keywords_custom(self, keyword_lib, mock_db):
        """测试删除自定义关键词"""
        # 先添加一个自定义关键词
        cursor = mock_db.cursor()
        cursor.execute(
            "INSERT INTO keyword_libraries (category, keyword, is_custom, created_at) VALUES (?, ?, 1, ?)",
            ('positive', '自定义词', 2000)
        )
        mock_db.commit()

        keyword_lib.reload_cache()

        # 删除自定义关键词
        count = keyword_lib.remove_keywords('positive', ['自定义词'])
        assert count == 1

        keywords = keyword_lib.get_keywords('positive')
        assert '自定义词' not in keywords

    def test_remove_keywords_default(self, keyword_lib):
        """测试删除默认关键词(修改后应该成功)"""
        # '开心'是默认关键词(is_custom=0),现在可以删除
        count = keyword_lib.remove_keywords('positive', ['开心'])
        assert count == 1  # 删除成功

        keywords = keyword_lib.get_keywords('positive')
        assert '开心' not in keywords  # 已被删除

    def test_remove_keywords_partial(self, keyword_lib):
        """测试删除部分存在的关键词"""
        count = keyword_lib.remove_keywords('positive', ['哈哈', '不存在'])
        assert count == 1  # 只删除了'哈哈'

    def test_remove_keywords_empty_list(self, keyword_lib):
        """测试删除空列表"""
        count = keyword_lib.remove_keywords('positive', [])
        assert count == 0

    def test_remove_keywords_invalid_category(self, keyword_lib):
        """测试从无效分类删除关键词"""
        with pytest.raises(ValueError, match="Invalid category"):
            keyword_lib.remove_keywords('invalid', ['测试'])

    # ===== 测试get_all_keywords =====

    def test_get_all_keywords(self, keyword_lib):
        """测试获取所有分类的关键词"""
        all_keywords = keyword_lib.get_all_keywords()

        assert isinstance(all_keywords, dict)
        assert len(all_keywords) == 7  # 6 → 7

        # 检查每个分类
        assert 'positive' in all_keywords
        assert 'negative' in all_keywords
        assert 'empathy' in all_keywords
        assert 'soothing' in all_keywords
        assert 'privacy' in all_keywords
        assert 'holiday' in all_keywords
        assert 'nickname' in all_keywords

        # 检查内容
        assert '开心' in all_keywords['positive']
        assert '难过' in all_keywords['negative']

    def test_get_all_keywords_returns_copy(self, keyword_lib):
        """测试get_all_keywords返回的是副本"""
        all_keywords1 = keyword_lib.get_all_keywords()
        all_keywords2 = keyword_lib.get_all_keywords()

        # 修改返回的字典不应该影响缓存
        all_keywords1['positive'].append('新词')
        assert '新词' not in all_keywords2['positive']

    # ===== 测试check_keywords_in_text =====

    def test_check_keywords_in_text_match(self):
        """测试关键词匹配成功"""
        text = "我今天很开心!"
        keywords = ['开心', '快乐', '幸福']
        result = KeywordLibraries.check_keywords_in_text(text, keywords)
        assert result is True

    def test_check_keywords_in_text_no_match(self):
        """测试关键词不匹配"""
        text = "我今天很普通"
        keywords = ['开心', '快乐', '幸福']
        result = KeywordLibraries.check_keywords_in_text(text, keywords)
        assert result is False

    def test_check_keywords_in_text_case_insensitive(self):
        """测试大小写不敏感匹配"""
        text = "我今天很开心!"
        keywords = ['开心', 'KAI XIN']
        result = KeywordLibraries.check_keywords_in_text(text, keywords)
        # 实际上是子串匹配,不区分大小写
        assert result is True

    def test_check_keywords_in_text_empty_text(self):
        """测试空文本"""
        result = KeywordLibraries.check_keywords_in_text('', ['开心'])
        assert result is False

    def test_check_keywords_in_text_empty_keywords(self):
        """测试空关键词列表"""
        result = KeywordLibraries.check_keywords_in_text('测试文本', [])
        assert result is False

    def test_check_keywords_in_text_partial_match(self):
        """测试部分匹配 - 关键词是文本的子串"""
        text = "这个产品很棒"
        keywords = ['棒']
        result = KeywordLibraries.check_keywords_in_text(text, keywords)
        assert result is True  # '棒'在文本中

    # ===== 测试check_text (便捷方法) =====

    def test_check_text_convenience_method(self, keyword_lib):
        """测试check_text便捷方法"""
        result = keyword_lib.check_text("我今天很开心!", 'positive')
        assert result is True

        result = keyword_lib.check_text("普通文本", 'positive')
        assert result is False
    
    # ===== 测试check_keywords_in_text_by_category (优化后的方法) =====
    
    def test_check_keywords_by_category_match(self, keyword_lib):
        """测试按分类检查关键词 - 匹配成功"""
        result = keyword_lib.check_keywords_in_text_by_category("我今天很开心!", 'positive')
        assert result is True
    
    def test_check_keywords_by_category_no_match(self, keyword_lib):
        """测试按分类检查关键词 - 不匹配"""
        result = keyword_lib.check_keywords_in_text_by_category("普通文本", 'positive')
        assert result is False
    
    def test_check_keywords_by_category_empty_text(self, keyword_lib):
        """测试按分类检查 - 空文本"""
        result = keyword_lib.check_keywords_in_text_by_category('', 'positive')
        assert result is False
    
    def test_check_keywords_by_category_case_insensitive(self, keyword_lib):
        """测试按分类检查 - 不区分大小写"""
        result = keyword_lib.check_keywords_in_text_by_category("我很开心", 'positive')
        assert result is True
    
    def test_regex_cache_mechanism(self, keyword_lib):
        """测试正则表达式缓存机制"""
        # 第一次调用会编译正则
        result1 = keyword_lib.check_keywords_in_text_by_category("开心", 'positive')
        assert result1 is True
        
        # 检查正则缓存已创建
        assert 'positive' in keyword_lib._regex_cache
        assert keyword_lib._regex_cache['positive'] is not None
        
        # 第二次调用应使用缓存
        result2 = keyword_lib.check_keywords_in_text_by_category("哈哈", 'positive')
        assert result2 is True
    
    def test_regex_cache_invalidation_on_add(self, keyword_lib):
        """测试添加关键词后正则缓存失效"""
        # 先创建缓存
        keyword_lib.check_keywords_in_text_by_category("开心", 'positive')
        assert 'positive' in keyword_lib._regex_cache
        
        # 添加新关键词
        keyword_lib.add_keywords('positive', ['棒极了'])
        
        # 缓存应被清除
        assert 'positive' not in keyword_lib._regex_cache
        
        # 新关键词应该生效
        result = keyword_lib.check_keywords_in_text_by_category("棒极了", 'positive')
        assert result is True
    
    def test_regex_cache_invalidation_on_reload(self, keyword_lib):
        """测试reload_cache后正则缓存失效"""
        # 先创建缓存
        keyword_lib.check_keywords_in_text_by_category("开心", 'positive')
        keyword_lib.check_keywords_in_text_by_category("难过", 'negative')
        
        assert len(keyword_lib._regex_cache) == 2
        
        # 重新加载缓存
        keyword_lib.reload_cache()
        
        # 所有正则缓存应被清空
        assert len(keyword_lib._regex_cache) == 0

    # ===== 测试get_categories =====

    def test_get_categories(self, keyword_lib):
        """测试获取所有分类名称"""
        categories = keyword_lib.get_categories()

        assert isinstance(categories, list)
        assert len(categories) == 7  # 6 → 7
        assert 'positive' in categories
        assert 'negative' in categories
        assert 'empathy' in categories
        assert 'soothing' in categories
        assert 'privacy' in categories
        assert 'holiday' in categories
        assert 'nickname' in categories  # 新增

    # ===== 测试缓存机制 =====

    def test_cache_mechanism(self, keyword_lib, mock_db):
        """测试缓存机制"""
        # 第一次调用会从数据库加载
        keywords1 = keyword_lib.get_keywords('positive')

        # 直接修改数据库
        cursor = mock_db.cursor()
        cursor.execute(
            "INSERT INTO keyword_libraries (category, keyword, is_custom, created_at) VALUES (?, ?, 1, ?)",
            ('positive', '缓存测试', 3000)
        )
        mock_db.commit()

        # 第二次调用应该从缓存读取,看不到新数据
        keywords2 = keyword_lib.get_keywords('positive')
        assert '缓存测试' not in keywords2
        assert keywords1 == keywords2

        # 手动刷新缓存
        keyword_lib.reload_cache()

        # 现在应该看到新数据了
        keywords3 = keyword_lib.get_keywords('positive')
        assert '缓存测试' in keywords3

    def test_reload_cache(self, keyword_lib, mock_db):
        """测试reload_cache方法"""
        # 确保缓存已加载
        _ = keyword_lib.get_keywords('positive')

        # 修改数据库
        cursor = mock_db.cursor()
        cursor.execute(
            "INSERT INTO keyword_libraries (category, keyword, is_custom, created_at) VALUES (?, ?, 1, ?)",
            ('negative', '新负面词', 4000)
        )
        mock_db.commit()

        # 重新加载缓存
        keyword_lib.reload_cache()

        # 验证新词已加载
        keywords = keyword_lib.get_keywords('negative')
        assert '新负面词' in keywords
