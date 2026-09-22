import json
import os
import sqlite3
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.realtime.rag_store import RagStore
from scripts.prepare_rag_v4_runtime_gold import generate_questions, select_facts


def test_runtime_gold_selects_only_normal_evidenced_facts_and_binds_numeric_id():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE messages (id INTEGER PRIMARY KEY, content TEXT)")
    conn.execute("INSERT INTO messages VALUES (1, '她喜欢拿铁')")
    store = RagStore(conn)
    good = store.upsert_fact(account_wxid="a", conversation_id=1, subject="对方", kind="preference", content="喜欢拿铁", confidence=0.9, evidence_message_ids=[1])
    store.upsert_fact(account_wxid="a", conversation_id=1, subject="对方", kind="private", content="手机号", confidence=1.0, sensitivity="sensitive", evidence_message_ids=[1])
    facts = select_facts(conn, account_wxid="a", conversation_id=1, count=10)
    assert [item["fact_id"] for item in facts] == [good]

    def call(messages):
        assert "手机号" not in json.dumps(messages, ensure_ascii=False)
        return json.dumps({"items": [{"fact_id": good, "query": "她喜欢喝什么？"}]}, ensure_ascii=False)

    items = generate_questions(facts, call)
    assert items[0]["gold_fact_ids"] == [good]
    assert items[0]["query_text"] == "她喜欢喝什么？"


def test_runtime_gold_extracts_wrapped_json_and_retries_missing_batch_items():
    facts = [
        {"fact_id": 1, "kind": "preference", "subject": "对方", "redacted_fact": "喜欢拿铁"},
        {"fact_id": 2, "kind": "plan", "subject": "对方", "redacted_fact": "周末看展"},
    ]
    calls = []

    def call(messages):
        calls.append(messages)
        if len(calls) == 1:
            return '说明\n{"items":[{"fact_id":1,"query":"喜欢喝什么？"}]}\n结束'
        return '{"query":"周末有什么安排？"}'

    items = generate_questions(facts, call, batch_size=8)
    assert [item["gold_fact_ids"] for item in items] == [[1], [2]]
    assert len(calls) == 2
