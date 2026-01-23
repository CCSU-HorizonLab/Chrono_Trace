"""聊天积极度服务测试

测试 ChatPositivityService 的所有 5 个子维度计算方法
"""

import pytest
import sys
import os
from unittest.mock import MagicMock, patch

# 添加项目路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))


class TestChatPositivityService:
    """测试聊天积极度服务"""

    @pytest.fixture
    def mock_db(self):
        """创建模拟数据库连接"""
        mock = MagicMock()
        return mock

    @pytest.fixture
    def mock_stats(self):
        """创建模拟预处理统计数据"""
        from app.services.analysis.preprocessing_orchestrator import PreprocessedStatistics
        
        stats = PreprocessedStatistics()
        stats.total_message_count = 1000
        stats.conversation_duration_days = 30.0
        stats.average_message_length = 25.0
        stats.total_sessions = 50
        stats.sender_initiated_count = 20
        stats.contact_initiated_count = 30
        return stats

    @pytest.fixture
    def service(self, mock_db):
        """创建服务实例"""
        with patch('app.services.analysis.chat_positivity_service.get_db', return_value=mock_db):
            from app.services.analysis.chat_positivity_service import ChatPositivityService
            return ChatPositivityService(timeliness_threshold_seconds=300)

    # ========================================
    # 日均消息数测试
    # ========================================

    def test_daily_message_score_normal(self, service, mock_stats):
        """测试正常情况下的日均消息数"""
        # 1000 消息 / 30 天 = 33.33 条/天
        # 满分基准是 10 条/天，所以应该得满分
        score = service.calculate_daily_message_score(mock_stats)
        assert score == 100.0

    def test_daily_message_score_low(self, service, mock_stats):
        """测试低消息量"""
        mock_stats.total_message_count = 100
        mock_stats.conversation_duration_days = 30.0
        # 100 / 30 = 3.33 条/天
        # 3.33 / 10 * 100 = 33.3
        score = service.calculate_daily_message_score(mock_stats)
        assert 33 <= score <= 34

    def test_daily_message_score_zero_duration(self, service, mock_stats):
        """测试零持续时间"""
        mock_stats.conversation_duration_days = 0
        score = service.calculate_daily_message_score(mock_stats)
        assert score == 0.0

    # ========================================
    # 回复及时率测试
    # ========================================

    def test_reply_timeliness_all_timely(self, service, mock_db):
        """测试全部及时回复"""
        # 模拟所有交互对都及时回复
        mock_db.execute.return_value.fetchone.return_value = (100, 100)
        
        score = service.calculate_reply_timeliness_score(1)
        assert score == 100.0

    def test_reply_timeliness_half_timely(self, service, mock_db):
        """测试一半及时回复"""
        mock_db.execute.return_value.fetchone.return_value = (100, 50)
        
        score = service.calculate_reply_timeliness_score(1)
        assert score == 50.0

    def test_reply_timeliness_no_pairs(self, service, mock_db):
        """测试无交互对"""
        mock_db.execute.return_value.fetchone.return_value = (0, 0)
        
        score = service.calculate_reply_timeliness_score(1)
        assert score == 0.0

    # ========================================
    # 平均消息长度测试
    # ========================================

    def test_avg_length_score_normal(self, service, mock_stats):
        """测试正常消息长度"""
        mock_stats.average_message_length = 25.0
        # 25 / 50 * 100 = 50
        score = service.calculate_avg_length_score(mock_stats)
        assert score == 50.0

    def test_avg_length_score_max(self, service, mock_stats):
        """测试长消息"""
        mock_stats.average_message_length = 100.0
        score = service.calculate_avg_length_score(mock_stats)
        assert score == 100.0

    def test_avg_length_score_zero(self, service, mock_stats):
        """测试零长度"""
        mock_stats.average_message_length = 0.0
        score = service.calculate_avg_length_score(mock_stats)
        assert score == 0.0

    # ========================================
    # 长文本占比测试
    # ========================================

    def test_long_text_ratio_high(self, service, mock_db, mock_stats):
        """测试高长文本占比"""
        # 30% 长文本 = 满分
        mock_db.execute.return_value.fetchone.return_value = (300,)
        mock_stats.total_message_count = 1000
        
        score = service.calculate_long_text_ratio_score(1, mock_stats)
        assert score == 100.0

    def test_long_text_ratio_low(self, service, mock_db, mock_stats):
        """测试低长文本占比"""
        # 10% 长文本
        mock_db.execute.return_value.fetchone.return_value = (100,)
        mock_stats.total_message_count = 1000
        
        score = service.calculate_long_text_ratio_score(1, mock_stats)
        assert 33 <= score <= 34

    def test_long_text_ratio_zero_messages(self, service, mock_db, mock_stats):
        """测试零消息"""
        mock_stats.total_message_count = 0
        
        score = service.calculate_long_text_ratio_score(1, mock_stats)
        assert score == 0.0

    # ========================================
    # 话题延续性测试
    # ========================================

    def test_topic_continuity_high(self, service, mock_db):
        """测试高话题延续性"""
        mock_db.execute.return_value.fetchone.return_value = (0.8,)
        
        score = service.calculate_topic_continuity_score(1)
        assert score == 80.0

    def test_topic_continuity_low(self, service, mock_db):
        """测试低话题延续性"""
        mock_db.execute.return_value.fetchone.return_value = (0.3,)
        
        score = service.calculate_topic_continuity_score(1)
        assert score == 30.0

    def test_topic_continuity_null(self, service, mock_db):
        """测试无相似度数据"""
        mock_db.execute.return_value.fetchone.return_value = (None,)
        
        score = service.calculate_topic_continuity_score(1)
        assert score == 0.0

    # ========================================
    # 主动发起率测试
    # ========================================

    def test_active_initiation_high(self, service, mock_stats):
        """测试高主动发起率"""
        mock_stats.total_sessions = 100
        mock_stats.contact_initiated_count = 80
        
        score = service.calculate_active_initiation_score(mock_stats)
        assert score == 80.0

    def test_active_initiation_low(self, service, mock_stats):
        """测试低主动发起率"""
        mock_stats.total_sessions = 100
        mock_stats.contact_initiated_count = 20
        
        score = service.calculate_active_initiation_score(mock_stats)
        assert score == 20.0

    def test_active_initiation_zero_sessions(self, service, mock_stats):
        """测试零会话"""
        mock_stats.total_sessions = 0
        mock_stats.contact_initiated_count = 0
        
        score = service.calculate_active_initiation_score(mock_stats)
        assert score == 0.0

    # ========================================
    # 综合评分测试
    # ========================================

    def test_overall_score_weights(self, service):
        """测试综合评分权重正确"""
        from app.services.analysis.chat_positivity_service import ChatPositivityResult
        
        result = ChatPositivityResult()
        result.daily_message_score = 100
        result.reply_timeliness_score = 100
        result.avg_length_score = 100
        result.long_text_ratio_score = 100
        result.topic_continuity_score = 100
        result.active_initiation_score = 100
        
        overall = service._calculate_overall_score(result)
        # 所有子维度都是 100，所以综合评分应该是 100
        assert overall == 100.0

    def test_overall_score_partial(self, service):
        """测试部分得分"""
        from app.services.analysis.chat_positivity_service import ChatPositivityResult
        
        result = ChatPositivityResult()
        result.daily_message_score = 50
        result.reply_timeliness_score = 50
        result.avg_length_score = 50
        result.long_text_ratio_score = 50
        result.topic_continuity_score = 50
        result.active_initiation_score = 50
        
        overall = service._calculate_overall_score(result)
        assert overall == 50.0

    # ========================================
    # 解释文本测试
    # ========================================

    def test_interpretation_high(self, service):
        """测试高分解释"""
        interpretation = service.generate_interpretation(85)
        assert "非常高" in interpretation

    def test_interpretation_medium(self, service):
        """测试中等分解释"""
        interpretation = service.generate_interpretation(55)
        assert "一般" in interpretation

    def test_interpretation_low(self, service):
        """测试低分解释"""
        interpretation = service.generate_interpretation(15)
        assert "很低" in interpretation


class TestChatPositivityIntegration:
    """聊天积极度服务集成测试"""

    def test_calculate_scores_full_pipeline(self):
        """测试完整计算流程"""
        # 跳过如果没有数据库
        pytest.skip("需要实际数据库进行集成测试")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
