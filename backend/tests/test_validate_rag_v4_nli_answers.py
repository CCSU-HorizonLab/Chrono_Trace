import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from scripts.validate_rag_v4_nli_answers import validate_answers


def _write(path, payload):
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def test_nli_answers_require_every_prepared_track(tmp_path):
    prepared = tmp_path / "input.json"
    answers = tmp_path / "answers.json"
    _write(prepared, {"items": [
        {"id": "q1", "track": "fact_path"},
        {"id": "q1", "track": "document_rag"},
    ]})
    _write(answers, {"items": [{
        "id": "q1", "track": "fact_path", "answer": "答复",
        "evidence": ["事实"], "nli_label": "entailed",
    }]})
    result = validate_answers(prepared, answers)
    assert result["status"] == "invalid"
    assert {item["reason"] for item in result["errors"]} == {"missing_answer"}


def test_nli_answers_reject_duplicates_unknown_and_bad_label(tmp_path):
    prepared = tmp_path / "input.json"
    answers = tmp_path / "answers.json"
    _write(prepared, {"items": [{"id": "q1", "track": "fact_path"}]})
    _write(answers, {"items": [
        {"id": "q1", "track": "fact_path", "answer": "a", "evidence": [], "nli_label": "entailed"},
        {"id": "q1", "track": "fact_path", "answer": "a", "evidence": [], "nli_label": "nope"},
        {"id": "q2", "track": "fact_path", "answer": "a", "evidence": [], "nli_label": "unknown"},
    ]})
    result = validate_answers(prepared, answers)
    reasons = {item["reason"] for item in result["errors"]}
    assert {"duplicate_answer", "invalid_label", "unknown_input"} <= reasons


def test_complete_nli_answers_are_ready(tmp_path):
    prepared = tmp_path / "input.json"
    answers = tmp_path / "answers.json"
    _write(prepared, {"items": [{"id": "q1", "track": "fact_path"}]})
    _write(answers, {"items": [{
        "id": "q1", "track": "fact_path", "answer": "不确定",
        "evidence": [], "nli_label": "unknown",
    }]})
    result = validate_answers(prepared, answers)
    assert result["status"] == "ready"
    assert result["label_counts"]["unknown"] == 1
