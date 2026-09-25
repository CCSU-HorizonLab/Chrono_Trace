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
    assert fact_quality_reason("recurring_habit", "我提到：家里还有一大堆家务要做完") == "kind_signal_missing"


def test_short_conversational_fragments_are_quarantined():
    for content in ("对方提到：6666", "对方提到：看一下吧", "对方提到：好好好"):
        assert not is_usable_shadow_fact("personal_profile", content)


def test_prototype_path_requires_minimal_length():
    """P2 收紧：原型路径焦点 <12 字一律拦截（真实库 80% 碎片）。

    LLM 宽松模式不受限——短而自包含的 LLM 事实（"对方对虾过敏"）
    由模型的自包含判断负责。
    """
    assert fact_quality_reason("preference_like", "对方提到：不吃香菜") == "prototype_too_short"
    assert fact_quality_reason("hobby_or_game", "我提到：不想你嘛") == "prototype_too_short"
    assert fact_quality_reason("personal_fact", "对方对虾过敏", require_kind_signal=False) is None
    # 12 字及以上仍走原有规则
    assert fact_quality_reason(
        "food_or_place", "对方提到：早餐一般吃豆浆配油条，很少换花样"
    ) is None


def test_generic_message_cannot_become_hobby_fact_without_object():
    # 短的 generic 活动句被长度门槛拦截（原 hobby_object_missing 场景
    # 在 <12 字区间与 prototype_too_short 重叠）；短而有效的爱好陈述
    # 由 LLM 路径负责（宽松模式放行）
    assert fact_quality_reason("hobby_or_game", "我提到：随便玩了") == "prototype_too_short"
    assert fact_quality_reason(
        "hobby_or_game", "最近在玩杀戮尖塔", require_kind_signal=False
    ) is None
    assert is_usable_shadow_fact("hobby_or_game", "我提到：最近一直在玩杀戮尖塔这个卡组")


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


def test_user_reported_vague_examples_rejected():
    """T4 第三轮：用户实测反馈的代指残留（真实库 active 事实原文）。"""
    # 库内 fact 1058/5298
    assert fact_quality_reason(
        "purchase_or_price", "我提到：这玩意我们有钱了整一台"
    ) == "vague_fragment"
    # 库内 fact 4984/5297
    assert fact_quality_reason("plan_or_appointment", "我提到：我们后天搬") == "vague_fragment"
    # 用户口语原话
    assert fact_quality_reason("purchase_or_price", "有钱了搞一台") == "vague_fragment"
    assert fact_quality_reason("personal_profile", "对方提到：有点吊") == "too_short"
    # 自包含版本（prompt 好例）必须放行
    assert fact_quality_reason(
        "plan_or_appointment", "两人计划后天把宿舍的行李搬到新租的房子", require_kind_signal=False
    ) is None
    assert fact_quality_reason(
        "purchase_or_price", "两人想等有钱了买一台之前讨论过的烘干机", require_kind_signal=False
    ) is None


def test_transaction_details_rejected():
    """T4：一次性金钱往来细节（设计蓝图排除项）拦截，词表在配置。"""
    # 库内 fact 319/5203
    assert fact_quality_reason("food_or_place", "我提到：早餐钱和冰红茶") == "transaction_detail"
    assert fact_quality_reason(
        "purchase_or_price", "对方提到：转你20，奶茶钱"
    ) == "transaction_detail"
    assert fact_quality_reason(
        "promise_or_commitment", "我提到：记得还我钱"
    ) == "transaction_detail"
    # 长句偏好/约定类事实不误伤（>24 字或有明确对象）
    assert fact_quality_reason(
        "preference",
        "对方坚持外出吃饭要AA平摊，认为这样谁都不欠谁，关系更轻松自在",
        require_kind_signal=False,
    ) is None


def test_pricing_question_turns_rejected():
    """T11 第四轮："多少/几块"结尾是询价不是事实（真实库"早餐多少"x2）。"""
    assert fact_quality_reason("food_or_place", "我提到：早餐多少") == "question_turn"
    assert fact_quality_reason("purchase_or_price", "对方提到：这个几块") == "question_turn"
    # 陈述句不受影响
    assert fact_quality_reason(
        "food_or_place", "对方提到：早餐一般吃豆浆配油条，很少换花样"
    ) is None


def test_purchase_pronoun_ending_rejected():
    """T11 第四轮：购买类"……的"结尾=代指，对象已丢失（用户标注"直接买80的"等）。"""
    assert fact_quality_reason(
        "purchase_or_price", "我提到：暑假打工赚钱后我到时候直接买80的"
    ) == "object_missing"
    assert fact_quality_reason(
        "purchase_or_price", "对方提到：钱包丢了所以最近只想买便宜点的"
    ) == "object_missing"
    # 写明具体物品的购买事实放行
    assert fact_quality_reason(
        "purchase_or_price", "对方提到：想买那款联动的限定游戏皮肤"
    ) is None


def test_weak_preference_fragments_rejected():
    """T11 第四轮："没那么想要"类弱化残句（真实库 #280/#5195 active）。"""
    assert fact_quality_reason("preference_like", "对方提到：没那么想要") == "vague_fragment"
    assert fact_quality_reason("preference_like", "对方提到：没那么想吃") == "vague_fragment"
    # 有对象的弱化表达放行
    assert fact_quality_reason(
        "preference_like", "对方提到：没那么想要那款机械键盘了，先不买"
    ) is None
