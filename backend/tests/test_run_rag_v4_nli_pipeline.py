import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from scripts.run_rag_v4_nli_pipeline import run_stage


def test_answer_stage_sends_only_deidentified_query_and_evidence():
    seen = []

    def call(messages):
        seen.append(messages)
        return '{"answer":"证据支持的回答"}'

    payload = {"secret": "not-forwarded", "items": [{
        "id": "q1:fact_path", "track": "fact_path", "query": "脱敏问题",
        "evidence": ["脱敏证据"], "account_wxid": "must-not-send", "answer": "",
    }]}
    result = run_stage(payload, stage="answer", llm_call=call)
    assert result["items"][0]["answer"] == "证据支持的回答"
    rendered = json.dumps(seen, ensure_ascii=False)
    assert "脱敏问题" in rendered and "脱敏证据" in rendered
    assert "must-not-send" not in rendered and "not-forwarded" not in rendered


def test_judge_stage_keeps_invalid_or_failed_parse_unknown():
    payload = {"items": [{
        "id": "q1:fact_path", "track": "fact_path", "query": "问题",
        "answer": "回答", "evidence": ["证据"], "nli_label": "unknown",
    }]}
    result = run_stage(payload, stage="judge", llm_call=lambda _: "not-json")
    assert result["items"][0]["nli_label"] == "unknown"
    assert result["last_stage_processed"] == 1


def test_judge_stage_accepts_fenced_valid_label_and_resumes():
    calls = []
    payload = {"items": [
        {"id": "q1", "query": "q", "answer": "a", "evidence": ["e"], "nli_label": "unknown"},
        {"id": "q2", "query": "q", "answer": "a", "evidence": ["e"], "nli_label": "entailed"},
    ]}
    result = run_stage(
        payload, stage="judge",
        llm_call=lambda messages: calls.append(messages) or '```json\n{"label":"contradicted","reason":"冲突"}\n```',
    )
    assert result["items"][0]["nli_label"] == "contradicted"
    assert result["items"][0]["judge_reason"] == "冲突"
    assert result["items"][1]["nli_label"] == "entailed"
    assert len(calls) == 1


def test_batch_answer_stage_maps_results_by_id_and_honors_limit():
    calls = []
    payload = {"items": [
        {"id": f"q{index}", "query": "q", "evidence": ["e"], "answer": ""}
        for index in range(3)
    ]}

    def call(messages):
        calls.append(messages)
        return '{"items":[{"id":"q1","answer":"a1"},{"id":"q0","answer":"a0"}]}'

    result = run_stage(payload, stage="answer", llm_call=call, limit=2, batch_size=8)
    assert [item["answer"] for item in result["items"]] == ["a0", "a1", ""]
    assert result["last_stage_processed"] == 2
    assert len(calls) == 1


def test_batch_stage_retries_only_missing_items_individually():
    calls = []
    payload = {"items": [
        {"id": "q0", "query": "q", "evidence": ["e"], "answer": ""},
        {"id": "q1", "query": "q", "evidence": ["e"], "answer": ""},
    ]}

    def call(messages):
        calls.append(messages)
        if len(calls) == 1:
            return '{"items":[{"id":"q0","answer":"a0"}]}'
        return '{"answer":"a1"}'

    result = run_stage(payload, stage="answer", llm_call=call, batch_size=8)
    assert [item["answer"] for item in result["items"]] == ["a0", "a1"]
    assert len(calls) == 2


def test_mixed_output_model_json_is_extracted_from_surrounding_text():
    payload = {"items": [{"id": "q", "query": "q", "evidence": ["e"], "answer": ""}]}
    result = run_stage(
        payload, stage="answer",
        llm_call=lambda _: '思考完成。\n{"response":"最终回答"}\n以上。',
    )
    assert result["items"][0]["answer"] == "最终回答"


def test_answer_failure_can_be_recorded_as_safe_degradation():
    payload = {"items": [{"id": "q", "query": "q", "evidence": ["e"], "answer": ""}]}
    result = run_stage(
        payload, stage="answer", llm_call=lambda _: "", safe_fallback=True,
    )
    item = result["items"][0]
    assert item["answer"] == "证据不足，无法根据当前证据回答。"
    assert item["answer_status"] == "degraded_model_output"
    assert item["nli_label"] == "unknown"
