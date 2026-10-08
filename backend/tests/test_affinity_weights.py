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


def test_default_plan_without_keywords_prefers_three_legacy_ratio():
    plan = resolve_dimension_plan(AffinityConfig(), llm_available=False)
    assert plan["preference_compatibility"]["enabled"] is False
    assert plan["llm_relationship"]["enabled"] is False
    # 三老维 declared 保持 8:7:5（与历史口径 40/35/25 一致）
    assert plan["emotional_resonance"]["declared"] == 0.40
    assert plan["chat_positivity"]["declared"] == 0.35
    assert plan["attitude_tendency"]["declared"] == 0.25


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
            "emotional_resonance",
            "chat_positivity",
            "attitude_tendency",
            "preference_compatibility",
            "intimacy_signals",
            "llm_relationship",
        ):
            setattr(self, key, dims.get(key))


def test_normalization_excludes_absent_llm_dimension():
    result = _Result(
        emotional_resonance=_Dim(80, 0.40),
        chat_positivity=_Dim(60, 0.35),
        attitude_tendency=_Dim(40, 0.25),
        llm_relationship=None,
    )
    effective = apply_weight_normalization(result)
    assert abs(sum(effective.values()) - 1.0) < 1e-9
    assert "llm_relationship" not in effective
    assert abs(result.emotional_resonance.weight - 0.40 / 1.00) < 1e-9


def test_normalization_includes_preference_when_declared():
    result = _Result(
        emotional_resonance=_Dim(80, 0.40),
        chat_positivity=_Dim(60, 0.35),
        attitude_tendency=_Dim(40, 0.25),
        preference_compatibility=_Dim(70, 0.10),
        llm_relationship=None,
    )
    effective = apply_weight_normalization(result)
    assert abs(sum(effective.values()) - 1.0) < 1e-9
    assert "preference_compatibility" in effective
    # weighted_score 被归一后权重覆写
    assert abs(
        result.preference_compatibility.weighted_score
        - 70 * (0.10 / 1.10)
    ) < 1e-9


def test_all_zero_declared_falls_back_to_three_legacy_dims():
    result = _Result(
        emotional_resonance=_Dim(80, 0.0),
        chat_positivity=_Dim(60, 0.0),
        attitude_tendency=_Dim(40, 0.0),
    )
    effective = apply_weight_normalization(result)
    # Σ=0 → 回退三老维默认（0.40/0.35/0.25 → 归一 8:7:5）
    assert abs(sum(effective.values()) - 1.0) < 1e-9
    assert set(effective) == {"emotional_resonance", "chat_positivity", "attitude_tendency"}
    assert abs(effective["emotional_resonance"] - 0.40 / 1.00) < 1e-9


def test_config_weight_override_takes_effect():
    config = AffinityConfig(
        weight_emotional_resonance=0.80, weight_attitude_tendency=0.0
    )
    plan = resolve_dimension_plan(config, llm_available=False)
    assert plan["emotional_resonance"]["declared"] == 0.80
    assert plan["attitude_tendency"]["declared"] == 0.0
    # declared=0 视为缺席（归一剔除）
    result = _Result(
        emotional_resonance=_Dim(80, 0.80),
        chat_positivity=_Dim(60, 0.35),
        attitude_tendency=_Dim(40, 0.0),
    )
    effective = apply_weight_normalization(result)
    assert "attitude_tendency" not in effective


def test_validate_rejects_negative_and_all_zero_weights():
    service = AffinityConfigService()
    try:
        service.validate_config(AffinityConfig(weight_chat_positivity=-0.1))
        raise AssertionError("负权重应被拒绝")
    except ValueError:
        pass
    try:
        service.validate_config(
            AffinityConfig(
                weight_emotional_resonance=0.0,
                weight_chat_positivity=0.0,
                weight_attitude_tendency=0.0,
                weight_preference_compatibility=0.0,
                weight_intimacy_signals=0.0,
                weight_llm_relationship=0.0,
            )
        )
        raise AssertionError("全零权重应被拒绝")
    except ValueError:
        pass
