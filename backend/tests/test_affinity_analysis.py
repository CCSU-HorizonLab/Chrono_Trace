"""好感度分析编排器测试

测试 AffinityAnalysisService 的编排和评分逻辑
"""

import json
import pytest
import sys
import os
from unittest.mock import MagicMock, patch, PropertyMock

# 添加项目路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))


class TestAffinityAnalysisService:
    """测试好感度分析编排器"""

    @pytest.fixture
    def mock_db(self):
        """模拟数据库"""
        mock = MagicMock()
        mock.execute.return_value.fetchone.return_value = None
        return mock

    @pytest.fixture
    def mock_stats(self):
        """模拟预处理统计"""
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
    def service(self, mock_db, mock_stats):
        """创建服务实例"""
        with patch('app.services.analysis.affinity_analysis_service.get_db', return_value=mock_db), \
             patch('app.services.analysis.affinity_analysis_service.PreprocessingOrchestrator') as MockPreprocessing, \
             patch('app.services.analysis.affinity_analysis_service.AffinityConfigService') as MockConfig, \
             patch('app.services.analysis.affinity_analysis_service.ChatPositivityService') as MockPositivity, \
             patch('app.services.analysis.affinity_analysis_service.PreferenceCompatibilityService') as MockPreference, \
             patch('app.services.analysis.affinity_analysis_service.EmotionalResonanceService') as MockResonance, \
             patch('app.services.analysis.affinity_analysis_service.AttitudeTendencyService') as MockAttitude:
            
            # 配置 mock
            MockPreprocessing.return_value.orchestrate_preprocessing.return_value = mock_stats
            MockPreprocessing.return_value.get_preprocessed_statistics.return_value = mock_stats
            
            from app.services.analysis.affinity_config import AffinityConfig
            MockConfig.return_value.get_config.return_value = AffinityConfig()
            MockConfig.return_value.get_dimension_weights.return_value = {
                'emotional_resonance': 0.35,
                'chat_positivity': 0.35,
                'attitude_tendency': 0.20,
                'preference_compatibility': 0.10
            }
            
            MockResonance.return_value.calculate_overall_resonance.return_value = {
                'overall_score': 80.0,
                'interpretation': '共振良好',
                'sub_scores': {
                    'bidirectional_positive_response': 80.0,
                    'polarity_consistency': 80.0,
                    'intensity_matching': 80.0,
                    'empathy_recognition': 80.0,
                    'negative_resolution': 80.0
                },
                'bonus_scores': {
                    'base_resonance_score': 80.0,
                    'empathy_recognition_bonus': 8.0,
                    'negative_resolution_bonus': 8.0
                }
            }
            
            MockAttitude.return_value.calculate_overall_attitude.return_value = {
                'overall_score': 70.0,
                'interpretation': '态度良好',
                'sub_scores': {
                    'positive_emotion_frequency': 70.0,
                    'negative_emotion_frequency': 10.0
                },
                'bonus_scores': {
                    'multimedia_usage': 5.0
                }
            }
            
            from app.services.analysis.chat_positivity_service import ChatPositivityResult
            positivity_result = ChatPositivityResult()
            positivity_result.overall_score = 75.0
            positivity_result.interpretation = "积极度较高"
            MockPositivity.return_value.calculate_scores.return_value = positivity_result
            
            from app.services.analysis.preference_compatibility_service import PreferenceCompatibilityResult
            preference_result = PreferenceCompatibilityResult()
            preference_result.overall_score = 60.0
            preference_result.interpretation = "兴趣较契合"
            MockPreference.return_value.calculate_scores.return_value = preference_result
            
            from app.services.analysis.affinity_analysis_service import AffinityAnalysisService
            yield AffinityAnalysisService()

    # ========================================
    # 分析流程测试
    # ========================================

    def test_analyze_returns_result(self, service):
        """测试分析返回结果"""
        result = service.analyze(1)
        
        from app.services.analysis.affinity_analysis_service import AffinityAnalysisResult
        assert isinstance(result, AffinityAnalysisResult)
        assert result.conversation_id == 1
        assert result.status == "completed"

    def test_analyze_generates_task_id(self, service):
        """测试生成任务 ID"""
        result = service.analyze(1)
        
        assert result.task_id.startswith("affinity_1_")

    def test_analyze_calculates_dimensions(self, service):
        """测试计算各维度"""
        result = service.analyze(1)
        
        # 聊天积极度应该有值
        assert result.chat_positivity is not None
        assert result.chat_positivity.score == 75.0
        
        # 喜好兼容度应该有值
        assert result.preference_compatibility is not None
        assert result.preference_compatibility.score == 60.0
        assert result.emotional_resonance is not None
        assert result.emotional_resonance.bonus_scores["base_resonance_score"] == 80.0
        assert result.emotional_resonance.bonus_scores["empathy_recognition_bonus"] == 8.0

    def test_analyze_calculates_overall_score(self, service):
        """测试计算综合评分"""
        result = service.analyze(1)
        
        # 综合评分应该大于 0
        assert result.overall_score > 0
        assert result.overall_interpretation != ""

    # ========================================
    # 缓存测试
    # ========================================

    def test_get_scores_returns_none_when_no_cache(self, service):
        """测试无缓存时返回 None"""
        result = service.get_scores(1)
        assert result is None

    def test_get_scores_ignores_running_cache(self, service, mock_db):
        """未完成缓存不应被当作正式结果返回"""
        mock_db.execute.return_value.fetchone.return_value = (
            json.dumps({
                "overall_score": 12.3,
                "conversation_id": 1,
                "status": "running"
            }),
        )

        result = service.get_scores(1)
        assert result is None

    def test_reanalyze_clears_cache(self, service, mock_db):
        """测试重新分析清除缓存"""
        service.reanalyze(1)
        
        # 应该调用了缓存清除
        assert mock_db.execute.called

    # ========================================
    # 进度跟踪测试
    # ========================================

    def test_get_progress_returns_status(self, service):
        """测试获取任务进度"""
        result = service.analyze(1)
        
        progress = service.get_progress(result.task_id)
        assert progress is not None
        assert progress.status == "completed"
        assert progress.progress_percent == 100

    def test_analyze_saves_completed_result(self, service, mock_db):
        """保存缓存时应写入 completed 状态"""
        service.analyze(1)

        save_calls = [
            call for call in mock_db.execute.call_args_list
            if "INSERT OR REPLACE INTO settings" in call.args[0]
        ]
        assert save_calls

        saved_json = save_calls[-1].args[1][1]
        saved = json.loads(saved_json)
        assert saved["status"] == "completed"
        assert saved["analysis_timestamp"] > 0

    # ========================================
    # 解释文本测试
    # ========================================

    def test_interpretation_high_score(self, service):
        """测试高分解释"""
        interpretation = service._generate_overall_interpretation(85)
        assert "非常高" in interpretation

    def test_interpretation_medium_score(self, service):
        """测试中等分解释"""
        interpretation = service._generate_overall_interpretation(55)
        assert "一般" in interpretation

    def test_interpretation_low_score(self, service):
        """测试低分解释"""
        interpretation = service._generate_overall_interpretation(15)
        assert "很低" in interpretation


class TestDimensionScore:
    """测试维度评分数据类"""

    def test_dimension_score_creation(self):
        """测试创建维度评分"""
        from app.services.analysis.affinity_analysis_service import DimensionScore
        
        score = DimensionScore(
            name="测试维度",
            score=80.0,
            weight=0.25,
            weighted_score=20.0,
            interpretation="表现良好"
        )
        
        assert score.name == "测试维度"
        assert score.score == 80.0
        assert score.weight == 0.25


class TestAffinityAnalysisResult:
    """测试分析结果数据类"""

    def test_result_defaults(self):
        """测试默认值"""
        from app.services.analysis.affinity_analysis_service import AffinityAnalysisResult
        
        result = AffinityAnalysisResult()
        
        assert result.overall_score == 0.0
        assert result.status == "pending"
        assert result.progress_percent == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
