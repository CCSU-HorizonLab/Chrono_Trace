import json
import sqlite3
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

from app.services.realtime.rag_fact_extractor import FactExtractionError, StructuredFactExtractor
from app.services.realtime.rag_config import apply_rag_defaults
from app.services.realtime.rag_embedding import RagEmbeddingService
from app.services.realtime.rag_retriever import RagRetriever
from app.services.realtime.rag_store import RagStore
from app.services.realtime.rag_context_builder import RagContextBuilder
from app.services.realtime.llm_engine import LLMSuggestionEngine
from app.services.realtime.privacy_redactor import PrivacyRedactor


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


def test_fact_memory_flows_into_prompt_and_retrieval_log(monkeypatch):
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    store = RagStore(conn)
    store.upsert_status("account-a", 1, status="ready", document_count=0, vector_count=0)
    store.upsert_fact(
        account_wxid="account-a", conversation_id=1, subject="对方",
        kind="preference", content="对方喜欢手冲咖啡", confidence=0.95,
        evidence_message_ids=[42],
    )
    settings = {
        "rag_enabled": True,
        "rag_fact_read_enabled": True,
        "rag_remote_context_redaction": True,
        "rag_allow_remote_embedding": False,
        "rag_embedding_model": "test",
        "rag_embedding_dim": 768,
        "rag_privacy_mode": "balanced",
        "rag_query_scope": "latest_turn",
    }
    monkeypatch.setattr(
        "app.services.realtime.rag_context_builder.load_rag_settings", lambda: settings
    )
    monkeypatch.setattr(
        "app.services.realtime.rag_retriever.load_rag_settings", lambda: settings
    )
    context = {
        "account_wxid": "account-a",
        "conversation_id": 1,
        "recent_messages": [],
        "user_context": "记得她喜欢什么咖啡吗",
        "memory_intent": {
            "should_retrieve": True,
            "mode": "memory_request",
            "confidence": 0.95,
            "query": "她喜欢什么咖啡",
            "reason": "test",
        },
    }
    class ReadyIndexer:
        def ensure_contact_index(self, **kwargs):
            return {"status": "ready", "document_count": 0, "vector_count": 0}

    RagContextBuilder(store=store, indexer=ReadyIndexer()).enrich_context(
        context,
        trigger_type="manual_request",
        intent="maintain",
        model_config={"provider": "local", "api_base_url": "http://127.0.0.1"},
    )
    retrieval = context["retrieval_context"]
    assert retrieval["strategy"] == "facts"
    assert retrieval["items"][0]["evidence_message_ids"] == [42]
    log = conn.execute("SELECT * FROM rag_retrieval_logs").fetchone()
    assert json.loads(log["fact_ids_json"]) == [retrieval["items"][0]["document_id"]]
    assert json.loads(log["evidence_ids_json"]) == [42]

    prompt = LLMSuggestionEngine()._build_prompt("manual_request", "maintain", context)
    assert "对方喜欢手冲咖啡" in prompt
    assert "证据消息：42" in prompt


def test_fact_lifecycle_supersedes_and_allows_user_disable():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    store = RagStore(conn)
    old_id = store.upsert_fact(
        account_wxid="account-a", conversation_id=1, subject="对方",
        kind="preference", content="喜欢奶茶", confidence=0.7,
    )
    new_id = store.upsert_fact(
        account_wxid="account-a", conversation_id=1, subject="对方",
        kind="preference", content="喜欢咖啡", confidence=0.9,
    )
    store.supersede_fact(old_id, new_id)
    assert [item["id"] for item in store.list_facts("account-a", 1)] == [new_id]
    store.set_fact_enabled(new_id, False)
    assert store.list_facts("account-a", 1) == []


def test_rag_schema_is_idempotent_and_keeps_contact_keys():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    first = RagStore(conn)
    second = RagStore(conn)
    tables = {
        row[0]
        for row in conn.execute(
            "select name from sqlite_master where type='table' and name like 'rag_%'"
        ).fetchall()
    }
    assert {"rag_documents", "rag_embeddings", "rag_index_status", "rag_retrieval_logs", "rag_facts"} <= tables
    columns = {row[1] for row in conn.execute("pragma table_info(rag_documents)").fetchall()}
    assert {"account_wxid", "conversation_id"} <= columns
    assert first.get_status("missing", 99) is None
    assert second.get_status("missing", 99) is None


def test_privacy_redactor_persists_cache_and_strong_masks_api_key():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    redactor = PrivacyRedactor(conn)
    result = redactor.redact(
        "token=sk-abcdefghijklmnopqrstuvwxyz123456",
        account_wxid="account-a",
        conversation_id=7,
        source_table="messages",
        source_id="m1",
    )
    assert "sk-abcdefghijklmnopqrstuvwxyz123456" not in result.redacted_text
    assert result.pii_flags["api_key"] is True
    assert conn.execute("select count(*) from privacy_entities").fetchone()[0] == 1
    assert conn.execute("select count(*) from privacy_redaction_cache").fetchone()[0] == 1
    assert "sk-abcdefghijklmnopqrstuvwxyz123456" not in redactor.strong_mask(
        "token=sk-abcdefghijklmnopqrstuvwxyz123456"
    )


def test_embedding_adapter_exposes_raw_dimension_before_index_validation():
    class FakeSentiment:
        def has_local_embedding_model(self):
            return True

        def analyze_batch(self, texts):
            return [{"embedding": [0.1] * 768} for _ in texts]

    service = RagEmbeddingService(FakeSentiment())
    vectors = service.embed_texts(["hello"])
    assert len(vectors[0]) == 768
    assert service.last_raw_dimensions == [768]


def test_rag_store_rejects_embedding_dimension_mismatch():
    conn = sqlite3.connect(":memory:")
    store = RagStore(conn)
    document_id = store.upsert_document(
        account_wxid="wxid_a",
        conversation_id=1,
        doc_type="fact_memory",
        content="对方喜欢拿铁",
        source_table="messages",
        source_id="1",
    )
    with pytest.raises(ValueError, match="embedding dimension mismatch"):
        store.upsert_embedding(
            document_id=document_id,
            account_wxid="wxid_a",
            conversation_id=1,
            embedding_model="test",
            embedding_dim=768,
            vector=[0.1] * 384,
        )
