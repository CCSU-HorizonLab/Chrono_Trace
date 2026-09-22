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
