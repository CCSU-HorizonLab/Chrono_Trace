import sqlite3
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

from app.services.realtime.rag_fact_extractor import FactExtractionError, StructuredFactExtractor
from app.services.realtime.rag_config import apply_rag_defaults
from app.services.realtime.rag_retriever import RagRetriever
from app.services.realtime.rag_store import RagStore


def test_structured_fact_extractor_validates_json_and_evidence():
    extractor = StructuredFactExtractor(
        lambda _: '{"facts":[{"subject":"对方","kind":"preference","content":"喜欢咖啡","confidence":0.9,"evidence_message_ids":[3]}]}'
    )
    facts = extractor.extract("prompt")
    assert facts[0]["content"] == "喜欢咖啡"
    assert facts[0]["evidence_message_ids"] == [3]


def test_structured_fact_extractor_quarantines_invalid_payload():
    extractor = StructuredFactExtractor(lambda _: "not-json")
    with pytest.raises(FactExtractionError):
        extractor.extract("prompt")


def test_rag_store_is_contact_scoped_for_shadow_facts():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    store = RagStore(conn)
    first = store.upsert_fact(
        account_wxid="account-a", conversation_id=1, subject="对方",
        kind="preference", content="喜欢咖啡", confidence=0.8,
        evidence_message_ids=[10],
    )
    second = store.upsert_fact(
        account_wxid="account-a", conversation_id=2, subject="对方",
        kind="preference", content="喜欢咖啡", confidence=0.8,
        evidence_message_ids=[20],
    )
    assert first != second
    assert conn.execute("select count(*) from rag_facts").fetchone()[0] == 2


def test_query_scope_defaults_to_latest_turn(monkeypatch):
    settings = apply_rag_defaults({})
    monkeypatch.setattr(
        "app.services.realtime.rag_retriever.load_rag_settings", lambda: settings
    )
    query = RagRetriever().build_query(
        {"recent_messages": [{"content": "旧话题"}, {"content": "最新输入"}]},
        "manual_request",
        "maintain",
    )
    assert "最新输入" in query
    assert "旧话题" not in query


def test_fact_read_is_opt_in_and_returns_contact_scoped_fact(monkeypatch):
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    store = RagStore(conn)
    store.upsert_status("account-a", 1, status="ready", document_count=0, vector_count=0)
    store.upsert_fact(
        account_wxid="account-a", conversation_id=1, subject="对方",
        kind="preference", content="对方喜欢咖啡", confidence=0.9,
        evidence_message_ids=[3],
    )
    monkeypatch.setattr(
        "app.services.realtime.rag_retriever.load_rag_settings",
        lambda: {
            "rag_fact_read_enabled": True,
            "rag_embedding_model": "test",
            "rag_embedding_dim": 384,
        },
    )
    result = RagRetriever(store=store).retrieve(
        account_wxid="account-a", conversation_id=1, query="喜欢咖啡"
    )
    assert result["strategy"] == "facts"
    assert result["items"][0]["doc_type"] == "fact_memory"
