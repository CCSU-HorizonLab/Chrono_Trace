"""模板建议引擎单元测试

测试 TemplateSuggestionEngine 的 18 种组合 + fallback
"""

import sys
import os
import time

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from app.services.realtime.suggestion_engine import (
    SuggestionEngine,
    SuggestionResult,
    SuggestionEngineFactory,
)
from app.services.realtime.template_engine import TemplateSuggestionEngine
from app.services.realtime.suggestion_templates import VALID_TRIGGER_TYPES, VALID_INTENTS


class TestTemplateSuggestionEngine:
    """模板引擎测试"""

    @pytest.fixture
    def engine(self):
        return TemplateSuggestionEngine()

    def test_all_18_combinations(self, engine):
        """所有 18 种 trigger × intent 组合都应返回有效结果"""
        for trigger_type in VALID_TRIGGER_TYPES:
            for intent in VALID_INTENTS:
                result = engine.generate(trigger_type, intent)

                assert isinstance(result, SuggestionResult)
                assert result.trigger_type == trigger_type
                assert result.intent == intent
                assert len(result.summary) > 0, (
                    f"摘要不应为空: {trigger_type} × {intent}"
                )
                assert len(result.speeches) >= 2, (
                    f"话术至少 2 条: {trigger_type} × {intent}"
                )
                assert result.severity in ("high", "medium", "low")
                assert 0 <= result.confidence <= 1

                print(f"✓ {trigger_type} × {intent}: {result.summary}")

    def test_unknown_trigger_fallback(self, engine):
        """未知触发类型应返回兜底建议"""
        result = engine.generate("nonexistent_trigger", "intimate")

        assert isinstance(result, SuggestionResult)
        assert result.confidence < 1.0
        assert len(result.summary) > 0
        print(f"✓ 兜底建议: {result.summary}")

    def test_unknown_intent_fallback(self, engine):
        """未知走向应兜底到 maintain"""
        result = engine.generate("negative_streak", "unknown_intent")

        assert isinstance(result, SuggestionResult)
        assert result.intent == "maintain"
        print(f"✓ 走向兜底: {result.intent}")

    def test_speeches_are_independent_copies(self, engine):
        """修改返回的话术列表不应影响后续调用"""
        result1 = engine.generate("negative_streak", "intimate")
        original_len = len(result1.speeches)
        result1.speeches.append("被修改的话术")

        result2 = engine.generate("negative_streak", "intimate")
        assert len(result2.speeches) == original_len

    def test_different_intents_produce_different_results(self, engine):
        """同一触发类型不同走向应返回不同内容"""
        r_intimate = engine.generate("negative_streak", "intimate")
        r_distance = engine.generate("negative_streak", "distance")

        assert r_intimate.summary != r_distance.summary
        assert r_intimate.speeches != r_distance.speeches
        print(f"✓ 亲密: {r_intimate.summary}")
        print(f"✓ 疏远: {r_distance.summary}")


class TestSuggestionEngineFactory:
    """引擎工厂测试"""

    def test_create_template_engine(self):
        """工厂应能创建模板引擎"""
        # 清除缓存
        SuggestionEngineFactory._engine_cache.clear()

        engine = SuggestionEngineFactory.create("template")
        assert isinstance(engine, TemplateSuggestionEngine)

    def test_factory_caches_instance(self):
        """工厂应缓存引擎实例"""
        SuggestionEngineFactory._engine_cache.clear()

        engine1 = SuggestionEngineFactory.create("template")
        engine2 = SuggestionEngineFactory.create("template")
        assert engine1 is engine2

    def test_unknown_engine_raises(self):
        """未知引擎类型应抛异常"""
        with pytest.raises(ValueError):
            SuggestionEngineFactory.create("unknown")

    def test_llm_not_implemented(self):
        """LLM 引擎应提示未实现"""
        with pytest.raises(NotImplementedError):
            SuggestionEngineFactory.create("local_llm")


class TestEnginePerformance:
    """引擎性能测试"""

    def test_template_latency(self):
        """模板引擎生成延迟应 < 10ms"""
        engine = TemplateSuggestionEngine()

        start = time.perf_counter()
        iterations = 1000
        for _ in range(iterations):
            engine.generate("negative_streak", "intimate")

        elapsed_ms = (time.perf_counter() - start) * 1000 / iterations
        print(f"✓ 模板引擎平均耗时: {elapsed_ms:.4f}ms")
        assert elapsed_ms < 10, f"延迟 {elapsed_ms:.4f}ms 超过 10ms 限制"


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
