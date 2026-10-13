"""权重归一引擎测试（点数制/缺席剔除/回退/配置覆盖）。"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.analysis.affinity_config import AffinityConfig, AffinityConfigService
from app.services.analysis.affinity_weights import (
    DEFAULT_WEIGHTS,
    apply_weight_normalization,
    resolve_dimension_plan,
)


def test_default_plan_without_keywords_disables_preference_and_llm():
    plan = resolve_dimension_plan(AffinityConfig(), llm_available=False)
    assert plan["preference_compatibility"]["enabled"] is False
    assert plan["llm_relationship"]["enabled"] is False
    # 本地三维持 8:7:3 相对关系（互动投入/情感共鸣/亲近信号）
    assert plan["interaction_investment"]["declared"] == 0.40
    assert plan["emotional_resonance"]["declared"] == 0.35
    assert plan["closeness_signals"]["declared"] == 0.15


def test_default_weights_cover_five_dimensions():
    assert set(DEFAULT_WEIGHTS) == {
        "interaction_investment",
        "emotional_resonance",
        "closeness_signals",
        "preference_compatibility",
        "llm_relationship",
    }


def test_preference_enabled_when_keywords_present():
    config = AffinityConfig(preference_keywords=["钓鱼"])
    plan = resolve_dimension_plan(config, llm_available=False)
    assert plan["preference_compatibility"]["enabled"] is True


def test_llm_enabled_only_when_available_and_switched_on():
    plan = resolve_dimension_plan(AffinityConfig(), llm_available=True)
    assert plan["llm_relationship"]["enabled"] is True
    plan = resolve_dimension_plan(
        AffinityConfig(llm_relationship_enabled=False), llm_available=True
    )
    assert plan["llm_relationship"]["enabled"] is False


class _Dim:
    def __init__(self, score, weight):
        self.score = score
        self.weight = weight
        self.weighted_score = score * weight


class _Result:
    def __init__(self, **dims):
        for key in (
            "interaction_investment",
            "emotional_resonance",
            "closeness_signals",
            "preference_compatibility",
            "llm_relationship",
        ):
            setattr(self, key, dims.get(key))


def test_normalization_excludes_absent_llm_dimension():
    result = _Result(
        interaction_investment=_Dim(80, 0.40),
        emotional_resonance=_Dim(60, 0.35),
        closeness_signals=_Dim(40, 0.15),
        llm_relationship=None,
    )
    effective = apply_weight_normalization(result)
    assert abs(sum(effective.values()) - 1.0) < 1e-9
    assert "llm_relationship" not in effective
    assert abs(result.interaction_investment.weight - 0.40 / 0.90) < 1e-9


def test_normalization_includes_preference_when_declared():
    result = _Result(
        interaction_investment=_Dim(80, 0.40),
        emotional_resonance=_Dim(60, 0.35),
        closeness_signals=_Dim(40, 0.15),
        preference_compatibility=_Dim(70, 0.10),
        llm_relationship=None,
    )
    effective = apply_weight_normalization(result)
    assert abs(sum(effective.values()) - 1.0) < 1e-9
    assert "preference_compatibility" in effective
    # weighted_score 被归一后权重覆写
    assert abs(
        result.preference_compatibility.weighted_score
        - 70 * (0.10 / 1.00)
    ) < 1e-9


def test_all_zero_declared_falls_back_to_three_local_dims():
    result = _Result(
        interaction_investment=_Dim(80, 0.0),
        emotional_resonance=_Dim(60, 0.0),
        closeness_signals=_Dim(40, 0.0),
    )
    effective = apply_weight_normalization(result)
    # Σ=0 → 回退本地三维默认（0.40/0.35/0.15 → 归一 8:7:3）
    assert abs(sum(effective.values()) - 1.0) < 1e-9
    assert set(effective) == {
        "interaction_investment", "emotional_resonance", "closeness_signals",
    }
    assert abs(effective["interaction_investment"] - 0.40 / 0.90) < 1e-9


def test_config_weight_override_takes_effect():
    config = AffinityConfig(
        weight_interaction_investment=0.80, weight_closeness_signals=0.0
    )
    plan = resolve_dimension_plan(config, llm_available=False)
    assert plan["interaction_investment"]["declared"] == 0.80
    assert plan["closeness_signals"]["declared"] == 0.0
    # declared=0 视为缺席（归一剔除）
    result = _Result(
        interaction_investment=_Dim(80, 0.80),
        emotional_resonance=_Dim(60, 0.35),
        closeness_signals=_Dim(40, 0.0),
    )
    effective = apply_weight_normalization(result)
    assert "closeness_signals" not in effective


def test_validate_rejects_negative_and_all_zero_weights():
    service = AffinityConfigService()
    try:
        service.validate_config(AffinityConfig(weight_closeness_signals=-0.1))
        raise AssertionError("负权重应被拒绝")
    except ValueError:
        pass
    try:
        service.validate_config(
            AffinityConfig(
                weight_interaction_investment=0.0,
                weight_emotional_resonance=0.0,
                weight_closeness_signals=0.0,
                weight_preference_compatibility=0.0,
                weight_llm_relationship=0.0,
            )
        )
        raise AssertionError("全零权重应被拒绝")
    except ValueError:
        pass
