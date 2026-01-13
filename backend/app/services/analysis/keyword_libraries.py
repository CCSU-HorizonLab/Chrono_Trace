"""
关键词库管理服务
管理6个类别的关键词: positive, negative, empathy, soothing, privacy, holiday
"""

from typing import List, Dict
import sqlite3
import time

# 使用相对导入避免循环依赖
from ...db.connection import get_db


class KeywordLibraries:
    """关键词库管理类"""

    # 6个关键词分类常量
    POSITIVE = 'positive'
    NEGATIVE = 'negative'
    EMPATHY = 'empathy'
    SOOTHING = 'soothing'
    PRIVACY = 'privacy'
    HOLIDAY = 'holiday'

    CATEGORIES = [POSITIVE, NEGATIVE, EMPATHY, SOOTHING, PRIVACY, HOLIDAY]

    def __init__(self):
        """初始化关键词库服务"""
        self._cache: Dict[str, List[str]] = {}  # 内存缓存
        self._cache_loaded = False

    # ===== 核心CRUD方法 =====

    def get_keywords(self, category: str) -> List[str]:
        """
        获取指定分类的所有关键词

        Args:
            category: 分类名称 (positive/negative/empathy/soothing/privacy/holiday)

        Returns:
            List[str]: 关键词列表

        Raises:
            ValueError: 分类名称无效
        """
        if category not in self.CATEGORIES:
            raise ValueError(f"Invalid category: {category}. Must be one of {self.CATEGORIES}")

        # 确保缓存已加载
        if not self._cache_loaded:
            self._load_cache()

        return self._cache.get(category, []).copy()

    def add_keywords(self, category: str, keywords: List[str]) -> int:
        """
        添加自定义关键词到指定分类

        Args:
            category: 分类名称
            keywords: 要添加的关键词列表

        Returns:
            int: 实际添加的关键词数量(排除已存在的)

        Raises:
            ValueError: 分类名称无效
        """
        if category not in self.CATEGORIES:
            raise ValueError(f"Invalid category: {category}")

        if not keywords:
            return 0

        # 过滤空字符串和已存在的关键词
        existing_keywords = set(self.get_keywords(category))
        new_keywords = [
            kw.strip() for kw in keywords
            if kw.strip() and kw.strip() not in existing_keywords
        ]

        if not new_keywords:
            return 0

        # 插入数据库
        conn = get_db()
        cursor = conn.cursor()
        timestamp = int(time.time())

        try:
            for keyword in new_keywords:
                cursor.execute(
                    "INSERT INTO keyword_libraries (category, keyword, is_custom, created_at) VALUES (?, ?, 1, ?)",
                    (category, keyword, timestamp)
                )
            conn.commit()
        except sqlite3.IntegrityError:
            # 如果插入失败(唯一约束冲突),回滚
            conn.rollback()
            return 0

        # 更新缓存
        self._cache[category].extend(new_keywords)

        return len(new_keywords)

    def remove_keywords(self, category: str, keywords: List[str]) -> int:
        """
        从指定分类删除关键词

        Args:
            category: 分类名称
            keywords: 要删除的关键词列表

        Returns:
            int: 实际删除的关键词数量
        """
        if category not in self.CATEGORIES:
            raise ValueError(f"Invalid category: {category}")

        if not keywords:
            return 0

        # 只能删除自定义关键词(is_custom=1),不能删除默认关键词
        conn = get_db()
        cursor = conn.cursor()

        placeholders = ','.join(['?'] * len(keywords))
        cursor.execute(
            f"DELETE FROM keyword_libraries WHERE category = ? AND keyword IN ({placeholders}) AND is_custom = 1",
            [category] + keywords
        )

        deleted_count = cursor.rowcount
        conn.commit()

        # 更新缓存
        if deleted_count > 0:
            self._load_cache()  # 重新加载缓存

        return deleted_count

    def get_all_keywords(self) -> Dict[str, List[str]]:
        """
        获取全部6个分类的关键词字典

        Returns:
            Dict[str, List[str]]: {category: [keywords]}
        """
        if not self._cache_loaded:
            self._load_cache()

        return {cat: kws.copy() for cat, kws in self._cache.items()}

    # ===== 辅助方法 =====

    def _load_cache(self):
        """从数据库加载所有关键词到内存缓存"""
        conn = get_db()
        cursor = conn.cursor()

        cursor.execute(
            "SELECT category, keyword FROM keyword_libraries ORDER BY category, keyword"
        )
        rows = cursor.fetchall()

        # 重置缓存
        self._cache = {cat: [] for cat in self.CATEGORIES}

        for category, keyword in rows:
            if category in self._cache:
                self._cache[category].append(keyword)

        self._cache_loaded = True

    def reload_cache(self):
        """强制重新加载缓存(用于外部更新后刷新)"""
        self._cache_loaded = False
        self._load_cache()

    @staticmethod
    def check_keywords_in_text(text: str, keywords: List[str]) -> bool:
        """
        检查文本中是否包含任意关键词

        Args:
            text: 要检查的文本
            keywords: 关键词列表

        Returns:
            bool: 如果文本包含任意关键词则返回True
        """
        if not text or not keywords:
            return False

        text_lower = text.lower()

        for keyword in keywords:
            if not keyword:
                continue
            # 简单子串匹配
            if keyword.lower() in text_lower:
                return True

        return False

    def check_text(self, text: str, category: str) -> bool:
        """
        检查文本是否包含指定分类的关键词

        Args:
            text: 要检查的文本
            category: 分类名称

        Returns:
            bool: 如果包含该分类的任意关键词则返回True
        """
        keywords = self.get_keywords(category)
        return self.check_keywords_in_text(text, keywords)

    def get_categories(self) -> List[str]:
        """获取所有有效的分类名称"""
        return self.CATEGORIES.copy()
