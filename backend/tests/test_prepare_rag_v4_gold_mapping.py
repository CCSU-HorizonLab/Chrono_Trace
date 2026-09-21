"""Privacy and ranking tests for gold mapping candidate export."""

import os
import sqlite3
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.realtime.rag_store import RagStore
from scripts.prepare_rag_v4_gold_mapping import build_candidates


def test_candidate_export_ranks_lexical_match_and_hides_sensitive_content():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    store = RagStore(conn)
    coffee_id = store.upsert_fact(
        account_wxid="account-a", conversation_id=1, subject="对方", kind="preference",
        content="对方喜欢手冲咖啡", confidence=0.9, evidence_message_ids=[11],
    )
    store.upsert_fact(
        account_wxid="account-a", conversation_id=1, subject="对方", kind="personal_fact",
        content="身份证号 123456", sensitivity="sensitive", confidence=0.9, evidence_message_ids=[12],
    )
    payload = build_candidates(
        conn,
        [
            {"id": "coffee", "query_text": "她喜欢什么咖啡？", "gold_fact_ids": ["fact_preference_coffee"]},
            {"id": "id", "query_text": "她的身份证号是多少？", "gold_fact_ids": ["fact_sensitive_id"]},
        ],
        account_wxid="account-a",
        conversation_id=1,
    )
    assert payload["facts_considered"] == 2
    assert payload["cases"][0]["candidates"][0]["fact_id"] == coffee_id
    sensitive = payload["cases"][1]["candidates"][0]
    assert sensitive["sensitivity"] == "sensitive"
    assert sensitive["content_preview"] == "[敏感事实内容已隐藏]"
    assert "123456" not in str(payload)
