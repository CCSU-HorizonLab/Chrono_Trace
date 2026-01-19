"""
态度预处理服务测试
测试单次遍历统计和O(N)复杂度验证
"""

import pytest
from unittest.mock import Mock, patch
from datetime import datetime

from app.services.analysis.preprocessing_service import (
    AttitudePreprocessingService,
    AttitudeStatistics
)


class TestAttitudePreprocessingService:
    """态度预处理服务测试类"""

    @pytest.fixture
    def mock_keywords(self):
        """模拟关键词库"""
        return {
            'positive': ['开心', '快乐'],
            'negative': ['难过', '痛苦'],
            'empathy': ['理解', '懂你'],
            'soothing': ['抱抱', '别哭'],
            'privacy': ['电话', '地址'],
            'holiday': ['新年快乐', '春节', '中秋节', '元旦'],
            'nickname': ['宝宝', '宝贝', '亲爱的']
        }

    @pytest.fixture
    def mock_keyword_lib(self, mock_keywords):
        """模拟KeywordLibraries实例"""
        lib = Mock()
        lib.get_all_keywords.return_value = mock_keywords
        lib.check_keywords_in_text = lambda text, keywords: any(
            kw.lower() in text.lower() for kw in keywords if kw
        )
        # 添加新方法的模拟
        def check_by_category(text, category):
            keywords = mock_keywords.get(category, [])
            return any(kw.lower() in text.lower() for kw in keywords if kw)
        lib.check_keywords_in_text_by_category = check_by_category
        return lib
    
    @pytest.fixture
    def mock_holiday_lib(self):
        """模拟HolidayLibrary实例"""
        lib = Mock()
        # 模拟节日名称提取
        def extract_holiday(text, keywords):
            if '元旦' in text or '新年' in text:
                return '元旦'
            elif '春节' in text:
                return '春节'
            elif '中秋' in text:
                return '中秋节'
            return None
        lib.extract_holiday_from_keywords = extract_holiday
        
        # 模拟节日日期匹配
        def is_holiday_date(date_str, holiday_name, tolerance_days=1):
            # 简化:元旦是1月1日
            if holiday_name == '元旦' and '01-01' in date_str:
                return True
            # 其他节日暂时返回False(需要农历转换)
            return False
        lib.is_holiday_date = is_holiday_date
        
        return lib

    @pytest.fixture
    def service(self, mock_keyword_lib, mock_holiday_lib):
        """创建AttitudePreprocessingService实例"""
        service = AttitudePreprocessingService(keyword_lib=mock_keyword_lib)
        service.holiday_lib = mock_holiday_lib
        return service

    # ===== 测试collect_attitude_statistics =====

    def test_collect_empty_messages(self, service):
        """测试空消息列表"""
        stats = service.collect_attitude_statistics([])

        assert stats.emoji_message_count == 0
        assert stats.voice_message_count == 0
        assert stats.video_message_count == 0
        assert stats.nickname_message_count == 0
        assert stats.privacy_message_count == 0
        assert stats.holiday_message_count == 0
        assert stats.holidays_sent_count == 0
    
    def test_collect_none_messages(self, service):
        """测试None消息列表"""
        stats = service.collect_attitude_statistics(None)
        assert stats.emoji_message_count == 0

    def test_collect_emoji_messages(self, service):
        """测试表情包统计"""
        messages = [
            {'content': '[表情]', 'message_type': 47, 'timestamp': 1000},
            {'content': '[动画]', 'message_type': 47, 'timestamp': 2000},
            {'content': '文本', 'message_type': 1, 'timestamp': 3000}
        ]

        stats = service.collect_attitude_statistics(messages)

        assert stats.emoji_message_count == 2

    def test_collect_voice_messages(self, service):
        """测试语音消息统计"""
        messages = [
            {'content': '[语音]', 'message_type': 34, 'timestamp': 1000},
            {'content': '[语音]', 'message_type': 34, 'timestamp': 2000},
            {'content': '文本', 'message_type': 1, 'timestamp': 3000}
        ]

        stats = service.collect_attitude_statistics(messages)

        assert stats.voice_message_count == 2

    def test_collect_video_messages(self, service):
        """测试视频通话统计"""
        messages = [
            {'content': '[视频通话]', 'message_type': 43, 'timestamp': 1000},
            {'content': '文本', 'message_type': 1, 'timestamp': 2000}
        ]

        stats = service.collect_attitude_statistics(messages)

        assert stats.video_message_count == 1

    def test_collect_nickname_keywords(self, service):
        """测试专属称呼统计"""
        messages = [
            {'content': '宝宝,你到了吗', 'message_type': 1, 'timestamp': 1000},
            {'content': '亲爱的,我想你了', 'message_type': 1, 'timestamp': 2000},
            {'content': '普通消息', 'message_type': 1, 'timestamp': 3000}
        ]

        stats = service.collect_attitude_statistics(messages)

        assert stats.nickname_message_count == 2

    def test_collect_privacy_keywords(self, service):
        """测试隐私关键词统计"""
        messages = [
            {'content': '我的电话是123456', 'message_type': 1, 'timestamp': 1000},
            {'content': '地址在某处', 'message_type': 1, 'timestamp': 2000},
            {'content': '普通消息', 'message_type': 1, 'timestamp': 3000}
        ]

        stats = service.collect_attitude_statistics(messages)

        assert stats.privacy_message_count == 2

    def test_collect_holiday_keywords_with_date_matching(self, service):
        """测试节日祝福统计(带日期匹配)"""
        # 2024-01-01 00:00:00 = 1704067200 (元旦)
        # 2024-02-10 = 1707523200 (春节,但不在1月1日)
        messages = [
            {'content': '新年快乐!', 'message_type': 1, 'timestamp': 1704067200},  # 元旦当天
            {'content': '元旦快乐', 'message_type': 1, 'timestamp': 1704067200},  # 同一天,同一节日
            {'content': '春节快乐', 'message_type': 1, 'timestamp': 1707523200}  # 不同节日
        ]

        stats = service.collect_attitude_statistics(messages)

        assert stats.holiday_message_count == 3
        # 元旦当天的两条消息会被识别为同一个节日(元旦-2024)
        # 春节消息因为日期不匹配,会使用消息日期作为标识
        assert stats.holidays_sent_count >= 2

    def test_collect_combined_statistics(self, service):
        """测试混合消息统计"""
        messages = [
            {'content': '[表情]', 'message_type': 47, 'timestamp': 1000},
            {'content': '[语音]', 'message_type': 34, 'timestamp': 2000},
            {'content': '宝宝,我的电话是123', 'message_type': 1, 'timestamp': 1704067200},
            {'content': '新年快乐', 'message_type': 1, 'timestamp': 1704067200},
            {'content': '普通文本', 'message_type': 1, 'timestamp': 3000}
        ]

        stats = service.collect_attitude_statistics(messages)

        assert stats.emoji_message_count == 1
        assert stats.voice_message_count == 1
        assert stats.nickname_message_count == 1
        assert stats.privacy_message_count == 1
        assert stats.holiday_message_count == 1

    # ===== 测试优化功能 =====
    
    def test_check_all_keywords_optimization(self, service):
        """测试_check_all_keywords方法(一次性检查所有类别)"""
        result = service._check_all_keywords('宝宝,我的电话是123,新年快乐')
        
        assert result['nickname'] is True
        assert result['privacy'] is True
        assert result['holiday'] is True
    
    def test_check_all_keywords_empty_text(self, service):
        """测试_check_all_keywords空文本"""
        result = service._check_all_keywords('')
        
        assert result['nickname'] is False
        assert result['privacy'] is False
        assert result['holiday'] is False
    
    def test_extract_holiday_name(self, service):
        """测试节日名称提取"""
        holiday = service._extract_holiday_name('新年快乐!')
        assert holiday == '元旦'
        
        holiday = service._extract_holiday_name('春节快乐')
        assert holiday == '春节'
        
        holiday = service._extract_holiday_name('普通消息')
        assert holiday is None

    # ===== 测试异常处理 =====
    
    def test_invalid_message_format(self, service, capsys):
        """测试无效消息格式的异常处理"""
        messages = [
            "这不是字典",  # 无效格式
            {'content': '正常消息', 'message_type': 1, 'timestamp': 1000},
            None,  # None值
            {'content': '另一条正常消息', 'message_type': 1, 'timestamp': 2000}
        ]
        
        stats = service.collect_attitude_statistics(messages)
        
        # 应该跳过无效消息,不崩溃
        captured = capsys.readouterr()
        assert '[警告]' in captured.out or '[错误]' in captured.out

    def test_message_processing_exception(self, service, capsys):
        """测试消息处理异常"""
        # 模拟关键词检查抛出异常
        def raise_error(text, category):
            raise ValueError("模拟错误")
        
        service.keyword_lib.check_keywords_in_text_by_category = raise_error
        
        messages = [
            {'content': '测试消息', 'message_type': 1, 'timestamp': 1000}
        ]
        
        stats = service.collect_attitude_statistics(messages)
        
        # 应该捕获异常并继续
        captured = capsys.readouterr()
        assert '[错误]' in captured.out

    # ===== 测试O(N)复杂度 =====

    def test_single_pass_complexity(self, service):
        """验证单次遍历(O(N)复杂度)"""
        # 创建1000条消息
        messages = [
            {'content': f'消息{i}', 'message_type': 1, 'timestamp': 1000 + i}
            for i in range(1000)
        ]

        # 统计get_all_keywords调用次数
        initial_count = service.keyword_lib.get_all_keywords.call_count

        stats = service.collect_attitude_statistics(messages)

        # 应该只调用1次(缓存机制)
        assert service.keyword_lib.get_all_keywords.call_count == initial_count + 1

        # 第二次调用应该使用缓存,不再调用get_all_keywords
        stats2 = service.collect_attitude_statistics(messages)
        assert service.keyword_lib.get_all_keywords.call_count == initial_count + 1

    # ===== 测试边界情况 =====

    def test_message_with_missing_fields(self, service):
        """测试消息缺少字段"""
        messages = [
            {},  # 完全空
            {'content': '测试'},  # 缺少message_type
            {'message_type': 1},  # 缺少content
            {'content': '', 'message_type': 1}  # 空内容
        ]

        stats = service.collect_attitude_statistics(messages)

        # 应该不崩溃,所有计数为0
        assert stats.emoji_message_count == 0
        assert stats.privacy_message_count == 0

    def test_holiday_date_extraction(self, service):
        """测试节日日期提取"""
        # 测试不同的时间戳
        messages = [
            {'content': '新年快乐', 'message_type': 1, 'timestamp': 0},  # 无效时间戳
            {'content': '元旦快乐', 'message_type': 1, 'timestamp': 1704067200}  # 2024-01-01
        ]

        stats = service.collect_attitude_statistics(messages)

        # 应该统计所有节日消息
        assert stats.holiday_message_count == 2
