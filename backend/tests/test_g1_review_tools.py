"""G0 审核工作流测试:审核包生成与作答回灌。"""

import os
import sys


sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from backend.scripts.g1_apply_review import apply_answers
from backend.scripts.g1_build_review_packet import build_packet, render_output


def _fixture_samples():
    return {
        "meta": {"active_model": {"model_id": "test-model"}},
        "samples": [
            {
                "sample_id": "s1",
                "dimension": "task_routing",
                "source": "authored",
                "input": [{"role": "user", "content": "我想约她打游戏"}],
                "account_wxid": "wxid_a",
                "conversation_id": None,
                "display_name": "测试",
                "expected": {
                    "task": "invitation_planning",
                    "output": "answer_with_speeches",
                    "knowledge_needs": ["facts"],
                    "must_use": ["共同游戏事实"],
                    "forbidden": [],
                    "safety": ["话术可直接发送"],
                    "annotation_basis": "施工单目标样例",
                },
                "expected_annotation": "ai_first_pass_pending_human",
            },
            {
                "sample_id": "s2",
                "dimension": "task_routing",
                "source": "authored",
                "input": [{"role": "user", "content": "你好"}],
                "account_wxid": "wxid_a",
                "conversation_id": None,
                "display_name": "测试",
                "expected": {
                    "task": "general_qa",
                    "output": "direct_answer",
                    "knowledge_needs": ["facts"],
                    "annotation_basis": "安全直答",
                },
                "expected_annotation": "ai_first_pass_pending_human",
            },
        ],
    }


def _fixture_results():
    return {
        "runs": [
            {
                "live": True,
                "results": [
                    {
                        "sample_id": "s1",
                        "chain": "g1",
                        "routing": {"task": "invitation_planning", "output": "answer_with_speeches"},
                        "output": {"reply": "顺着约", "summary": "轻邀约", "speeches": ["今晚打两把?"]},
                    },
                    {
                        "sample_id": "s1",
                        "chain": "legacy",
                        "routing": {"task": "general_qa", "output": "direct_answer"},
                        "output": {"reply": "先别追问", "summary": "[PURE_CHAT]", "speeches": []},
                    },
                    {
                        "sample_id": "s1",
                        "chain": "no_rag",
                        "routing": {"task": "invitation_planning", "output": "answer_with_speeches"},
                        "output": {"summary": "通用邀约", "speeches": ["一起玩?"]},
                    },
                ],
            }
        ]
    }


def test_build_packet_renders_three_chains_and_template(tmp_path):
    samples_path = tmp_path / "samples.json"
    results_path = tmp_path / "results.json"
    import json

    samples_path.write_text(json.dumps(_fixture_samples(), ensure_ascii=False), encoding="utf-8")
    results_path.write_text(json.dumps(_fixture_results(), ensure_ascii=False), encoding="utf-8")

    packet, template = build_packet(samples_path, results_path, db_path=str(tmp_path / "nonexistent.db"))
    assert "## s1" in packet and "## s2" in packet
    assert "`no_rag`" in packet and "`legacy`" in packet and "`g1`" in packet
    assert "我想约她打游戏" in packet
    assert "今晚打两把?" in packet  # 实际输出全文
    assert "[PURE_CHAT] → 无建议卡片" in packet
    assert "无会话范围" in packet  # conversation_id None 的降级说明
    assert {a["sample_id"] for a in template["answers"]} == {"s1", "s2"}
    assert all(a["verdict"] is None for a in template["answers"])


def test_render_output_handles_missing_and_error():
    assert "(无结果)" in render_output(None)
    assert "(失败" in render_output({"error": "ValueError: boom"})
    assert "(无输出)" in render_output({"output": {}})


def test_apply_answers_confirm_override_and_skip():
    payload = _fixture_samples()
    answers = {
        "answers": [
            {"sample_id": "s1", "verdict": "agree", "issues": ["话术质量尚可"], "severity": "minor"},
            {
                "sample_id": "s2",
                "verdict": "override",
                "expected_task": "memory_qa",
                "expected_output": "direct_answer",
                "knowledge_needs": ["facts"],
                "issues": ["应视为记忆问答"],
                "severity": "major",
            },
        ]
    }
    stats = apply_answers(payload, answers, reviewer="test-agent")
    assert stats == {"confirmed": 1, "overridden": 1, "skipped": 0, "missing": 0}

    s1 = payload["samples"][0]
    assert s1["expected_annotation"] == "agent_reviewed_confirmed"
    assert s1["review"]["reviewer"] == "test-agent"

    s2 = payload["samples"][1]
    assert s2["expected_annotation"] == "agent_reviewed_overridden"
    assert s2["expected"]["task"] == "memory_qa"
    assert s2["expected_superseded"]["task"] == "general_qa"  # 原判定留档

    meta = payload["meta"]["expected_annotation"]
    assert meta["confirmed"] == 1 and meta["overridden"] == 1


def test_apply_answers_skips_invalid_verdict_and_bad_output():
    payload = _fixture_samples()
    answers = {
        "answers": [
            {"sample_id": "s1", "verdict": "maybe"},
            {"sample_id": "s2", "verdict": "override", "expected_task": "x", "expected_output": "不合法"},
        ]
    }
    stats = apply_answers(payload, answers, reviewer="t")
    assert stats["skipped"] == 2
    assert payload["samples"][0]["expected_annotation"] == "ai_first_pass_pending_human"
