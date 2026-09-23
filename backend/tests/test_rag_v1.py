"""RAG v1 safety and integration tests."""

import json
import os
import sqlite3
import sys
import time


sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.realtime.feedback_attribution import SuggestionFeedbackAttributor
from app.services.realtime.llm_engine import LLMSuggestionEngine
from app.services.realtime.privacy_redactor import PrivacyRedactor
from app.services.realtime.rag_config import apply_rag_defaults, is_remote_llm_model
from app.services.realtime.rag_context_builder import RagContextBuilder
from app.services.realtime.rag_embedding import RagEmbeddingService, RagEmbeddingUnavailable
from app.services.realtime.rag_indexer import RagIndexer, RagIndexQueue
from app.services.realtime.rag_relevance_gate import RagRelevanceGate
from app.services.realtime.rag_retriever import RagRetriever
from app.services.realtime.rag_segmenter import RagSegmenter
from app.services.realtime.rag_store import RAG_INDEX_VERSION, RagStore


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
    assert settings["rag_embedding_dim"] == 768


def test_rag_defaults_migrate_legacy_384_projection_for_default_model():
    settings = apply_rag_defaults(
        {
            "rag_embedding_model": "tingting0514/text2vec-base-chinese",
            "rag_embedding_dim": 384,
        }
    )
    assert settings["rag_embedding_dim"] == 768


def test_remote_llm_detection_uses_actual_host_not_provider_label():
    assert is_remote_llm_model({"provider": "ollama", "api_base_url": "http://127.0.0.1:11434"}) is False
    assert is_remote_llm_model({"provider": "lmstudio", "api_base_url": "http://localhost:1234"}) is False
    assert is_remote_llm_model({"provider": "ollama", "api_base_url": "http://192.168.1.8:11434"}) is True
    assert is_remote_llm_model({"provider": "local", "api_base_url": "https://models.example.com/v1"}) is True


def test_rag_status_upsert_preserves_diagnostics_unless_explicitly_cleared():
    conn = _conn()
    store = RagStore(conn)
    store.upsert_status("wxid_a", 1, status="failed", dirty_since=123, last_error="boom")
    store.upsert_status("wxid_a", 1, status="pending")

    status = store.get_status("wxid_a", 1)
    assert status["dirty_since"] == 123
    assert status["last_error"] == "boom"

    store.upsert_status("wxid_a", 1, status="ready", dirty_since=None, last_error=None)
    status = store.get_status("wxid_a", 1)
    assert status["dirty_since"] is None
    assert status["last_error"] is None


def test_relevance_gate_weak_injects_relationship_context_only():
    gate = RagRelevanceGate()

    decision = gate.decide(
        query="这个人适合开玩笑吗",
        items=[
            {"doc": {"doc_type": "relationship_state", "sensitivity": "normal", "enabled": 1}, "score": 0.31},
            {"doc": {"doc_type": "dialogue_turn", "sensitivity": "normal", "enabled": 1}, "score": 0.22},
        ],
        strategy="vector",
        output_mode="suggestion",
        trigger_type="manual_request",
        user_context="这个人适合开玩笑吗",
    )

    assert decision.decision == "weak_inject"
    assert decision.reason == "weak_relationship_context"
    assert "relationship_state" in decision.allowed_doc_types


def test_relevance_gate_skips_low_score_without_no_hit_for_ordinary_chat():
    gate = RagRelevanceGate()

    decision = gate.decide(
        query="今天怎么开场",
        items=[
            {"doc": {"doc_type": "shared_memory", "sensitivity": "normal", "enabled": 1}, "score": 0.18}
        ],
        strategy="keyword_fallback",
        output_mode="suggestion",
        trigger_type="manual_request",
        user_context="今天怎么开场",
    )

    assert decision.decision == "skip"
    assert decision.reason == "low_score"
    assert decision.no_hit_eligible is False


def test_relevance_gate_no_hit_for_implicit_history_question():
    gate = RagRelevanceGate()

    decision = gate.decide(
        query="她说的那个流派是啥",
        items=[],
        strategy="keyword_fallback",
        output_mode="reply",
        trigger_type="manual_request",
        user_context="她说的那个流派是啥",
    )

    assert decision.decision == "no_hit"
    assert decision.no_hit_eligible is True


def test_relevance_gate_injects_low_score_fact_for_explicit_shared_history_question():
    gate = RagRelevanceGate()
    decision = gate.decide(
        query="我们玩过什么游戏",
        items=[
            {
                "doc": {"doc_type": "fact_memory", "sensitivity": "normal", "enabled": 1},
                "score": 0.13,
                "task_relevance_score": 0.04,
            }
        ],
        strategy="facts",
        output_mode="reply",
        trigger_type="manual_request",
        user_context="我们玩过什么游戏",
        memory_intent={"mode": "memory_request", "no_hit_eligible": True},
    )
    assert decision.decision == "inject"
    assert decision.reason == "memory_request_match"


def test_relevance_gate_blocks_sensitive_attribute_lookup_before_injection():
    decision = RagRelevanceGate().decide(
        query="她的手机号是多少？",
        items=[{
            "doc": {"doc_type": "fact_memory", "sensitivity": "normal", "enabled": 1},
            "score": 0.9,
        }],
        strategy="facts",
        output_mode="reply",
        trigger_type="manual_request",
        memory_intent={"mode": "memory_request"},
    )
    assert decision.decision == "no_hit"
    assert decision.reason == "sensitive_query_block"


def test_relevance_gate_fact_path_ignores_recent_off_topic_rerank():
    gate = RagRelevanceGate()
    decision = gate.decide(
        query="她之前提过啥想去的？",
        items=[{
            "doc": {"doc_type": "fact_memory", "sensitivity": "normal"},
            "score": 0.05,
            "task_relevance_score": 0.0,
            "off_topic_memory": True,
            "rerank_reason": "off_topic",
        }],
        strategy="facts",
        output_mode="suggestion",
        trigger_type="manual_request",
        recent_messages=[{"content": "最近加班很累"}],
        memory_intent={"mode": "memory_request"},
    )
    assert decision.decision == "inject"
    assert decision.reason == "memory_request_match"


def test_relevance_gate_ordinary_fact_uses_single_score_floor():
    gate = RagRelevanceGate()
    base = {
        "doc": {"doc_type": "fact_memory", "sensitivity": "normal"},
        "task_relevance_score": 0.0,
    }
    low = gate.decide(
        query="普通闲聊", items=[{**base, "score": 0.29}], strategy="facts",
        output_mode="suggestion", trigger_type="manual_request",
        memory_intent={"mode": "none"},
    )
    high = gate.decide(
        query="普通闲聊", items=[{**base, "score": 0.30}], strategy="facts",
        output_mode="suggestion", trigger_type="manual_request",
        memory_intent={"mode": "none"},
    )
    assert low.decision == "skip"
    assert high.decision == "inject"
    assert high.reason == "fact_memory_match"


def test_relevance_gate_fact_floor_is_configurable(monkeypatch):
    monkeypatch.setattr(
        "app.services.realtime.rag_relevance_gate.load_rag_settings",
        lambda: {"rag_fact_score_threshold": 0.50},
    )
    gate = RagRelevanceGate()
    base = {
        "doc": {"doc_type": "fact_memory", "sensitivity": "normal"},
        "task_relevance_score": 0.0,
    }
    low = gate.decide(
        query="普通闲聊", items=[{**base, "score": 0.49}], strategy="facts",
        output_mode="suggestion", trigger_type="manual_request",
        memory_intent={"mode": "none"},
    )
    high = gate.decide(
        query="普通闲聊", items=[{**base, "score": 0.50}], strategy="facts",
        output_mode="suggestion", trigger_type="manual_request",
        memory_intent={"mode": "none"},
    )
    assert low.decision == "skip"
    assert high.decision == "inject"


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


def test_rag_segmenter_splits_independently_from_bad_sessions_and_extracts_facts():
    now = int(time.time())
    messages = [
        {"id": 1, "is_sender": 0, "content": "我最近又在玩杀戮尖塔", "timestamp": now},
        {"id": 2, "is_sender": 1, "content": "哪个流派呀", "timestamp": now + 60},
        {"id": 3, "is_sender": 0, "content": "那个卡组有点贵", "timestamp": now + 120},
        {"id": 4, "is_sender": 0, "content": "明天要去吃火锅", "timestamp": now + 3 * 3600},
        {"id": 5, "is_sender": 1, "content": "吃哪家", "timestamp": now + 3 * 3600 + 60},
    ]

    segments = RagSegmenter().segment(
        messages,
        conversation_id=1,
        sessions=[{"id": 99, "start_time": now, "end_time": now + 4 * 3600}],
    )

    assert len(segments) >= 2
    assert "杀戮尖塔" in "".join(segments[0].topics + segments[0].entities)
    facts = RagSegmenter().build_fact_memories(segments[0])
    assert any("贵" in fact["content"] for fact in facts)


def test_rag_segmenter_splits_oversized_segments_with_overlap():
    now = int(time.time())
    messages = [
        {"id": index + 1, "is_sender": index % 2, "content": f"杀戮尖塔 卡组 话题 {index}", "timestamp": now + index}
        for index in range(55)
    ]

    segments = RagSegmenter().segment(messages, conversation_id=1)

    assert len(segments) >= 2
    assert set(segments[0].message_ids) & set(segments[1].message_ids)


def test_rag_segmenter_does_not_fragment_every_short_topic_shift():
    now = int(time.time())
    messages = [
        {
            "id": index + 1,
            "is_sender": index % 2,
            "content": "打瓦" if index % 2 else "吃饭",
            "timestamp": now + index * 30,
        }
        for index in range(24)
    ]

    segments = RagSegmenter().segment(messages, conversation_id=1)

    assert len(segments) <= 3


def test_rag_indexer_extracts_semantic_fact_without_marker_keywords(monkeypatch):
    conn = _conn()
    store = RagStore(conn)
    conn.executescript(
        """
        CREATE TABLE conversations (
            id INTEGER PRIMARY KEY,
            account_wxid TEXT NOT NULL,
            username TEXT NOT NULL,
            display_name TEXT,
            message_count INTEGER DEFAULT 0,
            updated_at INTEGER DEFAULT 0,
            is_deleted INTEGER DEFAULT 0
        );
        CREATE TABLE messages (
            id INTEGER PRIMARY KEY,
            conversation_id INTEGER NOT NULL,
            is_sender INTEGER NOT NULL,
            content TEXT,
            message_type INTEGER NOT NULL,
            timestamp INTEGER NOT NULL
        );
        """
    )
    now = int(time.time())
    conn.execute(
        """
        INSERT INTO conversations
        (id, account_wxid, username, display_name, message_count, updated_at)
        VALUES (1, 'wxid_a', 'alice', 'Alice', 3, ?)
        """,
        (now,),
    )
    conn.executemany(
        """
        INSERT INTO messages (id, conversation_id, is_sender, content, message_type, timestamp)
        VALUES (?, 1, ?, ?, 1, ?)
        """,
        [
            (1, 1, "最近忙吗", now - 120),
            (2, 0, "我每次压力大的时候都会去江边散步", now - 60),
            (3, 1, "听起来挺舒服", now),
        ],
    )
    monkeypatch.setattr(
        "app.services.realtime.rag_indexer.load_rag_settings",
        lambda: {
            "rag_embedding_model": "tingting0514/text2vec-base-chinese",
            "rag_embedding_dim": 384,
            "rag_privacy_mode": "balanced",
        },
    )

    class SemanticEmbedding:
        def embed_texts(self, texts):
            vectors = []
            for text in texts:
                compact = str(text)
                if any(token in compact for token in ("每次", "经常", "习惯", "反复", "都会", "压力", "江边")):
                    vectors.append([1.0, 0.0] + [0.0] * 382)
                elif any(token in compact for token in ("喜欢", "偏好", "爱吃", "爱玩", "想要")):
                    vectors.append([0.0, 1.0] + [0.0] * 382)
                else:
                    vectors.append([0.0, 0.0] + [0.0] * 382)
            return vectors

    status = RagIndexer(store=store, embedding_service=SemanticEmbedding()).rebuild_contact_index(
        account_wxid="wxid_a",
        conversation_id=1,
    )

    assert status["status"] == "ready"
    fact = conn.execute(
        "SELECT * FROM rag_documents WHERE doc_type = 'fact_memory' AND content LIKE '%江边散步%'"
    ).fetchone()
    assert fact is not None
    metadata = json.loads(fact["metadata_json"])
    assert metadata["memory_kind"] == "recurring_habit"
    assert metadata["semantic_score"] >= 0.52
    assert 2 in metadata["evidence_message_ids"]
    assert metadata["source_window_start_ts"] <= now - 60 <= metadata["source_window_end_ts"]


def test_rag_indexer_prefers_recent_quality_style_samples():
    store = RagStore(_conn())
    indexer = RagIndexer(store=store)
    now = int(time.time())
    messages = [
        {"id": 1, "is_sender": 1, "content": "早期很长很长的一段解释性文字，已经不像现在的说话方式了", "timestamp": now - 120 * 86400},
        {"id": 2, "is_sender": 1, "content": "哈哈哈", "timestamp": now - 2 * 86400},
        {"id": 3, "is_sender": 1, "content": "那晚点一起看？", "timestamp": now - 3600},
        {"id": 4, "is_sender": 1, "content": "可以呀", "timestamp": now - 1800},
        {"id": 5, "is_sender": 0, "content": "你说呢", "timestamp": now - 900},
    ]

    samples = indexer._select_style_samples(messages, last_ts=now)

    assert samples[:2] == ["那晚点一起看？", "可以呀"]
    assert "哈哈哈" not in samples


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
    assert "历史记忆检索结果" not in no_rag_prompt

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

    assert "历史记忆检索结果" in rag_prompt
    assert "对方上次提到喜欢拿铁" in rag_prompt
    assert "当前对话和用户显式需求永远高于历史记忆" in rag_prompt
    assert "不要为了使用记忆而引入旧话题" in rag_prompt
    assert rag_prompt.index("【最近对话】") < rag_prompt.index("【历史记忆检索结果】")

    direct_reply_prompt = engine._build_prompt(
        "manual_request",
        "maintain",
        {
            "user_context": "她上次说的什么流派我不知道",
            "retrieval_context": {
                "conversation_id": 7,
                "retrieval_status": "hit",
                "injection_mode": "reply",
                "items": [
                    {
                        "document_id": 4,
                        "doc_type": "shared_memory",
                        "content": "对方只提过最近在玩杀戮尖塔，没有明确说流派",
                        "score": 0.91,
                    }
                ],
            },
        },
    )
    assert "历史记忆检索结果" in direct_reply_prompt
    assert "没有明确说流派" in direct_reply_prompt
    assert "不要生成建议卡片" in direct_reply_prompt

    no_hit_prompt = engine._build_prompt(
        "manual_request",
        "maintain",
        {
            "user_context": "她上次说的游戏是啥",
            "retrieval_context": {
                "conversation_id": 7,
                "retrieval_status": "no_hit",
                "query": "她上次说的游戏是啥",
                "injection_mode": "reply",
                "items": [],
                "no_hit_guard": True,
            },
        },
    )
    assert "历史记忆检索结果" in no_hit_prompt
    assert "检索状态：no_hit" in no_hit_prompt
    assert "没查到就说没查到" in no_hit_prompt


def test_llm_engine_builds_three_state_rag_context_summary():
    engine = LLMSuggestionEngine()

    referenced = engine._build_rag_context_summary(
        {
            "_rag_log_id": 10,
            "_rag_debug": {
                "rag_enabled": True,
                "rag_retrieved": True,
                "rag_hit_count": 3,
                "rag_injection_mode": "reply",
            },
            "retrieval_context": {"items": [{"document_id": 1}, {"document_id": 2}]},
        }
    )
    assert referenced == {
        "state": "referenced",
        "label": "参考命中 2 条记录",
        "hit_count": 3,
        "referenced_count": 2,
        "log_id": 10,
    }

    no_hit = engine._build_rag_context_summary(
        {
            "_rag_debug": {
                "rag_enabled": True,
                "rag_retrieved": True,
                "rag_hit_count": 0,
                "rag_no_hit_guard": True,
            },
            "retrieval_context": {"items": [], "no_hit_guard": True},
        }
    )
    assert no_hit["state"] == "no_hit"
    assert no_hit["label"] == "未命中相关记录"

    not_referenced = engine._build_rag_context_summary(
        {
            "_rag_debug": {
                "rag_enabled": True,
                "rag_retrieved": True,
                "rag_hit_count": 2,
                "rag_injection_mode": "none",
            }
        }
    )
    assert not_referenced["state"] == "not_referenced"
    assert not_referenced["label"] == "未参考命中记录"

    hidden = engine._build_rag_context_summary({"_rag_debug": {"rag_enabled": False}})
    assert hidden["state"] == "hidden"


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
        "user_context": "她之前说过手机号拿铁吗",
    }
    RagContextBuilder(store=store).enrich_context(
        context,
        trigger_type="manual_request",
        intent="maintain",
        model_config={"provider": "openai", "api_base_url": "https://api.openai.com/v1"},
    )

    assert context["retrieval_context"]["items"]
    content = "\n".join(item["content"] for item in context["retrieval_context"]["items"])
    assert "13800138000" not in content
    assert "[PHONE_" in content
    log = conn.execute("SELECT * FROM rag_retrieval_logs").fetchone()
    assert log["redaction_status"] == "redacted"
    assert log["redaction_disabled"] == 0
    assert "1" in log["document_ids_json"]
    assert log["memory_intent_mode"] == "memory_request"
    assert log["rag_retrieved"] == 1
    assert log["rag_hit_count"] >= 1
    assert log["rag_injection_mode"] == "suggestion"


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
        "user_context": "她之前说过手机号拿铁吗",
    }
    RagContextBuilder(store=store).enrich_context(
        context,
        trigger_type="manual_request",
        intent="maintain",
        model_config={"provider": "openai", "api_base_url": "https://api.openai.com/v1"},
    )

    content = "\n".join(item["content"] for item in context["retrieval_context"]["items"])
    assert "13800138000" in content
    log = conn.execute("SELECT * FROM rag_retrieval_logs").fetchone()
    assert log["redaction_status"] == "disabled"
    assert log["redaction_disabled"] == 1


def test_context_builder_logs_missing_scope_before_retrieval(monkeypatch, caplog):
    conn = _conn()
    store = RagStore(conn)
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
        "user_context": "她上次说什么贵来着 我不记得了",
        "display_name": "Grace.",
    }
    with caplog.at_level("DEBUG", logger="app.services.realtime.rag_context_builder"):
        RagContextBuilder(store=store).enrich_context(
            context,
            trigger_type="manual_request",
            intent="maintain",
            model_config={"provider": "openai", "api_base_url": "https://api.openai.com/v1"},
        )

    assert "retrieval_context" not in context
    assert context["_rag_debug"]["rag_degraded_reason"] == "missing_scope"
    assert "reason=missing_scope" in caplog.text
    assert "account_wxid_present=False" in caplog.text


def test_context_builder_attempts_retrieval_then_gate_skips_when_memory_intent_is_none(monkeypatch):
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
        content="对方喜欢拿铁",
        redacted_content="对方喜欢拿铁",
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

    context = {
        "account_wxid": "wxid_a",
        "conversation_id": 1,
        "user_context": "你好，测试一下",
    }
    RagContextBuilder(store=store).enrich_context(
        context,
        trigger_type="manual_request",
        intent="maintain",
        model_config={"provider": "openai", "api_base_url": "https://api.openai.com/v1"},
    )

    assert "retrieval_context" not in context
    assert context["memory_intent"]["mode"] == "none"
    log = conn.execute("SELECT * FROM rag_retrieval_logs").fetchone()
    assert log["rag_retrieved"] == 1
    assert log["rag_gate_decision"] == "skip"
    assert log["rag_gate_reason"] == "no_result"


def test_context_builder_skips_off_topic_memory_for_ordinary_suggestion(monkeypatch):
    conn = _conn()
    store = RagStore(conn)
    store.upsert_status("wxid_a", 1, status="ready", document_count=1, vector_count=1)

    class OffTopicRetriever:
        def build_query(self, context, trigger_type, intent):
            return "今晚打游戏怎么回"

        def retrieve(self, **kwargs):
            return {
                "items": [
                    {
                        "doc": {
                            "id": 9,
                            "doc_type": "fact_memory",
                            "content": "时间：2026-01-01 晚上\n对方提到：以前喝拿铁觉得很香",
                            "redacted_content": "时间：2026-01-01 晚上\n对方提到：以前喝拿铁觉得很香",
                            "source_ts": int(time.time()) - 86400,
                            "sensitivity": "normal",
                            "enabled": 1,
                            "metadata_json": json.dumps({"memory_kind": "preference_like"}, ensure_ascii=False),
                        },
                        "score": 0.92,
                        "vector_score": 0.55,
                        "keyword_score": 0.0,
                    }
                ],
                "strategy": "vector",
                "status": {"status": "ready"},
                "timed_out": False,
                "degraded": False,
                "degrade_reason": None,
                "elapsed_ms": 1,
                "by_type": {"fact_memory": 1},
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
        "recent_messages": [
            {
                "sender_attr": "other",
                "content": "今晚打游戏吗",
                "timestamp": int(time.time()) - 8 * 86400,
            }
        ],
        "user_context": "怎么回自然点",
    }

    RagContextBuilder(store=store, retriever=OffTopicRetriever()).enrich_context(
        context,
        trigger_type="manual_request",
        intent="maintain",
        model_config={"provider": "openai", "api_base_url": "https://api.openai.com/v1"},
    )

    assert context["retrieval_context"]["retrieval_status"] == "hit"
    assert context["retrieval_context"]["gate_reason"] == "fact_memory_match"
    log = conn.execute("SELECT * FROM rag_retrieval_logs").fetchone()
    assert log["rag_retrieved"] == 1
    assert log["rag_hit_count"] == 1
    assert log["rag_gate_reason"] == "fact_memory_match"
    assert log["off_topic_rejected_count"] == 0
    assert log["task_relevance_score"] > 0


def test_context_builder_does_not_inject_topic_segment_for_ordinary_suggestion(monkeypatch):
    conn = _conn()
    store = RagStore(conn)
    store.upsert_status("wxid_a", 1, status="ready", document_count=1, vector_count=1)

    class TopicRetriever:
        def build_query(self, context, trigger_type, intent):
            return "杀戮尖塔怎么回"

        def retrieve(self, **kwargs):
            return {
                "items": [
                    {
                        "doc": {
                            "id": 10,
                            "doc_type": "topic_segment",
                            "content": "对方: 最近在玩杀戮尖塔\n我: 哪个流派呀",
                            "redacted_content": "对方: 最近在玩杀戮尖塔\n我: 哪个流派呀",
                            "source_ts": int(time.time()) - 3600,
                            "sensitivity": "normal",
                            "enabled": 1,
                            "metadata_json": "{}",
                        },
                        "score": 0.96,
                        "vector_score": 0.90,
                        "keyword_score": 0.70,
                    }
                ],
                "strategy": "vector",
                "status": {"status": "ready"},
                "timed_out": False,
                "degraded": False,
                "degrade_reason": None,
                "elapsed_ms": 1,
                "by_type": {"topic_segment": 1},
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
        "recent_messages": [
            {
                "sender_attr": "other",
                "content": "杀戮尖塔这个怎么接",
                "timestamp": int(time.time()) - 8 * 86400,
            }
        ],
        "user_context": "怎么回自然点",
    }

    RagContextBuilder(store=store, retriever=TopicRetriever()).enrich_context(
        context,
        trigger_type="manual_request",
        intent="maintain",
        model_config={"provider": "openai", "api_base_url": "https://api.openai.com/v1"},
    )

    assert "retrieval_context" not in context
    log = conn.execute("SELECT * FROM rag_retrieval_logs").fetchone()
    assert log["rag_gate_decision"] == "skip"
    assert log["rag_gate_reason"] == "low_score"
    assert log["task_relevance_score"] >= 0.62


def test_context_builder_injects_no_hit_guard_after_empty_retrieval(monkeypatch):
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
        content="对方喜欢拿铁",
        redacted_content="对方喜欢拿铁",
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
        "user_context": "她上次说的游戏是啥",
        "_rag_output_mode": "reply",
    }
    RagContextBuilder(store=store).enrich_context(
        context,
        trigger_type="manual_request",
        intent="maintain",
        model_config={"provider": "openai", "api_base_url": "https://api.openai.com/v1"},
    )

    assert context["retrieval_context"]["retrieval_status"] == "no_hit"
    assert context["retrieval_context"]["no_hit_guard"] is True
    assert context["retrieval_context"]["injection_mode"] == "reply"
    log = conn.execute("SELECT * FROM rag_retrieval_logs").fetchone()
    assert log["rag_retrieved"] == 1
    assert log["rag_hit_count"] == 0
    assert log["rag_injection_mode"] == "reply"
    assert log["rag_no_hit_guard"] == 1


def test_context_builder_masks_no_hit_query_for_remote_prompt(monkeypatch):
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
        content="对方喜欢拿铁",
        redacted_content="对方喜欢拿铁",
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
        "user_context": "她上次说手机号 13800138000 玩的游戏是啥",
        "_rag_output_mode": "reply",
    }
    RagContextBuilder(store=store).enrich_context(
        context,
        trigger_type="manual_request",
        intent="maintain",
        model_config={"provider": "openai", "api_base_url": "https://api.openai.com/v1"},
    )

    assert context["retrieval_context"]["retrieval_status"] == "no_hit"
    assert "13800138000" not in context["retrieval_context"]["query"]
    assert "[PHONE]" in context["retrieval_context"]["query"]


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


def test_failed_embedding_index_retries_when_model_becomes_available(monkeypatch):
    conn = _conn()
    store = RagStore(conn)
    queued = []
    store.upsert_status(
        "wxid_a",
        1,
        status="failed",
        last_error="本地 embedding 模型缺失: tingting0514/text2vec-base-chinese",
    )

    class AvailableEmbedding:
        def ensure_available(self):
            return None

    monkeypatch.setattr(RagIndexQueue, "enqueue", lambda account_wxid, conversation_id: queued.append((account_wxid, conversation_id)))
    monkeypatch.setattr(
        "app.services.realtime.rag_indexer.load_rag_settings",
        lambda: {
            "rag_embedding_model": "tingting0514/text2vec-base-chinese",
            "rag_embedding_dim": 384,
            "rag_privacy_mode": "balanced",
        },
    )

    status = RagIndexer(store=store, embedding_service=AvailableEmbedding()).ensure_contact_index(
        account_wxid="wxid_a",
        conversation_id=1,
    )

    assert status["status"] == "pending"
    assert status["last_error"] is None
    assert queued == [("wxid_a", 1)]


def test_context_builder_first_contact_without_index_injects_hot_context_and_logs(monkeypatch):
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
        "recent_messages": [
            {"sender_attr": "other", "content": "拿铁", "timestamp": int(time.time())}
        ],
        "user_context": "她之前说过喜欢拿铁吗",
    }

    RagContextBuilder(store=store).enrich_context(
        context,
        trigger_type="manual_request",
        intent="maintain",
        model_config={"provider": "openai", "api_base_url": "https://api.openai.com/v1"},
    )

    assert context["retrieval_context"]["items"][0]["doc_type"] == "hot_context"
    assert context["retrieval_context"]["index_status"] == "pending"
    log = conn.execute("SELECT * FROM rag_retrieval_logs").fetchone()
    assert log["index_status"] == "pending"
    assert log["degraded"] == 1
    assert log["degrade_reason"] == "hot_context_only"
    assert log["selected_doc_types_json"] == '["hot_context"]'


def test_context_builder_does_not_treat_old_recent_messages_as_hot_context(monkeypatch):
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
        "recent_messages": [
            {
                "sender_attr": "other",
                "content": "五月十三号的旧聊天",
                "timestamp": int(time.time()) - 8 * 86400,
            }
        ],
        "user_context": "找一下历史记录适合开启话题",
    }

    RagContextBuilder(store=store).enrich_context(
        context,
        trigger_type="manual_request",
        intent="maintain",
        model_config={"provider": "openai", "api_base_url": "https://api.openai.com/v1"},
    )

    assert "retrieval_context" not in context
    log = conn.execute("SELECT * FROM rag_retrieval_logs").fetchone()
    assert log["degrade_reason"] == "index_not_ready"


def test_hot_context_rejects_self_echo_and_messages_without_timestamp():
    builder = RagContextBuilder(store=RagStore(_conn()))

    self_echo = builder._build_hot_context_items(
        {
            "recent_messages": [
                {
                    "sender_attr": "self",
                    "content": "我们一起玩过什么游戏",
                    "timestamp": int(time.time()),
                }
            ]
        },
        account_wxid="wxid_a",
        conversation_id=1,
        query="我们一起玩过什么游戏",
        expanded_terms=[],
    )
    untrusted_legacy_time = builder._build_hot_context_items(
        {"recent_messages": [{"sender_attr": "other", "content": "很久以前的旧消息"}]},
        account_wxid="wxid_a",
        conversation_id=1,
        query="之前说过什么",
        expanded_terms=[],
    )

    assert self_echo == []
    assert untrusted_legacy_time == []


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
        "user_context": "她之前说过喜欢拿铁吗",
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


def test_rag_indexer_rebuilds_v2_multilayer_documents_and_cleans_old_auto_docs(monkeypatch):
    conn = _conn()
    store = RagStore(conn)
    conn.executescript(
        """
        CREATE TABLE conversations (
            id INTEGER PRIMARY KEY,
            account_wxid TEXT NOT NULL,
            username TEXT NOT NULL,
            display_name TEXT,
            message_count INTEGER DEFAULT 0,
            updated_at INTEGER DEFAULT 0,
            is_deleted INTEGER DEFAULT 0
        );
        CREATE TABLE messages (
            id INTEGER PRIMARY KEY,
            conversation_id INTEGER NOT NULL,
            is_sender INTEGER NOT NULL,
            content TEXT,
            message_type INTEGER NOT NULL,
            timestamp INTEGER NOT NULL
        );
        CREATE TABLE sessions (
            id INTEGER PRIMARY KEY,
            conversation_id INTEGER NOT NULL,
            start_time INTEGER,
            end_time INTEGER,
            message_count INTEGER,
            initiator TEXT
        );
        """
    )
    now = int(time.time())
    conn.execute(
        """
        INSERT INTO conversations
        (id, account_wxid, username, display_name, message_count, updated_at)
        VALUES (1, 'wxid_a', 'alice', 'Alice', 5, ?)
        """,
        (now,),
    )
    conn.executemany(
        """
        INSERT INTO messages (id, conversation_id, is_sender, content, message_type, timestamp)
        VALUES (?, 1, ?, ?, 1, ?)
        """,
        [
            (1, 0, "我最近又在玩杀戮尖塔", now - 600),
            (2, 1, "哪个流派呀", now - 540),
            (3, 0, "那个卡组有点贵", now - 480),
            (4, 1, "宝宝不是说那个贵嘛", now - 420),
            (5, 0, "对呀上次说的", now - 360),
        ],
    )
    conn.execute(
        "INSERT INTO sessions (id, conversation_id, start_time, end_time, message_count) VALUES (9, 1, ?, ?, 99)",
        (now - 10000, now + 10000),
    )
    old_doc_id = store.upsert_document(
        account_wxid="wxid_a",
        conversation_id=1,
        doc_type="topic_segment",
        source_table="messages",
        source_id="old",
        source_ts=now - 100,
        content="旧 v2 自动文档",
        redacted_content="旧 v2 自动文档",
        index_version=RAG_INDEX_VERSION,
        source_kind="historical",
    )
    feedback_id = store.upsert_document(
        account_wxid="wxid_a",
        conversation_id=1,
        doc_type="feedback_example",
        source_table="suggestion_feedback_attributions",
        source_id="fb1",
        source_ts=now,
        content="用户实际发送: 要不要一起玩",
        redacted_content="用户实际发送: 要不要一起玩",
        index_version=RAG_INDEX_VERSION,
        source_kind="feedback",
    )

    monkeypatch.setattr(
        "app.services.realtime.rag_indexer.load_rag_settings",
        lambda: {
            "rag_embedding_model": "tingting0514/text2vec-base-chinese",
            "rag_embedding_dim": 384,
            "rag_privacy_mode": "balanced",
        },
    )

    class FakeEmbedding:
        def embed_texts(self, texts):
            return [[0.1] * 384 for _ in texts]

    status = RagIndexer(store=store, embedding_service=FakeEmbedding()).rebuild_contact_index(
        account_wxid="wxid_a",
        conversation_id=1,
    )

    assert status["status"] == "ready"
    assert status["index_version"] == RAG_INDEX_VERSION
    assert conn.execute("SELECT 1 FROM rag_documents WHERE id = ?", (old_doc_id,)).fetchone() is None
    docs = conn.execute("SELECT * FROM rag_documents WHERE conversation_id = 1").fetchall()
    doc_types = {row["doc_type"] for row in docs}
    assert {"topic_segment", "fact_memory", "evidence_excerpt", "shared_memory"} <= doc_types
    assert conn.execute("SELECT 1 FROM rag_documents WHERE id = ?", (feedback_id,)).fetchone() is not None
    assert conn.execute("SELECT 1 FROM rag_embeddings WHERE document_id = ?", (feedback_id,)).fetchone() is not None
    fact = conn.execute("SELECT * FROM rag_documents WHERE doc_type = 'fact_memory' LIMIT 1").fetchone()
    metadata = json.loads(fact["metadata_json"])
    assert metadata["index_version"] == RAG_INDEX_VERSION
    assert metadata["source_kind"] == "historical"
    assert metadata["time_label"]
    assert metadata["message_ids"]


def test_retriever_prefers_recent_result_for_last_time_query():
    conn = _conn()
    store = RagStore(conn)
    now = int(time.time())
    old_ts = now - 200 * 86400
    store.upsert_status("wxid_a", 1, status="ready", document_count=2, vector_count=0)
    old_id = store.upsert_document(
        account_wxid="wxid_a",
        conversation_id=1,
        doc_type="fact_memory",
        source_table="messages",
        source_id="old",
        source_ts=old_ts,
        content="对方提到：拿铁很贵",
        redacted_content="对方提到：拿铁很贵",
        index_version=RAG_INDEX_VERSION,
    )
    new_id = store.upsert_document(
        account_wxid="wxid_a",
        conversation_id=1,
        doc_type="fact_memory",
        source_table="messages",
        source_id="new",
        source_ts=now,
        content="对方提到：拿铁很贵",
        redacted_content="对方提到：拿铁很贵",
        index_version=RAG_INDEX_VERSION,
    )

    result = RagRetriever(store=store).retrieve(
        account_wxid="wxid_a",
        conversation_id=1,
        query="上次她说拿铁什么贵来着",
    )

    ids = [item["doc"]["id"] for item in result["items"]]
    assert ids.index(new_id) < ids.index(old_id)


def test_retriever_filters_style_examples_for_explicit_memory_lookup():
    conn = _conn()
    store = RagStore(conn)
    now = int(time.time())
    store.upsert_status("wxid_a", 1, status="ready", document_count=2, vector_count=0)
    store.upsert_document(
        account_wxid="wxid_a",
        conversation_id=1,
        doc_type="self_style_example",
        source_table="messages",
        source_id="style",
        source_ts=now,
        content="杀戮尖塔 杀戮尖塔 杀戮尖塔",
        redacted_content="杀戮尖塔 杀戮尖塔 杀戮尖塔",
        index_version=RAG_INDEX_VERSION,
    )
    topic_id = store.upsert_document(
        account_wxid="wxid_a",
        conversation_id=1,
        doc_type="topic_segment",
        source_table="messages",
        source_id="topic",
        source_ts=now - 60,
        content="对方: 最近在玩杀戮尖塔 我: 哪个流派",
        redacted_content="对方: 最近在玩杀戮尖塔 我: 哪个流派",
        index_version=RAG_INDEX_VERSION,
    )

    result = RagRetriever(store=store).retrieve(
        account_wxid="wxid_a",
        conversation_id=1,
        query="那你看看文档里有没有合适的聊天记录 比如杀戮尖塔啥的",
    )

    ids = [item["doc"]["id"] for item in result["items"]]
    assert topic_id in ids
    assert all(item["doc"]["doc_type"] != "self_style_example" for item in result["items"])


def test_context_builder_injects_low_score_memory_document_for_explicit_lookup(monkeypatch):
    conn = _conn()
    store = RagStore(conn)
    now = int(time.time())
    store.upsert_status("wxid_a", 1, status="ready", document_count=1, vector_count=0)
    store.upsert_document(
        account_wxid="wxid_a",
        conversation_id=1,
        doc_type="topic_segment",
        source_table="messages",
        source_id="topic",
        source_ts=now,
        content="对方: 最近在玩杀戮尖塔 我: 哪个流派",
        redacted_content="对方: 最近在玩杀戮尖塔 我: 哪个流派",
        index_version=RAG_INDEX_VERSION,
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
        "user_context": "那你看看文档里有没有合适的聊天记录 比如杀戮尖塔啥的",
        "_rag_output_mode": "reply",
    }
    RagContextBuilder(store=store).enrich_context(
        context,
        trigger_type="manual_request",
        intent="intimate",
        model_config={"provider": "openai", "api_base_url": "https://api.openai.com/v1"},
    )

    assert context["memory_intent"]["mode"] == "memory_request"
    assert context["retrieval_context"]["retrieval_status"] == "hit"
    assert context["retrieval_context"]["items"][0]["doc_type"] == "topic_segment"
    log = conn.execute("SELECT * FROM rag_retrieval_logs").fetchone()
    assert log["rag_gate_reason"] == "memory_request_match"


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
        embedding_dim=768,
        vector=[0.1] * 768,
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
    assert result["degrade_reason"] == "embedding_unavailable"


def test_retriever_uses_shared_warm_embedding_service_for_vector_search(monkeypatch):
    conn = _conn()
    store = RagStore(conn)
    store.upsert_status("wxid_a", 1, status="ready", document_count=1, vector_count=1)
    doc_id = store.upsert_document(
        account_wxid="wxid_a",
        conversation_id=1,
        doc_type="topic_segment",
        source_table="messages",
        source_id="m1",
        source_ts=int(time.time()),
        content="蓝窗帘",
        redacted_content="蓝窗帘",
    )
    store.upsert_embedding(
        document_id=doc_id,
        account_wxid="wxid_a",
        conversation_id=1,
        embedding_model="tingting0514/text2vec-base-chinese",
        embedding_dim=768,
        vector=[1.0] + [0.0] * 767,
    )

    class WarmSentiment:
        _embedding_model = object()

        def has_local_embedding_model(self):
            return True

        def analyze_batch(self, texts):
            return [{"embedding": [1.0] + [0.0] * 767} for _ in texts]

    monkeypatch.setattr(RagEmbeddingService, "_shared_sentiment_service", WarmSentiment())

    result = RagRetriever(store=store).retrieve(
        account_wxid="wxid_a",
        conversation_id=1,
        query="完全不同的问题",
    )

    assert result["strategy"] == "vector"
    assert [item["doc"]["id"] for item in result["items"]] == [doc_id]


def test_retriever_filters_low_vector_matches_without_keyword_overlap():
    conn = _conn()
    store = RagStore(conn)
    store.upsert_status("wxid_a", 1, status="ready", document_count=1, vector_count=1)
    doc_id = store.upsert_document(
        account_wxid="wxid_a",
        conversation_id=1,
        doc_type="topic_segment",
        source_table="messages",
        source_id="m1",
        source_ts=int(time.time()),
        content="蓝窗帘",
        redacted_content="蓝窗帘",
    )
    store.upsert_embedding(
        document_id=doc_id,
        account_wxid="wxid_a",
        conversation_id=1,
        embedding_model="tingting0514/text2vec-base-chinese",
        embedding_dim=768,
        vector=[0.2, 0.979795897] + [0.0] * 766,
    )

    class LowSimilarityEmbedding:
        def embed_text(self, text):
            return [1.0] + [0.0] * 767

    result = RagRetriever(store=store, embedding_service=LowSimilarityEmbedding()).retrieve(
        account_wxid="wxid_a",
        conversation_id=1,
        query="火星基地",
    )

    assert result["strategy"] == "vector"
    assert result["items"] == []


def test_retriever_does_not_invent_memory_candidates_without_overlap():
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
    store.upsert_document(
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

    assert result["items"] == []
    assert "explicit_memory" not in result["strategy"]


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
        "user_context": "她之前说过喜欢拿铁吗",
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
        "user_context": "她之前说过拿铁和手机号吗",
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
        "user_context": "她之前说过手机号拿铁吗",
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


def test_feedback_attribution_handles_preface_then_reply_and_writes_positive_sample(monkeypatch):
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
    monkeypatch.setattr(
        "app.services.realtime.feedback_attribution.load_rag_settings",
        lambda: {
            "rag_embedding_model": "tingting0514/text2vec-base-chinese",
            "rag_embedding_dim": 384,
            "rag_privacy_mode": "balanced",
        },
    )
    monkeypatch.setattr(
        "app.services.realtime.feedback_attribution.RagEmbeddingService.embed_text",
        lambda self, text: [0.1] * 384,
    )

    result = SuggestionFeedbackAttributor(conn).attribute(suggestion_id=1, now_ts=now + 100)

    assert result["attribution_type"] == "preface_then_reply"
    row = conn.execute("SELECT * FROM suggestion_feedback_attributions").fetchone()
    assert row["attribution_type"] == "preface_then_reply"
    doc = conn.execute("SELECT * FROM rag_documents WHERE doc_type = 'feedback_example'").fetchone()
    assert doc is not None
    assert "用户实际发送" in doc["content"]
    assert doc["index_version"] == RAG_INDEX_VERSION
    assert doc["source_kind"] == "feedback"
    assert conn.execute("SELECT 1 FROM rag_embeddings WHERE document_id = ?", (doc["id"],)).fetchone() is not None
