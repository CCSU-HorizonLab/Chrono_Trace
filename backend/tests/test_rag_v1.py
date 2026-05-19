"""RAG v1 safety and integration tests."""

import os
import sqlite3
import sys
import time


sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.realtime.feedback_attribution import SuggestionFeedbackAttributor
from app.services.realtime.llm_engine import LLMSuggestionEngine
from app.services.realtime.privacy_redactor import PrivacyRedactor
from app.services.realtime.rag_config import apply_rag_defaults
from app.services.realtime.rag_context_builder import RagContextBuilder
from app.services.realtime.rag_embedding import RagEmbeddingUnavailable
from app.services.realtime.rag_indexer import RagIndexer, RagIndexQueue
from app.services.realtime.rag_retriever import RagRetriever
from app.services.realtime.rag_store import RagStore


def _conn():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    return conn


def test_rag_defaults_are_privacy_preserving():
    settings = apply_rag_defaults({})

    assert settings["rag_enabled"] is False
    assert settings["rag_remote_context_redaction"] is True
    assert settings["rag_allow_remote_embedding"] is False
    assert settings["rag_embedding_model"] == "tingting0514/text2vec-base-chinese"
    assert settings["rag_embedding_dim"] == 384


def test_privacy_redactor_masks_strong_sensitive_values_and_keeps_stable_placeholders():
    conn = _conn()
    redactor = PrivacyRedactor(conn)

    first = redactor.redact(
        "我的手机号是 13800138000，身份证 11010119900307001X",
        account_wxid="wxid_a",
        conversation_id=1,
        source_table="messages",
        source_id="1",
    )
    second = redactor.redact(
        "再说一次 13800138000",
        account_wxid="wxid_a",
        conversation_id=1,
        source_table="messages",
        source_id="2",
    )

    assert "13800138000" not in first.redacted_text
    assert "11010119900307001X" not in first.redacted_text
    assert "[PHONE_" in first.redacted_text
    assert first.redacted_text.split("手机号是 ", 1)[1].split("，", 1)[0] in second.redacted_text
    assert first.pii_flags["phone"] is True
    assert first.pii_flags["id_card"] is True


def test_prompt_omits_rag_when_disabled_and_injects_constructed_context_only():
    engine = LLMSuggestionEngine()

    no_rag_prompt = engine._build_prompt(
        "manual_request",
        "maintain",
        {
            "recent_messages": [{"sender_attr": "other", "content": "今天咖啡还挺好喝"}],
            "user_context": "怎么回",
        },
    )
    assert "联系人级共同记忆 RAG" not in no_rag_prompt

    rag_prompt = engine._build_prompt(
        "manual_request",
        "maintain",
        {
            "recent_messages": [{"sender_attr": "other", "content": "今天咖啡还挺好喝"}],
            "user_context": "怎么回",
            "retrieval_context": {
                "conversation_id": 7,
                "index_status": "ready",
                "redaction_status": "redacted",
                "degraded": False,
                "items": [
                    {
                        "document_id": 3,
                        "doc_type": "shared_memory",
                        "content": "对方上次提到喜欢拿铁",
                        "score": 0.88,
                    }
                ],
            },
        },
    )

    assert "联系人级共同记忆 RAG" in rag_prompt
    assert "对方上次提到喜欢拿铁" in rag_prompt
    assert rag_prompt.index("【最近对话】") < rag_prompt.index("【联系人级共同记忆 RAG（辅助参考，最近对话优先）】")


def test_context_builder_uses_redacted_content_for_remote_model_and_logs_trace(monkeypatch):
    conn = _conn()
    store = RagStore(conn)
    store.upsert_status(
        "wxid_a",
        1,
        status="ready",
        document_count=1,
        vector_count=0,
    )
    store.upsert_document(
        account_wxid="wxid_a",
        conversation_id=1,
        doc_type="dialogue_turn",
        source_table="messages",
        source_id="m1",
        source_ts=100,
        content="对方手机号 13800138000，喜欢拿铁",
        redacted_content="对方手机号 [PHONE_XXXXXX]，喜欢拿铁",
    )
    conn.commit()

    monkeypatch.setattr(
        "app.services.realtime.rag_context_builder.load_rag_settings",
        lambda: {
            "rag_enabled": True,
            "rag_remote_context_redaction": True,
            "rag_allow_remote_embedding": False,
            "rag_embedding_model": "tingting0514/text2vec-base-chinese",
            "rag_embedding_dim": 384,
            "rag_privacy_mode": "balanced",
        },
    )
    monkeypatch.setattr(
        "app.services.realtime.rag_retriever.load_rag_settings",
        lambda: {
            "rag_enabled": True,
            "rag_embedding_model": "tingting0514/text2vec-base-chinese",
            "rag_embedding_dim": 384,
            "rag_privacy_mode": "balanced",
        },
    )

    context = {
        "account_wxid": "wxid_a",
        "conversation_id": 1,
        "recent_messages": [{"sender_attr": "other", "content": "拿铁"}],
    }
    RagContextBuilder(store=store).enrich_context(
        context,
        trigger_type="manual_request",
        intent="maintain",
        model_config={"provider": "openai", "api_base_url": "https://api.openai.com/v1"},
    )

    assert context["retrieval_context"]["items"]
    content = context["retrieval_context"]["items"][0]["content"]
    assert "13800138000" not in content
    assert "[PHONE_" in content
    log = conn.execute("SELECT * FROM rag_retrieval_logs").fetchone()
    assert log["redaction_status"] == "redacted"
    assert log["redaction_disabled"] == 0
    assert log["document_ids_json"] == "[1]"


def test_context_builder_marks_redaction_disabled_when_user_explicitly_turns_it_off(monkeypatch):
    conn = _conn()
    store = RagStore(conn)
    store.upsert_status("wxid_a", 1, status="ready", document_count=1, vector_count=0)
    store.upsert_document(
        account_wxid="wxid_a",
        conversation_id=1,
        doc_type="dialogue_turn",
        source_table="messages",
        source_id="m1",
        source_ts=100,
        content="对方手机号 13800138000，喜欢拿铁",
        redacted_content="对方手机号 [PHONE_XXXXXX]，喜欢拿铁",
    )
    conn.commit()

    monkeypatch.setattr(
        "app.services.realtime.rag_context_builder.load_rag_settings",
        lambda: {
            "rag_enabled": True,
            "rag_remote_context_redaction": False,
            "rag_allow_remote_embedding": False,
            "rag_embedding_model": "tingting0514/text2vec-base-chinese",
            "rag_embedding_dim": 384,
            "rag_privacy_mode": "balanced",
        },
    )
    monkeypatch.setattr(
        "app.services.realtime.rag_retriever.load_rag_settings",
        lambda: {
            "rag_enabled": True,
            "rag_embedding_model": "tingting0514/text2vec-base-chinese",
            "rag_embedding_dim": 384,
            "rag_privacy_mode": "balanced",
        },
    )

    context = {
        "account_wxid": "wxid_a",
        "conversation_id": 1,
        "recent_messages": [{"sender_attr": "other", "content": "拿铁"}],
    }
    RagContextBuilder(store=store).enrich_context(
        context,
        trigger_type="manual_request",
        intent="maintain",
        model_config={"provider": "openai", "api_base_url": "https://api.openai.com/v1"},
    )

    assert "13800138000" in context["retrieval_context"]["items"][0]["content"]
    log = conn.execute("SELECT * FROM rag_retrieval_logs").fetchone()
    assert log["redaction_status"] == "disabled"
    assert log["redaction_disabled"] == 1


def test_first_contact_without_index_does_not_rebuild_synchronously(monkeypatch):
    conn = _conn()
    store = RagStore(conn)
    queued = []

    monkeypatch.setattr(RagIndexQueue, "enqueue", lambda account_wxid, conversation_id: queued.append((account_wxid, conversation_id)))
    monkeypatch.setattr(
        RagIndexer,
        "rebuild_contact_index",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("sync rebuild should not run")),
    )
    monkeypatch.setattr(
        "app.services.realtime.rag_indexer.load_rag_settings",
        lambda: {
            "rag_embedding_model": "tingting0514/text2vec-base-chinese",
            "rag_embedding_dim": 384,
            "rag_privacy_mode": "balanced",
        },
    )

    status = RagIndexer(store=store).ensure_contact_index(account_wxid="wxid_a", conversation_id=1)

    assert status["status"] == "pending"
    assert queued == [("wxid_a", 1)]


def test_context_builder_first_contact_without_index_omits_rag_and_logs(monkeypatch):
    conn = _conn()
    store = RagStore(conn)
    monkeypatch.setattr(RagIndexQueue, "enqueue", lambda account_wxid, conversation_id: None)
    monkeypatch.setattr(
        "app.services.realtime.rag_context_builder.load_rag_settings",
        lambda: {
            "rag_enabled": True,
            "rag_remote_context_redaction": True,
            "rag_allow_remote_embedding": False,
            "rag_embedding_model": "tingting0514/text2vec-base-chinese",
            "rag_embedding_dim": 384,
            "rag_privacy_mode": "balanced",
        },
    )
    monkeypatch.setattr(
        "app.services.realtime.rag_indexer.load_rag_settings",
        lambda: {
            "rag_embedding_model": "tingting0514/text2vec-base-chinese",
            "rag_embedding_dim": 384,
            "rag_privacy_mode": "balanced",
        },
    )
    context = {
        "account_wxid": "wxid_a",
        "conversation_id": 1,
        "recent_messages": [{"sender_attr": "other", "content": "拿铁"}],
    }

    RagContextBuilder(store=store).enrich_context(
        context,
        trigger_type="manual_request",
        intent="maintain",
        model_config={"provider": "openai", "api_base_url": "https://api.openai.com/v1"},
    )

    assert "retrieval_context" not in context
    log = conn.execute("SELECT * FROM rag_retrieval_logs").fetchone()
    assert log["index_status"] == "pending"
    assert log["degraded"] == 1
    assert log["degrade_reason"] == "index_not_ready"


def test_stale_index_uses_old_documents_and_queues_rebuild(monkeypatch):
    conn = _conn()
    store = RagStore(conn)
    store.upsert_status("wxid_a", 1, status="stale", document_count=1, vector_count=0)
    store.upsert_document(
        account_wxid="wxid_a",
        conversation_id=1,
        doc_type="shared_memory",
        source_table="messages",
        source_id="m1",
        source_ts=int(time.time()),
        content="对方喜欢拿铁",
        redacted_content="对方喜欢拿铁",
    )
    conn.commit()
    queued = []
    monkeypatch.setattr(RagIndexQueue, "enqueue", lambda account_wxid, conversation_id: queued.append((account_wxid, conversation_id)))
    monkeypatch.setattr(
        "app.services.realtime.rag_context_builder.load_rag_settings",
        lambda: {
            "rag_enabled": True,
            "rag_remote_context_redaction": True,
            "rag_allow_remote_embedding": False,
            "rag_embedding_model": "tingting0514/text2vec-base-chinese",
            "rag_embedding_dim": 384,
            "rag_privacy_mode": "balanced",
        },
    )

    context = {
        "account_wxid": "wxid_a",
        "conversation_id": 1,
        "recent_messages": [{"sender_attr": "other", "content": "拿铁"}],
    }
    RagContextBuilder(store=store).enrich_context(
        context,
        trigger_type="manual_request",
        intent="maintain",
        model_config={"provider": "ollama", "api_base_url": "http://localhost:11434/v1"},
    )

    assert context["retrieval_context"]["items"]
    assert context["retrieval_context"]["index_status"] == "stale"
    assert queued == [("wxid_a", 1)]


def test_retriever_embedding_unavailable_falls_back_to_keyword():
    conn = _conn()
    store = RagStore(conn)
    store.upsert_status("wxid_a", 1, status="ready", document_count=1, vector_count=1)
    doc_id = store.upsert_document(
        account_wxid="wxid_a",
        conversation_id=1,
        doc_type="dialogue_turn",
        source_table="messages",
        source_id="m1",
        source_ts=int(time.time()),
        content="对方喜欢拿铁",
        redacted_content="对方喜欢拿铁",
    )
    store.upsert_embedding(
        document_id=doc_id,
        account_wxid="wxid_a",
        conversation_id=1,
        embedding_model="tingting0514/text2vec-base-chinese",
        embedding_dim=384,
        vector=[0.1] * 384,
    )

    class MissingEmbedding:
        def embed_text(self, text):
            raise RagEmbeddingUnavailable("missing")

    result = RagRetriever(store=store, embedding_service=MissingEmbedding()).retrieve(
        account_wxid="wxid_a",
        conversation_id=1,
        query="拿铁",
    )

    assert result["items"]
    assert result["strategy"] == "keyword_fallback"
    assert result["degraded"] is True


def test_explicit_memory_request_falls_back_to_recent_contact_memory():
    conn = _conn()
    store = RagStore(conn)
    store.upsert_status("wxid_a", 1, status="ready", document_count=2, vector_count=0)
    store.upsert_document(
        account_wxid="wxid_a",
        conversation_id=1,
        doc_type="relationship_state",
        source_table="conversations",
        source_id="1",
        source_ts=int(time.time()),
        content="关系摘要",
        redacted_content="关系摘要",
    )
    memory_doc_id = store.upsert_document(
        account_wxid="wxid_a",
        conversation_id=1,
        doc_type="dialogue_turn",
        source_table="messages",
        source_id="chunk:1",
        source_ts=int(time.time()),
        content="蓝窗帘 木星基地 奶龙梦男",
        redacted_content="蓝窗帘 木星基地 奶龙梦男",
    )

    result = RagRetriever(store=store).retrieve(
        account_wxid="wxid_a",
        conversation_id=1,
        query="你找一下相关记忆 关于上次店的 我们去吃的啥我其实有点不记得了 给我建议话术",
    )

    assert result["items"]
    assert result["items"][0]["doc"]["id"] == memory_doc_id
    assert "explicit_memory" in result["strategy"]


def test_context_builder_timeout_omits_rag_and_logs_timeout(monkeypatch):
    conn = _conn()
    store = RagStore(conn)
    store.upsert_status("wxid_a", 1, status="ready", document_count=1, vector_count=0)

    class SlowRetriever:
        def build_query(self, context, trigger_type, intent):
            return "拿铁"

        def retrieve(self, **kwargs):
            time.sleep(0.85)
            return {
                "items": [{"doc": {"id": 1, "doc_type": "dialogue_turn", "content": "对方喜欢拿铁"}, "score": 1}],
                "timed_out": False,
                "degraded": False,
                "elapsed_ms": 850,
            }

    monkeypatch.setattr(
        "app.services.realtime.rag_context_builder.load_rag_settings",
        lambda: {
            "rag_enabled": True,
            "rag_remote_context_redaction": True,
            "rag_allow_remote_embedding": False,
            "rag_embedding_model": "tingting0514/text2vec-base-chinese",
            "rag_embedding_dim": 384,
            "rag_privacy_mode": "balanced",
        },
    )
    context = {
        "account_wxid": "wxid_a",
        "conversation_id": 1,
        "recent_messages": [{"sender_attr": "other", "content": "拿铁"}],
    }
    RagContextBuilder(store=store, retriever=SlowRetriever()).enrich_context(
        context,
        trigger_type="manual_request",
        intent="maintain",
        model_config={"provider": "openai", "api_base_url": "https://api.openai.com/v1"},
    )

    assert "retrieval_context" not in context
    log = conn.execute("SELECT * FROM rag_retrieval_logs").fetchone()
    assert log["timed_out"] == 1
    assert log["degraded"] == 1
    assert log["degrade_reason"] == "timeout"


def test_redaction_failure_uses_strong_mask_and_drops_sensitive_items(monkeypatch):
    conn = _conn()
    store = RagStore(conn)
    store.upsert_status("wxid_a", 1, status="ready", document_count=2, vector_count=0)
    store.upsert_document(
        account_wxid="wxid_a",
        conversation_id=1,
        doc_type="dialogue_turn",
        source_table="messages",
        source_id="m1",
        source_ts=int(time.time()),
        content="手机号 13800138000 拿铁",
        redacted_content="手机号 13800138000 拿铁",
    )
    store.upsert_document(
        account_wxid="wxid_a",
        conversation_id=1,
        doc_type="shared_memory",
        source_table="messages",
        source_id="m2",
        source_ts=int(time.time()),
        content="身份证 11010119900307001X 拿铁",
        redacted_content="身份证 11010119900307001X 拿铁",
        sensitivity="sensitive",
    )
    monkeypatch.setattr(
        "app.services.realtime.rag_context_builder.load_rag_settings",
        lambda: {
            "rag_enabled": True,
            "rag_remote_context_redaction": True,
            "rag_allow_remote_embedding": False,
            "rag_embedding_model": "tingting0514/text2vec-base-chinese",
            "rag_embedding_dim": 384,
            "rag_privacy_mode": "balanced",
        },
    )
    monkeypatch.setattr(PrivacyRedactor, "redact", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("boom")))

    context = {
        "account_wxid": "wxid_a",
        "conversation_id": 1,
        "recent_messages": [{"sender_attr": "other", "content": "拿铁 手机号 身份证"}],
    }
    RagContextBuilder(store=store).enrich_context(
        context,
        trigger_type="manual_request",
        intent="maintain",
        model_config={"provider": "openai", "api_base_url": "https://api.openai.com/v1"},
    )

    contents = " ".join(item["content"] for item in context["retrieval_context"]["items"])
    assert "13800138000" not in contents
    assert "11010119900307001X" not in contents
    assert "[PHONE]" in contents
    log = conn.execute("SELECT * FROM rag_retrieval_logs").fetchone()
    assert log["redaction_status"] == "strong_mask"
    assert log["redaction_fallback"] == 1


def test_strong_mask_failure_blocks_remote_rag(monkeypatch):
    conn = _conn()
    store = RagStore(conn)
    store.upsert_status("wxid_a", 1, status="ready", document_count=1, vector_count=0)
    store.upsert_document(
        account_wxid="wxid_a",
        conversation_id=1,
        doc_type="dialogue_turn",
        source_table="messages",
        source_id="m1",
        source_ts=int(time.time()),
        content="手机号 13800138000 拿铁",
        redacted_content="手机号 13800138000 拿铁",
    )
    monkeypatch.setattr(
        "app.services.realtime.rag_context_builder.load_rag_settings",
        lambda: {
            "rag_enabled": True,
            "rag_remote_context_redaction": True,
            "rag_allow_remote_embedding": False,
            "rag_embedding_model": "tingting0514/text2vec-base-chinese",
            "rag_embedding_dim": 384,
            "rag_privacy_mode": "balanced",
        },
    )
    monkeypatch.setattr(PrivacyRedactor, "redact", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("boom")))
    monkeypatch.setattr(PrivacyRedactor, "strong_mask", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("mask boom")))

    context = {
        "account_wxid": "wxid_a",
        "conversation_id": 1,
        "recent_messages": [{"sender_attr": "other", "content": "拿铁"}],
    }
    RagContextBuilder(store=store).enrich_context(
        context,
        trigger_type="manual_request",
        intent="maintain",
        model_config={"provider": "openai", "api_base_url": "https://api.openai.com/v1"},
    )

    assert "retrieval_context" not in context
    log = conn.execute("SELECT * FROM rag_retrieval_logs").fetchone()
    assert log["redaction_status"] == "blocked"
    assert log["redaction_fallback"] == 1


def test_enabled_superseded_sensitive_and_old_memory_filtering():
    conn = _conn()
    store = RagStore(conn)
    store.upsert_status("wxid_a", 1, status="ready", document_count=3, vector_count=0, enabled=True)
    old_ts = int(time.time()) - 200 * 86400
    new_ts = int(time.time())
    old_id = store.upsert_document(
        account_wxid="wxid_a",
        conversation_id=1,
        doc_type="shared_memory",
        source_table="messages",
        source_id="old",
        source_ts=old_ts,
        content="对方喜欢拿铁",
        redacted_content="对方喜欢拿铁",
    )
    new_id = store.upsert_document(
        account_wxid="wxid_a",
        conversation_id=1,
        doc_type="shared_memory",
        source_table="messages",
        source_id="new",
        source_ts=new_ts,
        content="对方喜欢拿铁",
        redacted_content="对方喜欢拿铁",
    )
    superseded_id = store.upsert_document(
        account_wxid="wxid_a",
        conversation_id=1,
        doc_type="shared_memory",
        source_table="messages",
        source_id="superseded",
        source_ts=new_ts,
        content="对方喜欢旧咖啡",
        redacted_content="对方喜欢旧咖啡",
    )
    conn.execute("UPDATE rag_documents SET superseded_by = ? WHERE id = ?", (new_id, superseded_id))
    store.upsert_document(
        account_wxid="wxid_a",
        conversation_id=1,
        doc_type="shared_memory",
        source_table="messages",
        source_id="sensitive",
        source_ts=new_ts,
        content="身份证 11010119900307001X",
        redacted_content="[ID_CARD]",
        sensitivity="sensitive",
    )

    result = RagRetriever(store=store).retrieve(
        account_wxid="wxid_a",
        conversation_id=1,
        query="拿铁",
    )
    ids = [item["doc"]["id"] for item in result["items"]]
    assert superseded_id not in ids
    assert new_id in ids and old_id in ids
    assert ids.index(new_id) < ids.index(old_id)

    store.set_conversation_enabled("wxid_a", 1, False)
    disabled = RagRetriever(store=store).retrieve(
        account_wxid="wxid_a",
        conversation_id=1,
        query="拿铁",
    )
    assert disabled["items"] == []
    assert disabled["degrade_reason"] == "conversation_disabled"


def test_feedback_attribution_handles_preface_then_reply_and_writes_positive_sample():
    conn = _conn()
    store = RagStore(conn)
    conn.executescript(
        """
        CREATE TABLE conversations (
            id INTEGER PRIMARY KEY,
            account_wxid TEXT NOT NULL,
            username TEXT NOT NULL,
            display_name TEXT NOT NULL,
            updated_at INTEGER DEFAULT 0,
            is_deleted INTEGER DEFAULT 0
        );
        CREATE TABLE realtime_suggestions (
            id INTEGER PRIMARY KEY,
            account_wxid TEXT NOT NULL,
            batch_id TEXT NOT NULL,
            trigger_type TEXT NOT NULL,
            intent TEXT NOT NULL,
            speeches TEXT NOT NULL,
            status TEXT,
            trigger_context TEXT,
            created_at INTEGER NOT NULL
        );
        CREATE TABLE realtime_message_buffer (
            id INTEGER PRIMARY KEY,
            account_wxid TEXT NOT NULL,
            batch_id TEXT NOT NULL,
            talker_username TEXT,
            talker_display_name TEXT,
            sender_attr TEXT NOT NULL,
            content TEXT,
            message_type TEXT,
            timestamp INTEGER NOT NULL,
            created_at INTEGER NOT NULL
        );
        """
    )
    now = int(time.time())
    conn.execute(
        "INSERT INTO conversations (id, account_wxid, username, display_name, updated_at) VALUES (1, 'wxid_a', 'alice', 'Alice', ?)",
        (now,),
    )
    conn.execute(
        """
        INSERT INTO realtime_suggestions
        (id, account_wxid, batch_id, trigger_type, intent, speeches, status, created_at)
        VALUES (1, 'wxid_a', 'b1', 'manual_request', 'maintain', '["要不要一起喝拿铁"]', 'pending', ?)
        """,
        (now,),
    )
    conn.executemany(
        """
        INSERT INTO realtime_message_buffer
        (id, account_wxid, batch_id, talker_username, talker_display_name, sender_attr, content, message_type, timestamp, created_at)
        VALUES (?, 'wxid_a', 'b1', 'alice', 'Alice', 'self', ?, 'text', ?, ?)
        """,
        [
            (1, "对了", now + 20, now + 20),
            (2, "要不要一起喝拿铁", now + 80, now + 80),
        ],
    )

    result = SuggestionFeedbackAttributor(conn).attribute(suggestion_id=1, now_ts=now + 100)

    assert result["attribution_type"] == "preface_then_reply"
    row = conn.execute("SELECT * FROM suggestion_feedback_attributions").fetchone()
    assert row["attribution_type"] == "preface_then_reply"
    doc = conn.execute("SELECT * FROM rag_documents WHERE doc_type = 'feedback_example'").fetchone()
    assert doc is not None
    assert "用户实际发送" in doc["content"]
