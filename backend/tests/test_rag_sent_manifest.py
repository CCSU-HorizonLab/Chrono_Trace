"""G2/G6 生成审计测试:任务化 prompt 门控、发送清单、badge、日志回填。"""

import os
import sqlite3
import sys


sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.realtime.llm_engine import LLMSuggestionEngine
from app.services.realtime.rag.store import RagStore


def _engine():
    return LLMSuggestionEngine()


def _fact_item(fact_id: int, content: str):
    return {
        "document_id": fact_id,
        "doc_type": "fact_memory",
        "content": content,
        "score": 0.8,
        "time_label": "3天前",
        "fact_status": "active",
        "fact_confidence": 0.8,
        "evidence_message_ids": [11, 12],
        "subject": "共同",
        "memory_kind": "hobby_or_game",
        "as_of": 1700000000,
    }


def test_invitation_prompt_allows_speeches_and_relationship_knowledge():
    engine = _engine()
    context = {
        "user_context": [{"role": "user", "content": "我想约她打游戏"}],
        "relationship_policy": {"stage": "暧昧期", "closeness_band": "medium", "state_id": 42},
        "contact_preferences": [
            {"pref_id": 7, "slot_kind": "preference", "summary": "喜欢主机游戏", "confidence": 0.8},
            {"pref_id": 8, "slot_kind": "preference", "summary": "喜欢贴膜", "confidence": 0.8},
        ],
        "recent_messages": [
            {"id": 1, "timestamp": 100, "sender_attr": "friend", "content": "最近在打游戏"},
        ],
    }
    prompt = engine._build_prompt("manual_request", "intimate", context)
    # 邀约任务:回答 + 可发送话术,不再强制 speeches 为空
    assert "不要生成建议卡片" not in prompt
    assert "先在 `reply` 字段直接回应用户" in prompt
    assert "【当前关系策略" in prompt
    assert "【对方偏好与雷点" in prompt
    manifest = context["_rag_sent_manifest"]
    assert "relationship_policy" in manifest["blocks"]
    assert "contact_preferences" in manifest["blocks"]
    assert manifest["policy_ids"] == [42]
    assert manifest["contact_preference_ids"] == [7, 8]
    assert len(manifest["prompt_hash"]) == 64


def test_memory_qa_prompt_skips_style_and_policy_blocks():
    engine = _engine()
    context = {
        "user_context": [{"role": "user", "content": "我们玩过什么游戏"}],
        "retrieval_context": {
            "items": [_fact_item(101, "我们一起玩过路易吉鬼屋,配合默契")],
            "retrieval_status": "hit",
            "no_hit_guard": False,
            "query": "我们玩过什么游戏",
            "memory_intent": {"mode": "memory_request"},
        },
        "relationship_policy": {"stage": "暧昧期", "state_id": 42},
        "contact_profile": {"personality_tags": ["慢热"]},
        "self_profile": {"typing_style": "短句"},
        "_rag_debug": {"rag_enabled": True, "rag_hit_count": 1},
    }
    prompt = engine._build_prompt("manual_request", "maintain", context)
    assert "直接回复用户本人" in prompt
    assert "【用户表达风格" not in prompt
    assert "【量化风格硬约束" not in prompt
    assert "【对方画像" not in prompt
    assert "【当前关系策略" not in prompt
    assert "我们一起玩过路易吉鬼屋" in prompt
    manifest = context["_rag_sent_manifest"]
    assert "self_profile" not in manifest["blocks"]
    assert "style_constraints" not in manifest["blocks"]
    assert manifest["fact_ids"] == [101]
    reasons = {entry["reason"] for entry in manifest["excluded"]}
    assert "task_knowledge_not_needed" in reasons


def test_auto_trigger_prompt_keeps_full_knowledge():
    engine = _engine()
    context = {
        "relationship_policy": {"stage": "老朋友", "state_id": 1},
        "self_profile": {"typing_style": "短句"},
        "recent_messages": [
            {"id": 1, "timestamp": 100, "sender_attr": "friend", "content": "在忙"},
        ],
    }
    prompt = engine._build_prompt("silence", "maintain", context)
    assert "【当前关系策略" in prompt
    assert "【用户表达风格" in prompt
    assert "【量化风格硬约束" in prompt


def test_transfer_events_rendered_as_events_with_notice_guard():
    engine = _engine()
    messages = [
        {"id": i, "timestamp": i, "sender_attr": "friend", "content": content}
        for i, content in enumerate(["[转账]已收款", "[转账]已收款", "[转账]已收款"], 1)
    ]
    context = {"recent_messages": messages}
    prompt = engine._build_prompt("topic_cooling", "maintain", context)
    assert "【事件】" in prompt
    assert "非聊天发言" in prompt
    assert "不得据此推断对方冷淡" in prompt


def test_badge_uses_manifest_fact_count():
    engine = _engine()
    context = {
        "_rag_debug": {"rag_enabled": True, "rag_hit_count": 5},
        "retrieval_context": {
            "items": [_fact_item(1, "a"), _fact_item(2, "b")],
            "no_hit_guard": False,
        },
        "_rag_sent_manifest": {
            "blocks": ["retrieval_memory"],
            "fact_ids": [1],
            "document_ids": [1, 2],
            "policy_ids": [],
            "contact_preference_ids": [],
        },
    }
    badge = engine._build_rag_context_summary(context)
    assert badge["state"] == "fact_hit"
    assert badge["label"] == "已参考 1 条历史事实"
    assert badge["referenced_count"] == 2


def test_badge_not_referenced_when_manifest_sends_nothing():
    """候选命中但未渲染 → UI 不得显示已参考。"""
    engine = _engine()
    context = {
        "_rag_debug": {"rag_enabled": True, "rag_hit_count": 3},
        "retrieval_context": {
            "items": [_fact_item(1, "a")],
            "no_hit_guard": False,
        },
        "_rag_sent_manifest": {
            "blocks": [],
            "fact_ids": [],
            "document_ids": [],
            "policy_ids": [],
            "contact_preference_ids": [],
        },
    }
    badge = engine._build_rag_context_summary(context)
    assert badge["state"] == "not_referenced"
    assert badge["label"] == "未参考命中记录"


def test_badge_falls_back_without_manifest():
    engine = _engine()
    context = {
        "_rag_debug": {"rag_enabled": True, "rag_hit_count": 1},
        "retrieval_context": {
            "items": [_fact_item(1, "a")],
            "no_hit_guard": False,
        },
    }
    badge = engine._build_rag_context_summary(context)
    assert badge["state"] == "fact_hit"
    assert badge["referenced_count"] == 1


def test_store_sent_manifest_roundtrip():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    store = RagStore(conn)
    log_id = store.insert_retrieval_log(
        account_wxid="wxid_a",
        conversation_id=1,
        query_text="q",
        fact_ids=[10],
        request_id="req-1",
        entrypoint="manual",
        excluded_reasons=[{"kind": "retrieval_item", "id": 9, "reason": "evidence_redacted_unusable"}],
    )
    store.conn.commit()
    store.update_retrieval_log_sent_manifest(
        log_id,
        {
            "request_id": "req-1",
            "entrypoint": "manual",
            "task": "invitation_planning",
            "output": "answer_with_speeches",
            "blocks": ["relationship_policy", "retrieval_memory"],
            "fact_ids": [10],
            "document_ids": [10],
            "policy_ids": [42],
            "contact_preference_ids": [7],
            "excluded": [{"id": 11, "reason": "prompt_budget_or_not_rendered"}],
            "prompt_chars": 1234,
            "prompt_hash": "a" * 64,
        },
    )
    row = conn.execute(
        "SELECT request_id, entrypoint, sent_manifest_json, final_prompt_hash, "
        "excluded_reasons_json, final_prompt_snapshot FROM rag_retrieval_logs WHERE id = ?",
        (log_id,),
    ).fetchone()
    assert row["request_id"] == "req-1"
    assert row["entrypoint"] == "manual"
    assert row["final_prompt_hash"] == "a" * 64
    assert row["final_prompt_snapshot"] is None  # 诊断关闭时不落快照
    import json

    manifest = json.loads(row["sent_manifest_json"])
    assert manifest["fact_ids"] == [10]
    assert manifest["policy_ids"] == [42]
    excluded = json.loads(row["excluded_reasons_json"])
    assert any(entry.get("reason") == "prompt_budget_or_not_rendered" for entry in excluded)


def test_persist_sent_manifest_writes_through(monkeypatch):
    import json as _json

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    store = RagStore(conn)
    log_id = store.insert_retrieval_log(account_wxid="wxid_a", conversation_id=1, query_text="q")
    store.conn.commit()
    monkeypatch.setattr("app.db.connection.get_db", lambda: conn)

    context = {
        "_rag_log_id": log_id,
        "_rag_sent_manifest": {
            "request_id": "req-2",
            "blocks": ["retrieval_memory"],
            "fact_ids": [5],
            "document_ids": [5],
            "prompt_hash": "b" * 64,
        },
    }
    engine = _engine()
    engine._persist_sent_manifest(context)
    row = conn.execute(
        "SELECT final_prompt_hash, sent_manifest_json FROM rag_retrieval_logs WHERE id = ?",
        (log_id,),
    ).fetchone()
    assert row["final_prompt_hash"] == "b" * 64
    assert _json.loads(row["sent_manifest_json"])["fact_ids"] == [5]
