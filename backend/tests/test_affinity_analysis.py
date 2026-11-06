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

from app.webview.api.affinity import AffinityApiMixin  # noqa: E402


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
             patch('app.services.analysis.affinity_analysis_service.PreferenceCompatibilityService') as MockPreference, \
             patch('app.services.analysis.affinity_analysis_service.EmotionalResonanceService') as MockResonance, \
             patch('app.services.analysis.affinity_analysis_service.InteractionInvestmentService') as MockInvestment, \
             patch('app.services.analysis.affinity_analysis_service.ClosenessSignalsService') as MockCloseness, \
             patch('app.services.analysis.affinity_analysis_service.EngagementMetricsService') as MockEngagement, \
             patch('app.services.analysis.relationship_llm_service.build_relationship_llm_service', return_value=None):

            # 配置 mock
            MockPreprocessing.return_value.orchestrate_preprocessing.return_value = mock_stats
            MockPreprocessing.return_value.get_preprocessed_statistics.return_value = mock_stats

            from app.services.analysis.affinity_config import AffinityConfig
            MockConfig.return_value.get_config.return_value = AffinityConfig()

            MockResonance.return_value.calculate_overall_resonance.return_value = {
                'overall_score': 80.0,
                'interpretation': '共鸣良好',
                'sub_scores': {
                    'bidirectional_positive_response': 80.0,
                    'polarity_consistency': 80.0,
                    'intensity_matching': 80.0,
                    'valence_balance': 80.0,
                    'perfunctory_reply': 80.0,
                    'empathy_recognition': 80.0,
                    'negative_resolution': 80.0
                },
                'bonus_scores': {
                    'base_resonance_score': 80.0,
                    'empathy_recognition_bonus': 8.0,
                    'negative_resolution_bonus': 8.0,
                    'trust_venting_bonus': 4.0
                }
            }

            MockCloseness.return_value.calculate_overall_closeness.return_value = {
                'overall_score': 70.0,
                'interpretation': '亲近信号中等：称谓保持稳定',
                'sub_scores': {
                    'address_term_evolution': 50.0,
                    'late_night_engagement': 60.0,
                    'active_coverage': 70.0,
                    'greeting_initiation': 50.0,
                    'icebreaking': 50.0,
                    'community_expression': 50.0,
                },
                'bonus_scores': {'total_bonus': 5.0},
                'confidence_meta': {},
            }

            from app.services.analysis.interaction_investment_service import InteractionInvestmentResult
            investment_result = InteractionInvestmentResult()
            investment_result.overall_score = 75.0
            investment_result.interpretation = "投入较高"
            investment_result.confidence_meta = {}
            MockInvestment.return_value.calculate_scores.return_value = investment_result

            from app.services.analysis.preference_compatibility_service import PreferenceCompatibilityResult
            preference_result = PreferenceCompatibilityResult()
            preference_result.overall_score = 60.0
            preference_result.interpretation = "兴趣较契合"
            MockPreference.return_value.calculate_scores.return_value = preference_result

            MockEngagement.return_value.compute.return_value = MagicMock()

            from app.services.analysis.affinity_analysis_service import AffinityAnalysisService
            yield AffinityAnalysisService()

    def test_confidence_shrinkage_uses_power_curve(self, service):
        """娴嬭瘯缃俊搴︽敹缂╀娇鐢ㄥ箓寰嬫洸绾?"""
        adjusted = service._apply_confidence_shrinkage(80.0, 0.6, 35.0)

        assert adjusted == pytest.approx(55.91, abs=0.01)

    def test_sigmoid_calibrate_rebalances_mid_scores(self, service):
        """娴嬭瘯 Sigmoid 鏍″噯鍖栧悗鐨勫垎甯?"""
        calibrated = service._sigmoid_calibrate(55.0)

        assert calibrated == 50.0

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

        # 互动投入应该有值
        assert result.interaction_investment is not None
        assert result.interaction_investment.score == 75.0

        # 喜好兼容度应该有值
        assert result.preference_compatibility is not None
        assert result.preference_compatibility.score == 60.0
        assert result.preference_compatibility.weight == 0.0
        assert result.preference_compatibility.weighted_score == 0.0
        assert result.preference_compatibility.bonus_scores["preference_bonus"] == 6.0
        assert result.emotional_resonance is not None
        assert result.emotional_resonance.bonus_scores["base_resonance_score"] == 80.0
        assert result.emotional_resonance.bonus_scores["empathy_recognition_bonus"] == 8.0
        assert result.closeness_signals is not None
        assert result.closeness_signals.score == 70.0
        # LLM 维缺席且给出可读原因
        assert result.llm_relationship is None
        assert result.llm_relationship_absent_reason

    def test_preference_participates_in_weighted_total(self, service):
        """点数制归一后：在场维度权重和为 1，各维 weighted=score×weight。

        旧加分制（_calculate_decayed_bonus 相加）已随权重引擎退役——
        偏好维现在作为正式维度参与归一，不再叠加 bonus。
        """
        result = service.analyze(1)

        dims = [
            result.interaction_investment,
            result.emotional_resonance,
            result.closeness_signals,
            result.preference_compatibility,
        ]
        present = [d for d in dims if d is not None and d.weight > 0]
        assert present, "至少三本地维应在场"
        assert sum(d.weight for d in present) == pytest.approx(1.0, abs=1e-9)
        for d in present:
            assert d.weighted_score == pytest.approx(d.score * d.weight, abs=1e-9)

    def test_analyze_calculates_overall_score(self, service):
        """测试计算综合评分"""
        result = service.analyze(1)
        
        # 综合评分应该大于 0
        assert result.overall_score > 0
        assert result.overall_interpretation != ""
        assert result.cache_version == service.CACHE_SCHEMA_VERSION

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
        interpretation = service._generate_overall_interpretation(45)
        assert "中等" in interpretation

    def test_interpretation_low_score(self, service):
        """测试低分解释"""
        interpretation = service._generate_overall_interpretation(15)
        assert "很低" in interpretation


    def test_analyze_llm_nonabsent_exception_becomes_absent(self, service):
        """LLM 维非 Absent 异常（如模型输出 sub_scores 为数组的解析异常）
        必须转缺席，不得炸掉整个四维+LLM 分析（第三轮抽查 W7）。

        旧实现只捕获 RelationshipLLMAbsent：非 Absent 异常从 fut_llm.result()
        直接向外抛，四个本地维度的结果全部丢弃。
        """
        from app.services.analysis.relationship_llm_service import RelationshipLLMAbsent  # noqa: F401 确认可导入

        fake_llm = MagicMock()
        fake_llm.evaluate.side_effect = ValueError("sub_scores 解析失败: list indices must be integers")

        with patch(
            'app.services.analysis.relationship_llm_service.build_relationship_llm_service',
            return_value=fake_llm,
        ):
            result = service.analyze(1)  # 修复前此处直接抛 ValueError

        assert result.status == "completed", "本地维度结果不得因 LLM 异常整体报废"
        assert result.llm_relationship is None
        assert "评估异常" in (result.llm_relationship_absent_reason or "")
        assert result.interaction_investment is not None
        assert result.emotional_resonance is not None


class TestRetryLlmRelationship:
    """补评 AI 关系评估（LLM 维瞬时缺席后的恢复通道）"""

    @pytest.fixture
    def mock_db(self):
        mock = MagicMock()
        mock.execute.return_value.fetchone.return_value = None
        return mock

    @pytest.fixture
    def mock_stats(self):
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
        """与 TestAffinityAnalysisService 同款 mock 基座（LLM 服务默认 None）"""
        with patch('app.services.analysis.affinity_analysis_service.get_db', return_value=mock_db), \
             patch('app.services.analysis.affinity_analysis_service.PreprocessingOrchestrator') as MockPreprocessing, \
             patch('app.services.analysis.affinity_analysis_service.AffinityConfigService') as MockConfig, \
             patch('app.services.analysis.affinity_analysis_service.PreferenceCompatibilityService'), \
             patch('app.services.analysis.affinity_analysis_service.EmotionalResonanceService'), \
             patch('app.services.analysis.affinity_analysis_service.InteractionInvestmentService'), \
             patch('app.services.analysis.affinity_analysis_service.ClosenessSignalsService'), \
             patch('app.services.analysis.affinity_analysis_service.EngagementMetricsService') as MockEngagement, \
             patch('app.services.analysis.affinity_analysis_service.RiskSignalService') as MockRisk, \
             patch('app.services.analysis.relationship_llm_service.build_relationship_llm_service', return_value=None):
            MockPreprocessing.return_value.get_preprocessed_statistics.return_value = mock_stats
            from app.services.analysis.affinity_config import AffinityConfig
            MockConfig.return_value.get_config.return_value = AffinityConfig()
            MockEngagement.return_value.compute.return_value = MagicMock()
            MockRisk.return_value.assess.return_value = None
            from app.services.analysis.affinity_analysis_service import AffinityAnalysisService
            yield AffinityAnalysisService()

    @staticmethod
    def _cached_result_with_llm_absent():
        """四个本地维度在场、LLM 维缺席的已完成缓存结果（网络故障现场）"""
        from app.services.analysis.affinity_analysis_service import (
            AffinityAnalysisResult,
            DimensionScore,
        )

        result = AffinityAnalysisResult()
        result.conversation_id = 1
        result.status = "completed"
        result.overall_score = 60.0
        result.interaction_investment = DimensionScore(
            name="互动投入", score=75.0, weight=0.42, weighted_score=31.5,
            interpretation="投入较高",
        )
        result.emotional_resonance = DimensionScore(
            name="情感共鸣", score=80.0, weight=0.37, weighted_score=29.6,
            interpretation="共鸣良好",
        )
        result.closeness_signals = DimensionScore(
            name="亲近信号", score=70.0, weight=0.21, weighted_score=14.7,
            interpretation="亲近信号中等",
        )
        result.preference_compatibility = DimensionScore(
            name="喜好兼容度", score=60.0, weight=0.0, weighted_score=0.0,
            interpretation="兴趣较契合",
        )
        result.llm_relationship = None
        result.llm_relationship_absent_reason = "LLM 调用失败: [Errno 113] 没有到主机的路由"
        return result

    def test_retry_fills_llm_dimension_and_rescores(self, service):
        """补评成功：LLM 维在场、缺席原因清空、总分按五维归一重算、任务可查进度"""
        cached = self._cached_result_with_llm_absent()
        service._load_cached_scores = lambda cid: cached

        fake_llm = MagicMock()
        fake_llm.evaluate.return_value = {
            "score": 85.0,
            "sub_scores": {"communication_quality": 88.0, "relationship_warmth": 82.0},
            "evidence": [{"quote": "在呢", "month": "2024-05"}],
            "insight": "沟通顺畅",
            "meta": {"model_name": "test-model"},
        }
        with patch(
            'app.services.analysis.relationship_llm_service.build_relationship_llm_service',
            return_value=fake_llm,
        ):
            result = service.retry_llm_relationship(1, "affinity_llm_1_t1")

        assert result.status == "completed"
        assert result.llm_relationship is not None
        assert result.llm_relationship.score == 85.0
        assert result.llm_relationship_absent_reason is None
        # LLM 维在场后权重按声明值归一（默认配置无关键词：偏好维缺席，
        # 分母 0.40+0.35+0.15+0.08=0.98）——缓存里已被归一覆写的本地维
        # 权重必须先复位为声明值，否则双次归一（0.08/1.08）口径失真
        assert result.llm_relationship.weight == pytest.approx(0.08 / 0.98, rel=1e-6)
        assert result.interaction_investment.weight == pytest.approx(0.40 / 0.98, rel=1e-6)
        assert sum(
            d.weight for d in (
                result.interaction_investment, result.emotional_resonance,
                result.closeness_signals, result.llm_relationship,
            ) if d and d.weight > 0
        ) == pytest.approx(1.0, abs=1e-6)
        # 风险预警随证据重判（mock assess 被调用且带 llm_result）
        from app.services.analysis.affinity_analysis_service import RiskSignalService
        RiskSignalService().assess.assert_called_once()
        assert service.get_progress("affinity_llm_1_t1") is result

    def test_retry_no_cache_fails_with_guidance(self, service):
        """无缓存（首析/配置已变更）：failed 且提示走全面分析，不抛异常"""
        service._load_cached_scores = lambda cid: None
        result = service.retry_llm_relationship(1, "affinity_llm_1_t2")
        assert result.status == "failed"
        assert "全面分析" in result.error

    def test_retry_skipped_when_llm_already_present(self, service):
        """LLM 维已在场：幂等守卫直接 failed"""
        cached = self._cached_result_with_llm_absent()
        cached.llm_relationship = cached.interaction_investment  # 任意在场维度
        cached.llm_relationship_absent_reason = None
        service._load_cached_scores = lambda cid: cached
        result = service.retry_llm_relationship(1, "affinity_llm_1_t3")
        assert result.status == "failed"
        assert "已在场" in result.error

    def test_retry_absent_again_reports_reason(self, service):
        """重评仍缺席（如网络未恢复）：failed 且错误带原因，缺席说明保留"""
        from app.services.analysis.relationship_llm_service import RelationshipLLMAbsent

        cached = self._cached_result_with_llm_absent()
        service._load_cached_scores = lambda cid: cached
        fake_llm = MagicMock()
        fake_llm.evaluate.side_effect = RelationshipLLMAbsent("网络仍不可达")
        with patch(
            'app.services.analysis.relationship_llm_service.build_relationship_llm_service',
            return_value=fake_llm,
        ):
            result = service.retry_llm_relationship(1, "affinity_llm_1_t4")
        assert result.status == "failed"
        assert "网络仍不可达" in result.error
        # 缓存结果不被失败污染：LLM 维仍缺席、原缺席原因保留
        assert result.llm_relationship is None

    def test_retry_without_llm_config_fails(self, service):
        """未配置 LLM 模型（fixture 默认 None）：failed 且提示可配置"""
        cached = self._cached_result_with_llm_absent()
        service._load_cached_scores = lambda cid: cached
        result = service.retry_llm_relationship(1, "affinity_llm_1_t5")
        assert result.status == "failed"
        assert "未配置" in result.error


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


def _fake_llm_payload(score=72.0):
    """LLM 关系评估的正常返回载荷（与 relationship_llm_service 契约一致）"""
    return {
        "score": score,
        "insight": "整体关系积极，互动稳定",
        "sub_scores": {"communication": 75.0, "trust": 70.0},
        "evidence": ["对方主动分享日常"],
        "meta": {"model_name": "test-model"},
    }


class TestProgressiveTwoPhase:
    """本地四维先行、LLM 评估后补的双阶段编排"""

    @pytest.fixture
    def mock_db(self):
        mock = MagicMock()
        mock.execute.return_value.fetchone.return_value = None
        return mock

    @pytest.fixture
    def mock_stats(self):
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
        """与 TestAffinityAnalysisService 同款可跑通 analyze 的 mock 基座
        （LLM 服务默认 None，测试内按需 patch 成 fake_llm）"""
        with patch('app.services.analysis.affinity_analysis_service.get_db', return_value=mock_db), \
             patch('app.services.analysis.affinity_analysis_service.PreprocessingOrchestrator') as MockPreprocessing, \
             patch('app.services.analysis.affinity_analysis_service.AffinityConfigService') as MockConfig, \
             patch('app.services.analysis.affinity_analysis_service.PreferenceCompatibilityService') as MockPreference, \
             patch('app.services.analysis.affinity_analysis_service.EmotionalResonanceService') as MockResonance, \
             patch('app.services.analysis.affinity_analysis_service.InteractionInvestmentService') as MockInvestment, \
             patch('app.services.analysis.affinity_analysis_service.ClosenessSignalsService') as MockCloseness, \
             patch('app.services.analysis.affinity_analysis_service.EngagementMetricsService') as MockEngagement, \
             patch('app.services.analysis.affinity_analysis_service.RiskSignalService') as MockRisk, \
             patch('app.services.analysis.relationship_llm_service.build_relationship_llm_service', return_value=None):

            MockPreprocessing.return_value.orchestrate_preprocessing.return_value = mock_stats
            MockPreprocessing.return_value.get_preprocessed_statistics.return_value = mock_stats
            from app.services.analysis.affinity_config import AffinityConfig
            MockConfig.return_value.get_config.return_value = AffinityConfig()

            MockResonance.return_value.calculate_overall_resonance.return_value = {
                'overall_score': 80.0,
                'interpretation': '共鸣良好',
                'sub_scores': {k: 80.0 for k in (
                    'bidirectional_positive_response', 'polarity_consistency',
                    'intensity_matching', 'valence_balance', 'perfunctory_reply',
                    'empathy_recognition', 'negative_resolution',
                )},
                'bonus_scores': {'base_resonance_score': 80.0},
            }
            MockCloseness.return_value.calculate_overall_closeness.return_value = {
                'overall_score': 70.0,
                'interpretation': '亲近信号中等',
                'sub_scores': {k: 50.0 for k in (
                    'address_term_evolution', 'late_night_engagement', 'active_coverage',
                    'greeting_initiation', 'icebreaking', 'community_expression',
                )},
                'bonus_scores': {'total_bonus': 5.0},
                'confidence_meta': {},
            }

            from app.services.analysis.interaction_investment_service import InteractionInvestmentResult
            investment_result = InteractionInvestmentResult()
            investment_result.overall_score = 75.0
            investment_result.interpretation = "投入较高"
            investment_result.confidence_meta = {}
            MockInvestment.return_value.calculate_scores.return_value = investment_result

            from app.services.analysis.preference_compatibility_service import PreferenceCompatibilityResult
            preference_result = PreferenceCompatibilityResult()
            preference_result.overall_score = 60.0
            preference_result.interpretation = "兴趣较契合"
            MockPreference.return_value.calculate_scores.return_value = preference_result

            MockEngagement.return_value.compute.return_value = MagicMock()
            MockRisk.return_value.assess.return_value = None

            from app.services.analysis.affinity_analysis_service import AffinityAnalysisService
            yield AffinityAnalysisService()

    def _settings_saves(self, mock_db):
        """按顺序取出全部 settings 主缓存写入的 JSON dict"""
        saves = []
        for call in mock_db.execute.call_args_list:
            if "INSERT OR REPLACE INTO settings" in call.args[0]:
                saves.append(json.loads(call.args[1][1]))
        return saves

    def test_partial_save_then_final(self, service, mock_db):
        """LLM 在场：本地终态先落部分结果（sentinel + 存储态 completed），
        LLM 返回后覆盖为终态——evaluate 被调时应观察到 llm_pending 任务态"""
        from app.services.analysis.affinity_analysis_service import LLM_EVALUATING_REASON

        observed = {}

        def evaluate(conv_id, **kw):
            task = next(iter(service._task_status.values()))
            observed["status"] = task.status
            observed["absent"] = task.llm_relationship_absent_reason
            return _fake_llm_payload()

        fake_llm = MagicMock()
        fake_llm.evaluate.side_effect = evaluate
        with patch(
            'app.services.analysis.relationship_llm_service.build_relationship_llm_service',
            return_value=fake_llm,
        ):
            result = service.analyze(1, force_reanalyze=True)

        # 阶段 2 起跑时的任务态：llm_pending + sentinel（供前端渐进渲染）
        assert observed["status"] == "llm_pending"
        assert observed["absent"] == LLM_EVALUATING_REASON
        # 终态
        assert result.status == "completed"
        assert result.llm_relationship is not None
        assert result.llm_relationship.score == 72.0
        assert result.llm_relationship_absent_reason is None

        # 两次主缓存写入：部分（sentinel/无 LLM/权重本地归一）→ 终态（LLM 在场）
        saves = self._settings_saves(mock_db)
        assert len(saves) == 2
        assert saves[0]["status"] == "completed"          # 存储态恒为 completed
        assert saves[0]["llm_relationship"] is None
        assert saves[0]["llm_relationship_absent_reason"] == LLM_EVALUATING_REASON
        assert saves[1]["llm_relationship"] is not None
        assert saves[1]["llm_relationship_absent_reason"] is None

    def test_partial_save_skips_history_final_records_once(self, service, mock_db):
        """一次全面分析只在终态保存落一行历史（部分结果不落，防趋势自比）"""
        fake_llm = MagicMock()
        fake_llm.evaluate.return_value = _fake_llm_payload()
        with patch(
            'app.services.analysis.relationship_llm_service.build_relationship_llm_service',
            return_value=fake_llm,
        ), patch(
            'app.services.analysis.affinity_history.record_score_history'
        ) as mock_history:
            service.analyze(1, force_reanalyze=True)

        assert mock_history.call_count == 1

    def test_on_local_complete_fires_once(self, service):
        """清 stale + 记忆索引入队在本地完成点恰触发一次（LLM 在场与否同口径）"""
        fake_llm = MagicMock()
        fake_llm.evaluate.return_value = _fake_llm_payload()
        for llm_mock in (fake_llm, None):
            for tid in list(service._task_status):
                service._task_status.pop(tid, None)
            with patch(
                'app.services.analysis.relationship_llm_service.build_relationship_llm_service',
                return_value=llm_mock,
            ), patch.object(
                type(service), '_on_local_complete'
            ) as mock_local_complete:
                service.analyze(2, force_reanalyze=True)

            assert mock_local_complete.call_count == 1

    def test_on_local_complete_enqueues_rag_when_account_known(self, service, mock_db):
        """账号可查时本地完成点入队记忆索引（其余跳过条件属 bridge 侧）"""
        row = MagicMock()
        row.__getitem__.side_effect = lambda k: "wxid_acc" if k == "account_wxid" else ""
        mock_db.execute.return_value.fetchone.return_value = row
        with patch('app.db.connection.get_db', return_value=mock_db), \
             patch('app.db.connection.optimize_query_plans'), \
             patch('app.services.analysis.analysis_state.mark_analysis_complete'), \
             patch('app.services.realtime.rag.indexer.RagIndexQueue.enqueue') as mock_enqueue:
            service._on_local_complete(5)

        mock_enqueue.assert_called_once_with("wxid_acc", 5)

    def test_llm_absent_error_still_saves_final(self, service, mock_db):
        """评估异常转缺席：部分结果照落，终态带真因文案与历史行"""
        fake_llm = MagicMock()
        fake_llm.evaluate.side_effect = RuntimeError("输出结构异常")
        with patch(
            'app.services.analysis.relationship_llm_service.build_relationship_llm_service',
            return_value=fake_llm,
        ):
            result = service.analyze(1, force_reanalyze=True)

        assert result.status == "completed"
        assert result.llm_relationship is None
        assert "评估异常" in (result.llm_relationship_absent_reason or "")
        saves = self._settings_saves(mock_db)
        assert len(saves) == 2
        assert "评估异常" in saves[1]["llm_relationship_absent_reason"]

    def test_cancel_during_llm_phase_keeps_partial_result(self, service, mock_db):
        """评估中取消：状态 cancelled，部分结果留在缓存（可经补评恢复）"""
        import threading
        import time as _time

        cancel_event = threading.Event()

        def evaluate(conv_id, **kw):
            cancel_event.set()       # 模拟用户在远程调用期间点停止
            _time.sleep(0.3)         # 在途调用，孤儿线程自然跑完丢弃
            return _fake_llm_payload()

        fake_llm = MagicMock()
        fake_llm.evaluate.side_effect = evaluate
        with patch(
            'app.services.analysis.relationship_llm_service.build_relationship_llm_service',
            return_value=fake_llm,
        ):
            result = service.analyze(1, force_reanalyze=True, cancel_event=cancel_event)

        assert result.status == "cancelled"
        # 恰一次主缓存写入 = 部分结果（终态保存未到达）
        saves = self._settings_saves(mock_db)
        assert len(saves) == 1
        assert saves[0]["llm_relationship"] is None
        assert saves[0]["llm_relationship_absent_reason"] is not None

    def test_without_llm_skips_pending_state(self, service, mock_db):
        """LLM 不在场：不经过 llm_pending/部分落库，直接终态一次保存"""
        save_calls = []

        orig_save = service._save_results

        def spy_save(conv_id, result, record_history=True):
            save_calls.append((result.status, record_history))
            return orig_save(conv_id, result, record_history=record_history)

        service._save_results = spy_save
        service.analyze(1, force_reanalyze=True)

        assert save_calls == [("completed", True)]


class _FakeProgressService:
    """bridge 进度查询的最小桩：直接返回预置任务结果"""

    def __init__(self, progress):
        self._progress = progress

    def get_progress(self, task_id):
        return self._progress


class _AffinityBridge(AffinityApiMixin):
    """组合好感度 mixin 的直调桥（生产 Bridge 同构）"""

    def __init__(self, service=None, services=None):
        if service is not None:
            self._affinity_service = service
        if services is not None:
            self._affinity_services = services


class TestAffinityBridgeProgressive:
    """bridge 层：llm_pending 带部分结果 + 残留 sentinel 归一"""

    def test_progress_carries_result_on_llm_pending(self):
        from app.services.analysis.affinity_analysis_service import AffinityAnalysisResult

        progress = AffinityAnalysisResult()
        progress.status = "llm_pending"
        progress.progress_percent = 85
        progress.overall_score = 70.0

        bridge = _AffinityBridge(service=_FakeProgressService(progress))
        response = bridge.get_affinity_progress("t1")

        assert response["ok"] is True
        assert response["status"] == "llm_pending"
        assert response["result"]["overall_score"] == 70.0

    def test_scores_normalizes_stale_sentinel_when_idle(self):
        """评估中退出/崩溃的残留 sentinel：无运行任务时改写为可重试口径"""
        from app.services.analysis.affinity_analysis_service import (
            LLM_EVALUATING_REASON,
            AffinityAnalysisResult,
        )

        cached = AffinityAnalysisResult()
        cached.conversation_id = 1
        cached.llm_relationship = None
        cached.llm_relationship_absent_reason = LLM_EVALUATING_REASON

        fake_service = MagicMock()
        fake_service.get_scores.return_value = cached
        fake_service.find_running_task.return_value = None

        module = "app.services.analysis.affinity_analysis_service"
        with patch(f"{module}.AffinityAnalysisService", return_value=fake_service), patch(
            "app.services.analysis.analysis_state.get_analysis_freshness",
            return_value={"stale": False, "pending_message_count": 0},
        ), patch(
            "app.services.analysis.affinity_history.compute_trend", return_value={}
        ):
            response = _AffinityBridge(service=fake_service).get_affinity_scores(1)

        assert response["ok"] is True
        assert response["result"]["llm_relationship_absent_reason"] == "上次 AI 评估未完成，可点击重试补齐"

    def test_scores_keeps_sentinel_while_running(self):
        """评估仍在跑（任务挂在任一实例上）：sentinel 原样，前端经进度通道渲染"""
        from app.services.analysis.affinity_analysis_service import (
            LLM_EVALUATING_REASON,
            AffinityAnalysisResult,
        )

        cached = AffinityAnalysisResult()
        cached.conversation_id = 1
        cached.llm_relationship = None
        cached.llm_relationship_absent_reason = LLM_EVALUATING_REASON

        idle_service = MagicMock()
        idle_service.get_scores.return_value = cached
        idle_service.find_running_task.return_value = None
        busy_service = MagicMock()
        busy_service.find_running_task.return_value = "affinity_1_running"

        module = "app.services.analysis.affinity_analysis_service"
        with patch(f"{module}.AffinityAnalysisService", return_value=idle_service), patch(
            "app.services.analysis.analysis_state.get_analysis_freshness",
            return_value={"stale": False, "pending_message_count": 0},
        ), patch(
            "app.services.analysis.affinity_history.compute_trend", return_value={}
        ):
            bridge = _AffinityBridge(service=idle_service, services=[busy_service])
            response = bridge.get_affinity_scores(1)

        assert response["result"]["llm_relationship_absent_reason"] == LLM_EVALUATING_REASON


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
