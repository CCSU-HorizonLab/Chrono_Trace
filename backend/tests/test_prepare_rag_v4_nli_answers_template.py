import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from scripts.prepare_rag_v4_nli_answers_template import build_template


def test_answer_template_matches_prepared_keys_without_copying_content(tmp_path):
    source = tmp_path / "input.json"
    source.write_text(json.dumps({"items": [{
        "id": "q1:fact_path", "track": "fact_path",
        "query_text": "脱敏问题", "evidence": ["脱敏证据"],
        "judge_version": "judge-v1", "prompt_version": "prompt-v1",
    }]}, ensure_ascii=False), encoding="utf-8")
    payload = build_template(source)
    assert payload["items"] == [{
        "id": "q1:fact_path", "track": "fact_path", "answer": "",
        "evidence": [], "nli_label": "unknown",
        "judge_version": "judge-v1", "prompt_version": "prompt-v1",
    }]
    rendered = json.dumps(payload, ensure_ascii=False)
    assert "脱敏问题" not in rendered
    assert "脱敏证据" not in rendered
