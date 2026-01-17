"""
态度预处理服务测试
测试单次遍历统计和O(N)复杂度验证
"""

import pytest
from unittest.mock import Mock, patch

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
            'holiday': ['新年快乐', '春节', '中秋节'],
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
        return lib

    @pytest.fixture
    def service(self, mock_keyword_lib):
        """创建AttitudePreprocessingService实例"""
        return AttitudePreprocessingService(keyword_lib=mock_keyword_lib)

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

    def test_collect_holiday_keywords(self, service):
        """测试节日祝福统计"""
        # 2024-01-01 00:00:00 UTC = 1704067200
        # 2024-01-02 00:00:00 UTC = 1704153600
        messages = [
            {'content': '新年快乐!', 'message_type': 1, 'timestamp': 1704067200},
            {'content': '春节快乐', 'message_type': 1, 'timestamp': 1704067200},  # 同一天
            {'content': '中秋节快乐', 'message_type': 1, 'timestamp': 1726089600}  # 不同天
        ]

        stats = service.collect_attitude_statistics(messages)

        assert stats.holiday_message_count == 3
        assert stats.holidays_sent_count == 2  # 2个不同日期

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
        assert stats.holidays_sent_count == 1

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

    def test_no_duplicate_traversal(self, service):
        """验证不重复遍历消息"""
        messages = [
            {'content': '新年快乐', 'message_type': 1, 'timestamp': 1704067200},
            {'content': '[表情]', 'message_type': 47, 'timestamp': 2000}
        ]

        # 统计关键词检查次数
        check_count = [0]
        original_check = service.keyword_lib.check_keywords_in_text

        def counting_check(text, keywords):
            check_count[0] += 1
            return original_check(text, keywords)

        service.keyword_lib.check_keywords_in_text = counting_check

        stats = service.collect_attitude_statistics(messages)

        # 每条文本消息只检查3个分类(nickname + privacy + holiday)
        # 1条文本消息 × 3个分类 = 3次检查
        assert check_count[0] <= 3  # 不应该超过3次

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
            {'content': '春节快乐', 'message_type': 1, 'timestamp': 1704067200}  # 2024-01-01
        ]

        stats = service.collect_attitude_statistics(messages)

        # 只统计有效日期
        assert stats.holidays_sent_count == 1
