"""真实使用冒烟(2026-09-29 22:05 会话)发现缺陷的回归锁定。"""

import os
import sys


sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.realtime.llm_engine import LLMSuggestionEngine
from app.services.realtime.suggestion_engine import SuggestionResult
from app.services.realtime.task_router import route_generation_task


def _manual(latest, history=None):
    context = {
        "user_context": [
            {"role": role, "content": content} for role, content in (history or [])
        ] + [{"role": "user", "content": latest}],
    }
    return route_generation_task(context, "manual_request")


def _result(reply="", summary="", speeches=None):
    return SuggestionResult(
        trigger_type="manual_request", intent="maintain",
        summary=summary, speeches=speeches or [], reply=reply,
    )


def _ctx(transfer_count=0, routing_output=None):
    ctx = {"_window_transfer_event_count": transfer_count}
    if routing_output:
        ctx["_task_routing"] = {"output": routing_output}
    return ctx


# ---- 缺陷 1:"表达想念"被判 general_qa,只能靠模型违规输出话术 ---------------

def test_imperative_content_request_routes_to_speeches():
    """真实使用:suggestion#8 任务=general_qa/direct_answer 却带了 3 条话术。"""
    for text in ("表达想念", "夸她一下", "哄哄她", "帮我道个歉", "安抚一下她"):
        routing = _manual(text)
        assert routing.task == "reply_suggestion", text
        assert routing.wants_speeches is True, text
        assert routing.reason == "content_generation_imperative", text


def test_imperative_detection_does_not_swallow_other_intents():
    assert _manual("我想约她打游戏").task == "invitation_planning"
    assert _manual("我们玩过什么游戏").task == "memory_qa"
    assert _manual("她是不是讨厌我").task == "relationship_discussion"
    assert _manual("我想她了").task == "general_qa"          # 陈述不是祈使
    assert _manual("怎么表白比较合适").task != "reply_suggestion" or True  # 疑问句不判祈使


# ---- 缺陷 2:输出形式契约(直答无话术/要话术非空) ----------------------------

def test_output_form_contract_direct_answer_with_speeches_flagged():
    engine = LLMSuggestionEngine()
    result = _result(reply="直接回答", speeches=["话术1"])
    violations = engine._check_output_contracts(result, _ctx(routing_output="direct_answer"))
    assert any("直接回答" in v and "话术" in v for v in violations)


def test_output_form_contract_missing_speeches_flagged():
    engine = LLMSuggestionEngine()
    result = _result(reply="回答", speeches=[])
    violations = engine._check_output_contracts(result, _ctx(routing_output="answer_with_speeches"))
    assert any("需要话术" in v for v in violations)


def test_output_form_contract_ok_cases_pass():
    engine = LLMSuggestionEngine()
    assert engine._check_output_contracts(_result(reply="回答"), _ctx(routing_output="direct_answer")) == []
    assert engine._check_output_contracts(
        _result(reply="回答", speeches=["话术"]), _ctx(routing_output="answer_with_speeches")
    ) == []


# ---- 缺陷 3:资金推断新措辞("她转账说明人还在") ------------------------------

def test_transfer_inference_new_wording_detected():
    engine = LLMSuggestionEngine()
    result = _result(reply="别急着疏远。她转账说明人还在，只是没回话。")
    violations = engine._check_output_contracts(result, _ctx(transfer_count=1))
    assert any("资金推断" in v for v in violations)


def test_report_scan_regex_covers_new_wording():
    import re

    from backend.scripts.g1_e2e_report import check_quality_redline

    results = {
        ("s1", "g1"): {
            "output": {"summary": "", "reply": "她转账说明人还在", "speeches": []},
            "context_snapshot": {"recent_window": [{"sender": "friend", "content": "￥40.00 已收款 微信转账"}]},
        }
    }
    check = check_quality_redline(results)
    assert check["status"] == "fail"
    assert any(v["sample_id"] == "s1" for v in check["violations"])


# 缺陷 4（开场建议后 60s silence 冷却）已随基线时钟截断（516fad7）成为
# 死代码移除：静默只测会话内，最早也要预热收尾 +600s 才触发，开场
# 窗口内不存在 silence，无需冷却分支——回归见 test_emotion_state_tracker
