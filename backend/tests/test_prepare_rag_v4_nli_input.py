"""Tests for de-identified NLI input export."""

import json
import os
import sqlite3
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.realtime.rag.store import RagStore
from scripts.prepare_rag_v4_nli_input import build_nli_input


def test_nli_export_redacts_sensitive_evidence_and_keeps_contact_scope():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    store = RagStore(conn)
    sensitive_id = store.upsert_fact(
        account_wxid="account-a", conversation_id=1, subject="对方",
        kind="personal_profile", content="手机号 13800138000",
        sensitivity="sensitive", evidence_message_ids=[11], confidence=0.9,
    )
    normal_id = store.upsert_fact(
        account_wxid="account-b", conversation_id=1, subject="对方",
        kind="preference_like", content="喜欢手冲咖啡，联系电话 13800138001",
        evidence_message_ids=[22], confidence=0.9,
    )
    store.insert_retrieval_log(
        account_wxid="account-a", conversation_id=1,
        query_text="她的手机号是多少？", rag_enabled=True, rag_retrieved=True,
        rag_strategy="facts", retrieval_source="fact", fact_ids=[sensitive_id],
        rag_gate_decision="inject", rag_gate_reason="test",
    )
    store.insert_retrieval_log(
        account_wxid="account-b", conversation_id=1,
        query_text="她喜欢什么？", rag_enabled=True, rag_retrieved=True,
        rag_strategy="facts", retrieval_source="fact", fact_ids=[normal_id],
        rag_gate_decision="inject", rag_gate_reason="test",
    )
    payload = build_nli_input(conn, [
        {"id": "sensitive", "query_text": "她的手机号是多少？"},
        {"id": "preference", "query_text": "她喜欢什么？"},
    ])
    sensitive = next(item for item in payload["items"] if item["id"] == "sensitive:fact_path")
    preference = next(item for item in payload["items"] if item["id"] == "preference:fact_path")
    assert payload["deidentified"] is True
    assert sensitive["evidence"][0]["content"] == "[敏感证据已隐藏]"
    assert "13800138000" not in json.dumps(payload, ensure_ascii=False)
    assert "13800138001" not in json.dumps(payload, ensure_ascii=False)
    assert "[PHONE_" in preference["evidence"][0]["content"]


def test_nli_export_has_three_tracks_per_gold_case():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    RagStore(conn)
    payload = build_nli_input(conn, [{"id": "one", "query_text": "没有这条记忆"}])
    assert [item["track"] for item in payload["items"]] == ["no_rag", "document_rag", "fact_path"]
    assert all(item["answer"] == "" and item["nli_label"] == "unknown" for item in payload["items"])
