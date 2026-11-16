"""决策风格推断（GDMS）纯函数测试：映射方向、双通道合成、降级口径。"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.analysis.decision_style import (  # noqa: E402
    GDMS_DIMENSIONS,
    MIN_MESSAGES_FOR_SIGNALS,
    channel_a_scores,
    channel_b_scores,
    combine_channels,
    compute_decision_style,
    z_standardize,
)


def _big5(**over):
    base = {k: 50.0 for k in
            ("extraversion", "conscientiousness", "neuroticism", "agreeableness", "openness")}
    base.update(over)
    return base


def test_z_standardize_center_and_missing():
    z = z_standardize(_big5(extraversion=80))
    assert z["extraversion"] == 2.0  # (80-50)/15
    assert z["conscientiousness"] == 0.0
    z2 = z_standardize({"extraversion": 50.0})
    assert z2["openness"] is None


def test_channel_a_mapping_directions():
    """高尽责 → 理性↑回避↓自发↓（先验系数方向的核心断言）。"""
    a = channel_a_scores(_big5(conscientiousness=65.0))
    assert a["confidence"] == "normal"
    assert a["rational"]["score"] == 60.4   # 50 + 0.26*40
    assert a["avoidant"]["score"] == 40.0   # 50 - 0.25*40
    assert a["spontaneous"]["score"] == 41.6  # 50 - 0.21*40
    assert not a["rational"]["fallback"]

    # 高神经质 → 回避↑（El Othman 反转弃用后的合成方向）
    a2 = channel_a_scores(_big5(neuroticism=80.0))
    assert a2["avoidant"]["score"] == 66.0  # 50 + 0.20*2*40


def test_channel_a_confidence_fallback():
    a = channel_a_scores({"extraversion": 50.0, "openness": 50.0})
    assert a["confidence"] == "low"
    assert all(a[d]["fallback"] and a[d]["score"] == 50.0 for d in GDMS_DIMENSIONS)

    a2 = channel_a_scores(_big5(openness=None))
    assert a2["confidence"] == "reduced"
    assert a2["missing_big5"] == ["openness"]
    assert not a2["rational"]["fallback"]


def test_channel_b_signals_and_sample_gate():
    b = channel_b_scores(
        {"help_seeking": 20.0, "procrastination": 8.0},
        message_count=1000,
    )
    assert b["confidence"] == "normal"
    assert b["signals"]["help_seeking"]["score"] == 100.0
    # 求助信号独占 dependent 维聚合
    assert b["dimensions"]["dependent"]["score"] == 100.0
    assert b["dimensions"]["rational"]["score"] is None

    # 样本不足：整体降置信、不产出行为分
    b2 = channel_b_scores({"help_seeking": 20.0}, message_count=10)
    assert b2["confidence"] == "insufficient_sample"
    assert b2["signals"]["help_seeking"]["used"] is False


def test_combine_bounded_adjust_and_memory():
    a = channel_a_scores(_big5())
    b = channel_b_scores(
        {"help_seeking": 20.0, "deliberation": 0.0},
        message_count=1000,
    )
    c = combine_channels(a, b)
    # dependent 基线 50（大五中性）+ 行为分 100 → (100-50)*0.25=12.5 截到 +10
    dep = c["dimensions"]["dependent"]
    assert dep["base"] == 50.0 and dep["adjust"] == 10.0
    assert dep["score"] == 60.0
    assert "信号修正" in dep["adjust_notes"]

    # 记忆行为修正：兑现率 0.9 → dependent 下修 (0.5-0.9)*8 = -3.2
    c2 = combine_channels(a, None, memory_behaviors={"promise_follow_through": 0.9})
    assert c2["dimensions"]["dependent"]["adjust"] == -3.2
    # 改主意率 0.8 → spontaneous 上修 +2.4
    c3 = combine_channels(a, None, memory_behaviors={"plan_supersede_rate": 0.8})
    assert c3["dimensions"]["spontaneous"]["adjust"] == 2.4

    # 空记忆（rag_facts 建设期常态）：不修正、不报错
    c4 = combine_channels(a, None)
    assert c4["dimensions"]["dependent"]["adjust"] == 0.0


def test_compute_decision_style_full_payload():
    out = compute_decision_style(
        _big5(conscientiousness=60.0),
        {"help_seeking": 10.0},
        message_count=2000,
        memory_behaviors={"promise_follow_through": 0.7},
        exploratory={"revoke_rate": 0.01, "promise_follow_through": 0.7},
    )
    assert out["disclaimer"] == "从行为痕迹估计的决策风格倾向，非心理测评"
    assert set(out["channel_a"].keys()) >= set(GDMS_DIMENSIONS)
    assert set(out["combined"]["dimensions"].keys()) == set(GDMS_DIMENSIONS)
    assert out["exploratory"]["revoke_rate"] == 0.01
    # 大五缺席时总装仍可出（通道 B 兜底存在）
    out2 = compute_decision_style({}, None, message_count=0)
    assert out2["channel_a"]["confidence"] == "low"


def test_late_night_is_ratio_not_lexicon():
    """深夜活跃为占比口径（0-1），不走词表——锚点表按占比插值。"""
    b = channel_b_scores({"late_night": 0.15}, message_count=1000)
    assert b["signals"]["late_night"]["score"] == 72.0
    assert b["signals"]["late_night"]["target"] == "spontaneous"
    # 减半权重在维聚合中体现：与其他信号共存时占一半点数
    b2 = channel_b_scores({"late_night": 0.15, "impulsive": 20.0}, message_count=1000)
    # spontaneous = (72*0.5 + 100*0.8) / 1.3
    assert b2["dimensions"]["spontaneous"]["score"] == round((72 * 0.5 + 100 * 0.8) / 1.3, 1)


def test_min_messages_threshold_boundary():
    assert MIN_MESSAGES_FOR_SIGNALS == 200
    b = channel_b_scores({"help_seeking": 20.0}, message_count=200)
    assert b["confidence"] == "normal"
    b2 = channel_b_scores({"help_seeking": 20.0}, message_count=199)
    assert b2["confidence"] == "insufficient_sample"
