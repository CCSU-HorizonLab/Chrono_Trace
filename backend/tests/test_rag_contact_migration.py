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
from app.services.realtime.rag_context_builder import RagQueryBuilder
from app.services.realtime.rag_indexer import RagIndexer
from app.services.realtime.rag_segmenter import RagSegment
from app.services.realtime.llm_engine import LLMSuggestionEngine
from app.webview.bridge import Bridge
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


def test_context_query_contains_only_memory_question_and_latest_user_input():
    query = RagQueryBuilder().build(
        {
            "user_context": "最新用户问题",
            "recent_messages": [
                {"sender_attr": "other", "content": "近聊噪声一"},
                {"sender_attr": "other", "content": "近聊噪声二"},
                {"sender_attr": "self", "content": "最新用户问题"},
            ],
        },
        trigger_type="manual_request",
        intent="maintain",
        memory_intent=type("Intent", (), {"mode": "memory_request", "query": "记得什么偏好吗"})(),
    )
    assert "记得什么偏好吗" in query
    assert "最新用户问题" in query
    assert "近聊噪声一" not in query
    assert "对方:" not in query


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


def test_legacy_shadow_only_config_migrates_once_to_fact_read(monkeypatch):
    legacy = {"rag_fact_read_enabled": False}
    apply_rag_defaults(legacy)
    assert legacy["rag_fact_read_enabled"] is True
    assert legacy["_rag_fact_read_migrated_v1"] is True

    user_opt_out = {
        "rag_fact_read_enabled": False,
        "_rag_fact_read_migrated_v1": True,
    }
    apply_rag_defaults(user_opt_out)
    assert user_opt_out["rag_fact_read_enabled"] is False


def test_fact_memory_flows_into_prompt_and_retrieval_log(monkeypatch):
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    store = RagStore(conn)
    store.upsert_status("account-a", 1, status="ready", document_count=0, vector_count=0)
    store.upsert_fact(
        account_wxid="account-a", conversation_id=1, subject="对方",
        kind="preference", content="对方喜欢手冲咖啡", confidence=0.95,
        evidence_message_ids=[42], as_of=1700000000,
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
    assert "主体：对方；截至：2023-11-15" in prompt
    assert "事实状态：active；置信度：0.95" in prompt
    assert "证据消息：42" in prompt


def test_bridge_rebuild_reports_indexer_failure_to_frontend(monkeypatch):
    bridge = Bridge.__new__(Bridge)
    bridge._resolve_account_wxid = lambda account_wxid="": account_wxid or "account-a"

    class FailedIndexer:
        def rebuild_contact_index(self, **kwargs):
            return {"status": "failed", "last_error": "embedding unavailable"}

    monkeypatch.setattr("app.services.realtime.rag_indexer.RagIndexer", FailedIndexer)
    result = bridge.rebuild_rag_index(7, "account-a")
    assert result["ok"] is False
    assert result["status"]["status"] == "failed"
    assert result["error"] == "embedding unavailable"


def test_bridge_rag_status_exposes_fact_read_settings(monkeypatch):
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        "CREATE TABLE conversations (id INTEGER PRIMARY KEY, account_wxid TEXT, display_name TEXT, username TEXT, is_deleted INTEGER DEFAULT 0, updated_at INTEGER)"
    )
    conn.execute(
        "INSERT INTO conversations (id, account_wxid, display_name, username, updated_at) VALUES (1, 'account-a', 'Alice', 'alice', 1)"
    )

    class FakeBridge(Bridge):
        def __init__(self):
            self.settings = {
                "rag_enabled": True,
                "rag_remote_context_redaction": True,
                "rag_allow_remote_embedding": False,
                "rag_embedding_model": "tingting0514/text2vec-base-chinese",
                "rag_embedding_dim": 768,
                "rag_privacy_mode": "balanced",
                "rag_fact_shadow_enabled": True,
                "rag_fact_read_enabled": True,
            }

    monkeypatch.setattr("app.db.connection.get_db", lambda: conn)
    monkeypatch.setattr("app.webview.bridge.get_db", lambda: conn, raising=False)
    bridge = FakeBridge()
    result = bridge.get_rag_status("account-a")
    assert result["ok"] is True
    assert result["settings"]["rag_fact_shadow_enabled"] is True
    assert result["settings"]["rag_fact_read_enabled"] is True


def test_llm_generate_consumes_fact_context_before_calling_provider(monkeypatch):
    engine = LLMSuggestionEngine()
    captured = {}

    class FakeContextBuilder:
        def enrich_context(self, context, **kwargs):
            context["_rag_log_id"] = 99
            context["_rag_conversation_id"] = 1
            context["retrieval_context"] = {
                "retrieval_status": "hit",
                "query": "喜欢什么咖啡",
                "memory_intent": {"mode": "memory_request"},
                "items": [
                    {
                        "document_id": 7,
                        "doc_type": "fact_memory",
                        "content": "对方喜欢手冲咖啡",
                        "score": 0.95,
                        "time_label": "近期",
                        "fact_status": "active",
                        "fact_confidence": 0.95,
                        "evidence_message_ids": [42],
                    }
                ],
            }

    monkeypatch.setattr(
        "app.services.realtime.rag_context_builder.RagContextBuilder", FakeContextBuilder
    )
    monkeypatch.setattr(
        engine,
        "_get_active_model",
        lambda: {
            "name": "fake",
            "provider": "local",
            "model_id": "fake-chat",
            "api_base_url": "http://127.0.0.1",
        },
    )

    def fake_call_api(model_config, prompt, **kwargs):
        captured["prompt"] = prompt
        return '{"reply":"","thought_process":"基于已核验事实","summary":"记住偏好","speeches":["下次给你冲手冲咖啡"]}'

    monkeypatch.setattr(engine, "_call_api", fake_call_api)
    result = engine.generate(
        "manual_request",
        "maintain",
        {
            "account_wxid": "account-a",
            "conversation_id": 1,
            "recent_messages": [],
            "user_context": "记得她喜欢什么咖啡吗",
        },
    )
    assert result.summary == "记住偏好"
    assert result.rag_log_id == 99
    assert "对方喜欢手冲咖啡" in captured["prompt"]
    assert "证据消息：42" in captured["prompt"]


def test_three_way_replay_no_rag_document_fallback_and_fact_priority(monkeypatch):
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    store = RagStore(conn)
    store.upsert_status("account-a", 1, status="ready", document_count=1, vector_count=0)
    store.upsert_document(
        account_wxid="account-a", conversation_id=1, doc_type="dialogue_turn",
        source_table="messages", source_id="m1", source_ts=10,
        content="对方说过喜欢咖啡", redacted_content="对方说过喜欢咖啡",
    )
    store.upsert_fact(
        account_wxid="account-a", conversation_id=1, subject="对方",
        kind="preference", content="对方喜欢手冲咖啡", confidence=0.95,
        evidence_message_ids=[42],
    )
    ReadyIndexer = type(
        "ReadyIndexer", (),
        {"ensure_contact_index": lambda self, **kwargs: {"status": "ready", "document_count": 1, "vector_count": 0}},
    )
    intent = {
        "should_retrieve": True,
        "mode": "memory_request",
        "confidence": 1.0,
        "query": "喜欢咖啡",
        "reason": "test",
    }

    def run(settings):
        monkeypatch.setattr("app.services.realtime.rag_context_builder.load_rag_settings", lambda: settings)
        monkeypatch.setattr("app.services.realtime.rag_retriever.load_rag_settings", lambda: settings)
        context = {
            "account_wxid": "account-a", "conversation_id": 1,
            "recent_messages": [], "user_context": "喜欢咖啡", "memory_intent": intent,
        }
        RagContextBuilder(store=store, indexer=ReadyIndexer()).enrich_context(
            context, trigger_type="manual_request", intent="maintain",
            model_config={"provider": "local", "api_base_url": "http://127.0.0.1"},
        )
        return context

    base = {
        "rag_remote_context_redaction": True, "rag_allow_remote_embedding": False,
        "rag_embedding_model": "test", "rag_embedding_dim": 768,
        "rag_privacy_mode": "balanced", "rag_query_scope": "latest_turn",
    }
    no_rag = run({**base, "rag_enabled": False, "rag_fact_read_enabled": True})
    docs = run({**base, "rag_enabled": True, "rag_fact_read_enabled": False})
    facts = run({**base, "rag_enabled": True, "rag_fact_read_enabled": True})
    assert "retrieval_context" not in no_rag
    assert docs["retrieval_context"]["strategy"] == "keyword_fallback"
    assert docs["retrieval_context"]["items"][0]["doc_type"] == "dialogue_turn"
    assert facts["retrieval_context"]["strategy"] == "facts"
    assert facts["retrieval_context"]["items"][0]["doc_type"] == "fact_memory"


def test_redacted_fact_without_redacted_payload_keeps_original_evidence():
    builder = RagContextBuilder(store=RagStore(sqlite3.connect(":memory:")))
    items = builder._minimize_items(
        [{
            "doc": {
                "id": 7,
                "doc_type": "fact_memory",
                "content": "对方提到：最近在玩杀戮尖塔",
                "redacted_content": None,
                "metadata_json": "{}",
            },
            "score": 0.8,
            "fact_status": "active",
            "fact_confidence": 0.8,
            "evidence_message_ids": [11],
        }],
        use_redacted=True,
    )
    assert items[0]["content"] == "对方提到：最近在玩杀戮尖塔"


def test_empty_fact_is_excluded_from_fact_retrieval():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    store = RagStore(conn)
    store.upsert_fact(
        account_wxid="account-a", conversation_id=1, subject="对方",
        kind="hobby_or_game", content="", confidence=0.99,
    )
    store.upsert_fact(
        account_wxid="account-a", conversation_id=1, subject="对方",
        kind="hobby_or_game", content="对方提到：最近在玩杀戮尖塔", confidence=0.8,
    )
    result = RagRetriever(store=store).retrieve(
        account_wxid="account-a", conversation_id=1,
        query="一起玩过什么游戏 杀戮尖塔", limit=5,
    )
    assert all(item["content"] for item in result["items"])


def test_game_query_does_not_return_unrelated_purchase_fact():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    store = RagStore(conn)
    store.upsert_fact(
        account_wxid="account-a", conversation_id=1, subject="对方",
        kind="purchase_or_price", content="对方提到：后天到", confidence=0.99,
    )
    result = RagRetriever(store=store).retrieve(
        account_wxid="account-a", conversation_id=1,
        query="我们一起玩过什么游戏", limit=5,
    )
    assert result["items"] == []


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


def _maintenance_segment():
    return RagSegment(
        segment_id="test",
        start_ts=100,
        end_ts=200,
        messages=[],
        message_ids=[],
        topics=[],
        entities=[],
        time_label="测试时间",
    )


def test_structured_fact_fusion_supersedes_conflicting_fact_and_keeps_audit_chain():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    store = RagStore(conn)
    old_id = store.upsert_fact(
        account_wxid="account-a", conversation_id=1, subject="对方",
        kind="preference", content="对方喜欢吃虾", confidence=0.8,
        evidence_message_ids=[1],
    )

    def llm(prompt):
        payload = json.loads(prompt)
        assert payload["task"] == "maintain_atomic_contact_facts"
        return {"decisions": [{"fact_id": old_id, "action": "UPDATE"}]}

    indexer = RagIndexer(store=store, structured_fact_extractor=StructuredFactExtractor(llm))
    indexer._write_structured_facts(
        account_wxid="account-a", conversation_id=1, segment=_maintenance_segment(), facts=[{
            "subject": "对方", "kind": "preference", "content": "对方最近对虾过敏，不吃了",
            "status": "active", "confidence": 0.95, "sensitivity": "normal",
            "evidence_message_ids": [2],
        }],
    )
    rows = conn.execute("SELECT * FROM rag_facts ORDER BY id").fetchall()
    assert len(rows) == 2
    assert rows[0]["status"] == "superseded"
    assert rows[0]["enabled"] == 0
    assert rows[1]["status"] == "active"
    assert rows[1]["supersedes_fact_id"] == old_id
    assert [item["id"] for item in store.list_facts("account-a", 1)] == [rows[1]["id"]]


def test_structured_fact_fusion_merges_duplicate_evidence_without_new_fact():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    store = RagStore(conn)
    old_id = store.upsert_fact(
        account_wxid="account-a", conversation_id=1, subject="对方",
        kind="preference", content="对方爱吃虾", confidence=0.6,
        evidence_message_ids=[1],
    )

    def llm(prompt):
        payload = json.loads(prompt)
        return {"decisions": [{"fact_id": old_id, "action": "MERGE"}]}

    RagIndexer(store=store, structured_fact_extractor=StructuredFactExtractor(llm))._write_structured_facts(
        account_wxid="account-a", conversation_id=1, segment=_maintenance_segment(), facts=[{
            "subject": "对方", "kind": "preference_like", "content": "对方喜欢吃虾",
            "status": "active", "confidence": 0.9, "sensitivity": "normal",
            "evidence_message_ids": [2],
        }],
    )
    rows = conn.execute("SELECT * FROM rag_facts").fetchall()
    assert len(rows) == 1
    assert rows[0]["confidence"] == 0.9
    assert json.loads(rows[0]["evidence_message_ids_json"]) == [1, 2]


def test_structured_fact_fusion_failure_falls_back_to_add():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    store = RagStore(conn)
    old_id = store.upsert_fact(
        account_wxid="account-a", conversation_id=1, subject="对方",
        kind="preference", content="对方喜欢吃虾", confidence=0.8,
    )

    def llm(_prompt):
        return "not-json"

    RagIndexer(store=store, structured_fact_extractor=StructuredFactExtractor(llm))._write_structured_facts(
        account_wxid="account-a", conversation_id=1, segment=_maintenance_segment(), facts=[{
            "subject": "对方", "kind": "preference", "content": "对方最近对虾过敏",
            "status": "active", "confidence": 0.9, "sensitivity": "normal",
            "evidence_message_ids": [],
        }],
    )
    assert len(conn.execute("SELECT id FROM rag_facts").fetchall()) == 2
    assert store.list_facts("account-a", 1)[0]["id"] != old_id


def test_structured_fact_fusion_contract_accepts_all_maintenance_actions():
    extractor = StructuredFactExtractor(
        lambda _prompt: {
            "decisions": [
                {"fact_id": 1, "action": "ADD"},
                {"fact_id": 2, "action": "UPDATE"},
                {"fact_id": 3, "action": "INVALIDATE"},
                {"fact_id": 4, "action": "MERGE"},
                {"fact_id": 5, "action": "NOOP"},
            ]
        }
    )
    decisions = extractor.decide_fusion("{}", candidate_ids={1, 2, 3, 4, 5})
    assert [item["action"] for item in decisions] == [
        "ADD", "UPDATE", "INVALIDATE", "MERGE", "NOOP"
    ]


def test_fact_vector_retrieval_handles_semantic_match_without_keyword_overlap(monkeypatch):
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    store = RagStore(conn)
    store.upsert_status("account-a", 1, status="ready", document_count=0, vector_count=0)
    allergy_id = store.upsert_fact(
        account_wxid="account-a", conversation_id=1, subject="对方",
        kind="preference", content="对方对虾过敏", confidence=0.9,
    )
    unrelated_id = store.upsert_fact(
        account_wxid="account-a", conversation_id=1, subject="对方",
        kind="preference", content="对方在玩杀戮尖塔", confidence=0.9,
    )
    store.upsert_fact_embedding(
        fact_id=allergy_id, account_wxid="account-a", conversation_id=1,
        embedding_model="test", embedding_dim=2, vector=[1.0, 0.0],
    )
    store.upsert_fact_embedding(
        fact_id=unrelated_id, account_wxid="account-a", conversation_id=1,
        embedding_model="test", embedding_dim=2, vector=[0.0, 1.0],
    )

    class WarmSentiment:
        _embedding_model = object()

        def has_local_embedding_model(self):
            return True

        def analyze_batch(self, texts):
            return [{"embedding": [1.0, 0.0]} for _ in texts]

    monkeypatch.setattr(
        "app.services.realtime.rag_retriever.load_rag_settings",
        lambda: {"rag_fact_read_enabled": True, "rag_embedding_model": "test", "rag_embedding_dim": 2},
    )
    result = RagRetriever(
        store=store,
        embedding_service=RagEmbeddingService(WarmSentiment()),
    ).retrieve(
        account_wxid="account-a", conversation_id=1,
        query="她有什么忌口？吃什么要注意？", limit=2,
    )
    assert result["strategy"] == "facts"
    assert result["items"][0]["document_id"] == allergy_id
    assert result["items"][0]["vector_score"] == 1.0


def test_fact_embedding_dimension_mismatch_is_rejected():
    store = RagStore(sqlite3.connect(":memory:"))
    fact_id = store.upsert_fact(
        account_wxid="account-a", conversation_id=1, subject="对方",
        kind="preference", content="喜欢咖啡",
    )
    with pytest.raises(ValueError, match="fact embedding dimension mismatch"):
        store.upsert_fact_embedding(
            fact_id=fact_id, account_wxid="account-a", conversation_id=1,
            embedding_model="test", embedding_dim=2, vector=[1.0],
        )


def test_fact_vector_retrieval_times_out_without_raising(monkeypatch):
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    store = RagStore(conn)
    store.upsert_status("account-a", 1, status="ready", document_count=0, vector_count=0)

    class SlowSentiment:
        _embedding_model = object()

        def has_local_embedding_model(self):
            return True

        def analyze_batch(self, texts):
            import time
            time.sleep(0.02)
            return [{"embedding": [1.0, 0.0]} for _ in texts]

    monkeypatch.setattr(
        "app.services.realtime.rag_retriever.load_rag_settings",
        lambda: {"rag_fact_read_enabled": True, "rag_embedding_model": "test", "rag_embedding_dim": 2},
    )
    result = RagRetriever(
        store=store, embedding_service=RagEmbeddingService(SlowSentiment())
    ).retrieve(
        account_wxid="account-a", conversation_id=1,
        query="忌口", timeout_ms=1,
    )
    assert result["timed_out"] is True
    assert result["degrade_reason"] == "timeout"


def test_legacy_fact_vector_backfill_is_idempotent_and_dimension_checked(monkeypatch):
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    store = RagStore(conn)
    first = store.upsert_fact(
        account_wxid="account-a", conversation_id=1, subject="对方",
        kind="preference", content="喜欢咖啡", confidence=0.8,
    )
    second = store.upsert_fact(
        account_wxid="account-a", conversation_id=1, subject="对方",
        kind="plan", content="周末去看展", confidence=0.8,
    )

    class FakeEmbedding:
        def embed_texts(self, texts):
            return [[1.0, 0.0] if index % 2 == 0 else [0.0, 1.0] for index, _ in enumerate(texts)]

    monkeypatch.setattr(
        "app.services.realtime.rag_indexer.load_rag_settings",
        lambda: {"rag_embedding_model": "test", "rag_embedding_dim": 2, "rag_embedding_provider": "local"},
    )
    indexer = RagIndexer(store=store, embedding_service=FakeEmbedding())
    result = indexer.backfill_fact_embeddings(account_wxid="account-a", conversation_id=1, batch_size=1)
    assert result["written"] == 2
    assert result["failed"] == 0
    assert store.count_fact_embeddings("account-a", 1, embedding_model="test", embedding_dim=2) == 2
    again = indexer.backfill_fact_embeddings(account_wxid="account-a", conversation_id=1)
    assert again["written"] == 0
    assert {first, second} == {row["id"] for row in store.list_facts_with_vectors("account-a", 1, embedding_model="test", embedding_dim=2)}


def test_ready_contact_index_schedules_missing_fact_vectors(monkeypatch):
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    store = RagStore(conn)
    store.upsert_fact(
        account_wxid="account-a", conversation_id=1, subject="对方",
        kind="preference", content="喜欢咖啡", confidence=0.8,
    )
    store.upsert_status(
        "account-a", 1, status="ready", document_count=1,
        embedding_model="test", embedding_dim=2, privacy_mode="balanced",
        index_version=RagIndexer.INDEX_VERSION,
    )
    scheduled = []
    monkeypatch.setattr(
        "app.services.realtime.rag_indexer.load_rag_settings",
        lambda: {
            "rag_enabled": True,
            "rag_fact_read_enabled": True,
            "rag_embedding_model": "test",
            "rag_embedding_dim": 2,
            "rag_privacy_mode": "balanced",
        },
    )
    monkeypatch.setattr(
        "app.services.realtime.rag_indexer.RagIndexQueue.enqueue_fact_backfill",
        lambda account, conversation: scheduled.append((account, conversation)),
    )
    status = RagIndexer(store=store).ensure_contact_index(account_wxid="account-a", conversation_id=1)
    assert status["status"] == "ready"
    assert scheduled == [("account-a", 1)]


def test_document_query_with_recent_word_keeps_older_relevant_memory(monkeypatch):
    import time

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    store = RagStore(conn)
    store.upsert_status("account-a", 1, status="ready", document_count=1, vector_count=0)
    store.upsert_document(
        account_wxid="account-a", conversation_id=1, doc_type="shared_memory",
        source_table="messages", source_id="m1", source_ts=int(time.time()) - 8 * 86400,
        content="她之前提过想去摄影展", redacted_content="她之前提过想去摄影展",
    )
    monkeypatch.setattr(
        "app.services.realtime.rag_retriever.load_rag_settings",
        lambda: {
            "rag_fact_read_enabled": False, "rag_embedding_model": "test",
            "rag_embedding_dim": 2,
        },
    )
    result = RagRetriever(store=store).retrieve(
        account_wxid="account-a", conversation_id=1,
        query="我刚下班，之前她提过想去什么展？", limit=3,
    )
    assert result["items"]
    assert "摄影展" in result["items"][0]["doc"]["content"]


def test_fact_kind_hints_are_configured_and_select_food_preference():
    retriever = RagRetriever()
    kinds = retriever._preferred_fact_kinds("上次她想吃什么来的？")
    assert "preference" in kinds
    assert "event" in kinds


def test_fact_context_keeps_eight_complete_facts_with_subject_and_as_of():
    builder = RagContextBuilder(store=RagStore(sqlite3.connect(":memory:")))
    facts = []
    for index in range(8):
        text = f"对方事实 {index}：" + "重要内容" * 20
        facts.append({
            "doc": {
                "id": index + 1,
                "doc_type": "fact_memory",
                "content": text,
                "metadata_json": "{}",
                "source_ts": 1700000000 + index,
            },
            "score": 0.8,
            "subject": "对方",
            "as_of": 1700000000 + index,
            "fact_status": "active",
            "fact_confidence": 0.8,
            "evidence_message_ids": [index + 10],
        })
    items = builder._minimize_items(facts, use_redacted=False)
    assert len(items) == 8
    assert items[-1]["content"].endswith("重要内容" * 20)
    assert items[0]["subject"] == "对方"
    assert items[0]["as_of"] == 1700000000


def test_fact_context_keeps_sub_500_char_fact_without_half_sentence_cut():
    builder = RagContextBuilder(store=RagStore(sqlite3.connect(":memory:")))
    content = "对方的完整偏好：" + "喜欢清淡饮食，晚餐尽量少油少盐。" * 20
    assert len(content) <= 500
    item = builder._minimize_items(
        [{
            "doc": {
                "id": 1,
                "doc_type": "fact_memory",
                "content": content,
                "metadata_json": "{}",
                "source_ts": 1700000000,
            },
            "score": 0.8,
            "subject": "对方",
            "as_of": 1700000000,
            "fact_status": "active",
            "fact_confidence": 0.8,
            "evidence_message_ids": [10],
        }],
        use_redacted=False,
    )
    assert item[0]["content"] == content


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
