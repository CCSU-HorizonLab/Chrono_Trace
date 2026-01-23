"""喜好兼容度服务测试

测试 PreferenceCompatibilityService 的 2 个子维度计算方法
"""

import pytest
import sys
import os
from unittest.mock import MagicMock, patch

# 添加项目路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))


class TestPreferenceCompatibilityService:
    """测试喜好兼容度服务"""

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
        stats.total_sessions = 100
        return stats

    @pytest.fixture
    def service(self, mock_db):
        """创建服务实例"""
        with patch('app.services.analysis.preference_compatibility_service.get_db', return_value=mock_db):
            from app.services.analysis.preference_compatibility_service import PreferenceCompatibilityService
            return PreferenceCompatibilityService(preference_keywords=["篮球", "电影", "旅行"])

    @pytest.fixture
    def empty_service(self, mock_db):
        """创建无关键词的服务实例"""
        with patch('app.services.analysis.preference_compatibility_service.get_db', return_value=mock_db):
            from app.services.analysis.preference_compatibility_service import PreferenceCompatibilityService
            return PreferenceCompatibilityService(preference_keywords=[])

    # ========================================
    # 话题提及频率测试
    # ========================================

    def test_topic_mention_high(self, service):
        """测试高话题提及率"""
        # 30% 以上提及率为满分
        score = service.calculate_topic_mention_score(30, 100)
        assert score == 100.0

    def test_topic_mention_low(self, service):
        """测试低话题提及率"""
        # 10% 提及率
        score = service.calculate_topic_mention_score(10, 100)
        assert 33 <= score <= 34

    def test_topic_mention_zero_sessions(self, service):
        """测试零会话"""
        score = service.calculate_topic_mention_score(0, 0)
        assert score == 0.0

    def test_topic_mention_no_matches(self, service):
        """测试无匹配"""
        score = service.calculate_topic_mention_score(0, 100)
        assert score == 0.0

    # ========================================
    # 话题延续性测试
    # ========================================

    def test_topic_continuity_high(self, service, mock_db):
        """测试高话题延续性"""
        mock_db.execute.return_value.fetchone.return_value = (0.8,)
        
        score = service.calculate_topic_continuity_score(1, [1, 2, 3])
        assert score == 80.0

    def test_topic_continuity_low(self, service, mock_db):
        """测试低话题延续性"""
        mock_db.execute.return_value.fetchone.return_value = (0.3,)
        
        score = service.calculate_topic_continuity_score(1, [1, 2])
        assert score == 30.0

    def test_topic_continuity_no_sessions(self, service, mock_db):
        """测试无会话"""
        score = service.calculate_topic_continuity_score(1, [])
        assert score == 0.0

    def test_topic_continuity_null(self, service, mock_db):
        """测试无相似度数据"""
        mock_db.execute.return_value.fetchone.return_value = (None,)
        
        score = service.calculate_topic_continuity_score(1, [1])
        assert score == 0.0

    # ========================================
    # 空关键词测试 (T038)
    # ========================================

    def test_empty_keywords_returns_zero(self, empty_service, mock_stats):
        """测试空关键词返回 0 分"""
        result = empty_service.calculate_scores(1, mock_stats)
        assert result.overall_score == 0.0
        assert "未设置" in result.interpretation

    def test_set_preference_keywords(self, empty_service):
        """测试设置喜好关键词"""
        empty_service.set_preference_keywords(["音乐", "游戏"])
        assert len(empty_service.preference_keywords) == 2
        assert "音乐" in empty_service.preference_keywords

    def test_set_empty_keywords(self, service):
        """测试设置空关键词列表"""
        service.set_preference_keywords([])
        assert len(service.preference_keywords) == 0

    def test_set_keywords_with_whitespace(self, empty_service):
        """测试带空白的关键词"""
        empty_service.set_preference_keywords(["  音乐  ", "", "  "])
        assert len(empty_service.preference_keywords) == 1
        assert empty_service.preference_keywords[0] == "音乐"

    # ========================================
    # 综合评分测试
    # ========================================

    def test_overall_score_weights(self, service):
        """测试综合评分权重正确"""
        from app.services.analysis.preference_compatibility_service import PreferenceCompatibilityResult
        
        result = PreferenceCompatibilityResult()
        result.topic_mention_score = 100
        result.topic_continuity_score = 100
        
        overall = service._calculate_overall_score(result)
        # 所有子维度都是 100，所以综合评分应该是 100
        assert overall == 100.0

    def test_overall_score_weighted(self, service):
        """测试加权计算"""
        from app.services.analysis.preference_compatibility_service import PreferenceCompatibilityResult
        
        result = PreferenceCompatibilityResult()
        result.topic_mention_score = 50  # 40% weight
        result.topic_continuity_score = 50  # 60% weight
        
        overall = service._calculate_overall_score(result)
        # 50 * 0.4 + 50 * 0.6 = 20 + 30 = 50
        assert overall == 50.0

    # ========================================
    # 解释文本测试
    # ========================================

    def test_interpretation_high(self, service):
        """测试高分解释"""
        interpretation = service.generate_interpretation(85)
        assert "高度契合" in interpretation

    def test_interpretation_medium(self, service):
        """测试中等分解释"""
        interpretation = service.generate_interpretation(55)
        assert "一般" in interpretation

    def test_interpretation_low(self, service):
        """测试低分解释"""
        interpretation = service.generate_interpretation(15)
        assert "很低" in interpretation


class TestAffinityConfigService:
    """测试配置服务"""

    @pytest.fixture
    def mock_db(self):
        """创建模拟数据库连接"""
        mock = MagicMock()
        return mock

    @pytest.fixture
    def service(self, mock_db):
        """创建服务实例"""
        with patch('app.services.analysis.affinity_config.get_db', return_value=mock_db):
            from app.services.analysis.affinity_config import AffinityConfigService
            return AffinityConfigService()

    def test_get_default_config(self, service, mock_db):
        """测试获取默认配置"""
        mock_db.execute.return_value.fetchone.return_value = None
        
        from app.services.analysis.affinity_config import AffinityConfig
        config = service.get_config(1)
        
        assert isinstance(config, AffinityConfig)
        assert config.weight_emotional_resonance == 0.30
        assert config.weight_chat_positivity == 0.30

    def test_validate_config_valid(self, service):
        """测试验证有效配置"""
        from app.services.analysis.affinity_config import AffinityConfig
        
        config = AffinityConfig()
        assert service.validate_config(config) == True

    def test_validate_config_invalid_weights(self, service):
        """测试验证无效权重"""
        from app.services.analysis.affinity_config import AffinityConfig
        
        config = AffinityConfig()
        config.weight_emotional_resonance = 0.5
        # 总权重 = 0.5 + 0.3 + 0.2 + 0.2 = 1.2
        
        with pytest.raises(ValueError) as excinfo:
            service.validate_config(config)
        assert "权重总和" in str(excinfo.value)

    def test_validate_config_negative_threshold(self, service):
        """测试验证负阈值"""
        from app.services.analysis.affinity_config import AffinityConfig
        
        config = AffinityConfig()
        config.reply_timeliness_threshold_seconds = -1
        
        with pytest.raises(ValueError) as excinfo:
            service.validate_config(config)
        assert "不能为负" in str(excinfo.value)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
