import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.realtime.rag_fact_quality import (
    fact_quality_reason,
    is_usable_shadow_fact,
)


def test_durable_fact_requires_kind_aligned_signal():
    assert is_usable_shadow_fact(
        "recurring_habit",
        "我提到：我每次压力大的时候都会去江边散步",
    )
    assert fact_quality_reason("recurring_habit", "我提到：家里还要做家务") == "kind_signal_missing"


def test_short_conversational_fragments_are_quarantined():
    for content in ("对方提到：6666", "对方提到：看一下吧", "对方提到：好好好"):
        assert not is_usable_shadow_fact("personal_profile", content)


def test_generic_message_cannot_become_hobby_fact_without_object():
    assert fact_quality_reason("hobby_or_game", "我提到：随便玩了") == "hobby_object_missing"
    assert is_usable_shadow_fact("hobby_or_game", "我提到：最近在玩杀戮尖塔")


def test_sensitive_shadow_fact_is_quarantined():
    assert fact_quality_reason("personal_profile", "对方提到：密码全是这样的") == "sensitive_quarantine"


def test_system_messages_are_rejected():
    assert fact_quality_reason(
        "personal_profile", "对方提到：我通过了你的朋友验证请求，现在我们可以开始聊天了"
    ) == "system_message"
    assert fact_quality_reason("plan_or_appointment", "对方提到：收到了红包") == "system_message"
    # 正常事实不受系统消息词表影响
    assert fact_quality_reason(
        "personal_profile", "对方提到：她在深圳一家中小公司做后端开发"
    ) is None


def test_corrupted_text_detected():
    assert fact_quality_reason(
        "hobby_or_game", "我提到：(\xb5/\xfd \xd4U\x06\x00\xd2\xcb-1pi<X"
    ) == "corrupted_text"
    # 偶发西文字符不误伤
    assert fact_quality_reason(
        "preference_like", "对方提到：我喜欢喝café，周末常去"
    ) is None


def test_vague_fragments_rejected():
    assert fact_quality_reason("preference", "对方提到：就买一下下嘛") == "vague_fragment"
    assert fact_quality_reason("plan_or_appointment", "你什么时候跟我提再说吧") == "vague_fragment"
    # 自包含陈述不受影响（LLM 事实走宽松模式）
    assert fact_quality_reason(
        "preference", "对方撒娇要求购买之前讨论过的游戏皮肤", require_kind_signal=False
    ) is None
    assert fact_quality_reason("plan_or_appointment", "我们约了周五在五道口那家店见面") is None
