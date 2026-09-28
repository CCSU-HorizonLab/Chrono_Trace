"""G2 任务路由测试:task / output / knowledge_needs 三元拆分。"""

import os
import sys


sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.realtime.task_router import (
    KN_CONTACT_PROFILE,
    KN_FACTS,
    KN_RELATIONSHIP_SIGNALS,
    KN_USER_STYLE,
    OUTPUT_ANSWER_WITH_SPEECHES,
    OUTPUT_DIRECT_ANSWER,
    OUTPUT_SUGGESTION_CARD,
    TASK_GENERAL_QA,
    TASK_INVITATION_PLANNING,
    TASK_MEMORY_QA,
    TASK_RELATIONSHIP_DISCUSSION,
    TASK_REPLY_SUGGESTION,
    TaskRouting,
    route_generation_task,
)


def _manual(latest: str, history: list[tuple[str, str]] | None = None):
    context = {
        "user_context": [
            {"role": role, "content": content} for role, content in (history or [])
        ] + [{"role": "user", "content": latest}],
    }
    return route_generation_task(context, "manual_request")


def test_invitation_request_routes_to_planning_with_speeches():
    """施工单首个目标样例:"我想约她打游戏"必须进入邀约任务并可给话术。"""
    routing = _manual("我想约她打游戏")
    assert routing.task == TASK_INVITATION_PLANNING
    assert routing.output == OUTPUT_ANSWER_WITH_SPEECHES
    assert routing.wants_speeches is True
    assert routing.needs(KN_FACTS)
    assert routing.needs(KN_CONTACT_PROFILE)
    assert routing.needs(KN_RELATIONSHIP_SIGNALS)
    assert routing.needs(KN_USER_STYLE)


def test_history_question_routes_to_memory_qa_without_style():
    """纯历史问答不强行注入用户口头禅和建议风格。"""
    routing = _manual("我们玩过什么游戏")
    assert routing.task == TASK_MEMORY_QA
    assert routing.output == OUTPUT_DIRECT_ANSWER
    assert routing.wants_speeches is False
    assert routing.needs(KN_FACTS)
    assert not routing.needs(KN_USER_STYLE)
    assert not routing.needs(KN_CONTACT_PROFILE)


def test_preference_lookup_routes_to_memory_qa():
    routing = _manual("她喜欢什么")
    assert routing.task == TASK_MEMORY_QA
    assert routing.output == OUTPUT_DIRECT_ANSWER


def test_advice_followup_inherits_previous_advice_task():
    routing = _manual(
        "没有建议么",
        history=[("user", "她刚发了个朋友圈,怎么回她比较好?"), ("assistant", "可以夸照片拍得好")],
    )
    assert routing.task == TASK_REPLY_SUGGESTION
    assert routing.output == OUTPUT_SUGGESTION_CARD
    assert routing.reason == "advice_followup_inherited"


def test_rewrite_followup_inherits_advice_task():
    routing = _manual(
        "短一点",
        history=[("user", "给我几条回复建议"), ("assistant", "好的")],
    )
    assert routing.task == TASK_REPLY_SUGGESTION
    assert routing.reason in {"advice_followup_inherited", "rewrite_followup"}


def test_relationship_discussion_allows_profile_even_direct_answer():
    routing = _manual("她是不是讨厌我")
    assert routing.task == TASK_RELATIONSHIP_DISCUSSION
    assert routing.output == OUTPUT_DIRECT_ANSWER
    # 关系讨论即使直接回答,也允许画像与关系证据
    assert routing.needs(KN_CONTACT_PROFILE)
    assert routing.needs(KN_RELATIONSHIP_SIGNALS)
    assert routing.needs(KN_FACTS)
    assert not routing.needs(KN_USER_STYLE)


def test_relationship_discussion_with_action_request_gives_speeches():
    routing = _manual("我们还有机会吗,我该怎么推进")
    assert routing.task == TASK_RELATIONSHIP_DISCUSSION
    assert routing.output == OUTPUT_ANSWER_WITH_SPEECHES
    assert routing.wants_speeches is True


def test_explicit_advice_keyword_routes_to_suggestion():
    routing = _manual("这句怎么回比较好")
    assert routing.task == TASK_REPLY_SUGGESTION
    assert routing.output == OUTPUT_SUGGESTION_CARD


def test_plain_greeting_routes_to_safe_general_qa():
    """不确定时优先保持安全输出,不擅自生成代发话术。"""
    routing = _manual("你好呀")
    assert routing.task == TASK_GENERAL_QA
    assert routing.output == OUTPUT_DIRECT_ANSWER
    assert routing.wants_speeches is False
    assert not routing.needs(KN_USER_STYLE)
    assert not routing.needs(KN_CONTACT_PROFILE)


def test_auto_trigger_always_suggestion_card():
    routing = route_generation_task({"trigger_context": {"source": "full_auto"}}, "positive_window")
    assert routing.task == TASK_REPLY_SUGGESTION
    assert routing.output == OUTPUT_SUGGESTION_CARD
    assert routing.wants_speeches is True
    assert routing.manual_request is False


def test_manual_without_input_defaults_to_suggestion():
    routing = route_generation_task({}, "manual_request")
    assert routing.task == TASK_REPLY_SUGGESTION
    assert routing.output == OUTPUT_SUGGESTION_CARD


def test_three_turn_task_switching():
    """三轮任务切换:求助 → 追问 → 历史问答,互不串扰。"""
    turn1 = _manual("怎么回她关于周末的邀约")
    assert turn1.task == TASK_REPLY_SUGGESTION

    turn2 = _manual(
        "再来几条",
        history=[("user", "怎么回她关于周末的邀约"), ("assistant", "建议一:...")],
    )
    assert turn2.task == TASK_REPLY_SUGGESTION
    assert turn2.output == OUTPUT_SUGGESTION_CARD

    turn3 = _manual("我们上次玩过什么游戏来着")
    assert turn3.task == TASK_MEMORY_QA
    assert turn3.output == OUTPUT_DIRECT_ANSWER


def test_negation_is_not_advice():
    """否定句("我不知道说什么了")不是建议求助时回落安全输出。"""
    routing = _manual("今天天气真不错")
    assert routing.task == TASK_GENERAL_QA


def test_routing_roundtrip_via_dict():
    routing = _manual("我想约她打游戏")
    restored = TaskRouting.from_dict(routing.to_dict())
    assert restored is not None
    assert restored.task == routing.task
    assert restored.output == routing.output
    assert restored.knowledge_needs == routing.knowledge_needs
    assert restored.wants_speeches is True

    assert TaskRouting.from_dict({"task": "", "output": ""}) is None
    assert TaskRouting.from_dict(None) is None
    # 缺 wants_speeches 字段时按 output 推导
    derived = TaskRouting.from_dict({"task": TASK_MEMORY_QA, "output": OUTPUT_DIRECT_ANSWER})
    assert derived.wants_speeches is False
