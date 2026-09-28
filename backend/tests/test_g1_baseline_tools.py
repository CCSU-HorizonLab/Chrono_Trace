"""G0/G7 基线工具测试:装载器抽取、回放链路路由差异、转账模式兜底。"""

import os
import sqlite3
import sys
import tempfile
from pathlib import Path


sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.realtime.recent_window import (
    KIND_HUMAN_CHAT,
    KIND_TRANSFER_EVENT,
    classify_message_kind,
)
from backend.scripts.g1_baseline_loader import (
    DIMENSIONS,
    _auto_expected,
    _legacy_classify,
    load_samples,
)
from backend.scripts.g1_baseline_replay import (
    _legacy_two_way,
    build_recent_messages,
    inject_ambiguous_twin,
    legacy_routing,
)


def _msg(sender: str, content: str, **extra):
    return {"sender_attr": sender, "content": content, "message_type": "text", **extra}


def test_real_transfer_bubble_wording_classified_as_event():
    """真实缓冲区措辞:"￥42.50 已被接收 微信转账"不得算人工聊天。"""
    assert classify_message_kind(_msg("friend", "￥42.50 已被接收 微信转账")) == KIND_TRANSFER_EVENT
    assert classify_message_kind(_msg("self", "￥40.00 已收款 微信转账")) == KIND_TRANSFER_EVENT
    assert classify_message_kind(_msg("friend", "￥88.00 微信红包存入零钱")) == KIND_TRANSFER_EVENT
    # 正常文字提及转账仍是聊天
    assert classify_message_kind(_msg("self", "上次说的转账的事别忘了哈")) == KIND_HUMAN_CHAT


def test_legacy_two_way_reproduces_old_classification():
    invitation = {"user_context": [{"role": "user", "content": "我想约她打游戏"}]}
    advice = {"user_context": [{"role": "user", "content": "这句怎么回比较好"}]}
    assert _legacy_two_way(invitation) == "direct_reply"  # 旧链路的误判实证
    assert _legacy_two_way(advice) == "advice_request"
    assert _legacy_classify([{"role": "user", "content": "我想约她打游戏"}]) == "direct_reply"


def test_legacy_routing_suppresses_knowledge_for_direct_reply():
    invitation = {"user_context": [{"role": "user", "content": "我想约她打游戏"}]}
    routing = legacy_routing(None, invitation)
    assert routing["reason"] == "legacy_direct_reply"
    assert routing["knowledge_needs"] == []
    assert routing["output"] == "direct_answer"

    advice_routing = legacy_routing(None, {"user_context": [{"role": "user", "content": "怎么回她"}]})
    assert advice_routing["reason"] == "legacy_advice_request"
    assert advice_routing["knowledge_needs"]  # 旧链路建议任务注入全部知识


def test_g1_routing_differs_from_legacy_on_target_example():
    from app.services.realtime.task_router import route_generation_task

    context = {"user_context": [{"role": "user", "content": "我想约她打游戏"}]}
    g1 = route_generation_task(context, "manual_request")
    legacy = legacy_routing(None, context)
    assert g1.task == "invitation_planning"
    assert g1.wants_speeches is True
    assert legacy["output"] == "direct_answer"  # 三路对照的差异锚点


def test_auto_expected_marks_scopeless_safety():
    expected = _auto_expected(
        [{"role": "user", "content": "怎么回她"}],
        {"dimension": "missing_scope_degrade", "requires_ambiguous_twin": False},
    )
    assert expected["scope"] == "missing_or_ambiguous"
    assert any("不得注入" in rule for rule in expected["safety"])


def _fixture_db(path: Path) -> None:
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE conversations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            account_wxid TEXT, display_name TEXT, username TEXT,
            is_deleted INTEGER DEFAULT 0, message_count INTEGER DEFAULT 0,
            platform TEXT DEFAULT 'wechat', created_at INTEGER, updated_at INTEGER
        );
        CREATE TABLE messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT, conversation_id INTEGER, local_id INTEGER,
            talker TEXT, sender TEXT, is_sender INTEGER, message_type TEXT,
            content TEXT, media_path TEXT, timestamp INTEGER, source TEXT, emotion TEXT, created_at INTEGER
        );
        CREATE TABLE rag_facts (
            id INTEGER PRIMARY KEY AUTOINCREMENT, account_wxid TEXT, conversation_id INTEGER,
            subject TEXT, kind TEXT, content TEXT, status TEXT DEFAULT 'active',
            as_of INTEGER, valid_from INTEGER, valid_to INTEGER, confidence REAL,
            sensitivity TEXT, enabled INTEGER, evidence_message_ids_json TEXT,
            source_window_json TEXT, summary_method TEXT, supersedes_fact_id INTEGER,
            created_at INTEGER, updated_at INTEGER
        );
        CREATE TABLE rag_retrieval_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT, account_wxid TEXT, conversation_id INTEGER,
            suggestion_id INTEGER, query_text TEXT, document_ids_json TEXT,
            retrieval_scores_json TEXT, created_at INTEGER
        );
        CREATE TABLE realtime_suggestions (
            id INTEGER PRIMARY KEY AUTOINCREMENT, account_wxid TEXT, batch_id TEXT,
            trigger_type TEXT, intent TEXT, severity TEXT, summary TEXT, speeches TEXT,
            confidence REAL, status TEXT, engine_type TEXT, trigger_context TEXT,
            created_at INTEGER
        );
        CREATE TABLE llm_models (
            id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, provider TEXT, model_id TEXT,
            api_base_url TEXT, api_key TEXT, is_active INTEGER, created_at INTEGER, updated_at INTEGER
        );
        """
    )
    conn.execute(
        "INSERT INTO conversations (account_wxid, display_name, username, created_at, updated_at) "
        "VALUES ('wxid_a', '测试联系人', 'wxid_contact', 1, 1)"
    )
    conn.executemany(
        "INSERT INTO messages (conversation_id, is_sender, message_type, content, timestamp) VALUES (1, ?, ?, ?, ?)",
        [
            (0, "text", "在吗", 100),
            (1, "text", "在的", 101),
            (0, "10000", "对方撤回了一条消息", 102),
        ],
    )
    conn.executemany(
        "INSERT INTO rag_facts (account_wxid, conversation_id, subject, kind, content, status) VALUES (?, 1, ?, ?, ?, 'active')",
        [
            ("wxid_a", "共同", "hobby_or_game", "我们一起玩过主机游戏"),
            ("wxid_a", "对方", "preference", "对方喜欢喝奶茶"),
        ],
    )
    conn.execute(
        "INSERT INTO rag_retrieval_logs (account_wxid, conversation_id, query_text, document_ids_json, created_at) "
        "VALUES ('wxid_a', 1, '我们玩过什么游戏', '[]', 1000)"
    )
    conn.execute(
        "INSERT INTO realtime_suggestions (account_wxid, batch_id, trigger_type, summary, speeches, trigger_context, created_at) "
        "VALUES ('wxid_a', 'b1', 'manual_request', '[PURE_CHAT]', '[]', "
        "'{\"user_context\": [{\"role\": \"user\", \"content\": \"我们玩过什么游戏\"}]}', 1010)"
    )
    conn.execute("INSERT INTO llm_models (name, provider, model_id, api_base_url, is_active) VALUES ('t', 'ollama', 'm', 'http://127.0.0.1', 1)")
    conn.commit()
    conn.close()


def test_loader_produces_covered_samples_from_fixture():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "fixture.db"
        _fixture_db(db_path)
        payload = load_samples(str(db_path))

    samples = payload["samples"]
    meta = payload["meta"]
    assert meta["sample_count"] == len(samples)
    for dim in DIMENSIONS:
        assert meta["dimension_coverage"].get(dim, 0) >= 1, f"维度未覆盖: {dim}"

    real = [s for s in samples if s["source"] == "real_log"]
    assert real, "真实日志样例未被抽取"
    assert real[0]["baseline"]["retrieval_log_id"] == 1
    assert real[0]["baseline"]["legacy_task"] == "direct_reply"
    assert real[0]["baseline"]["suggestion_summary"] == "[PURE_CHAT]"

    ambiguous = [s for s in samples if s.get("requires_ambiguous_twin")]
    assert ambiguous and ambiguous[0]["conversation_id"] is None
    assert ambiguous[0]["expected"]["scope"] == "missing_or_ambiguous"

    scopeless = [s for s in samples if s["dimension"] == "missing_scope_degrade"]
    assert scopeless and all(s.get("conversation_id") is None for s in scopeless)

    assert meta["active_model"]["model_id"] == "m"
    assert meta["db"]["conversations"] == 1


def test_build_recent_messages_maps_senders():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        "CREATE TABLE messages (id INTEGER PRIMARY KEY AUTOINCREMENT, conversation_id INTEGER, "
        "talker TEXT, is_sender INTEGER, message_type TEXT, content TEXT, timestamp INTEGER)"
    )
    conn.executemany(
        "INSERT INTO messages (conversation_id, is_sender, message_type, content, timestamp) VALUES (5, ?, ?, ?, ?)",
        [(0, "text", "早", 1), (1, "text", "早呀", 2), (0, "10000", "撤回", 3)],
    )
    conn.commit()
    messages = build_recent_messages(conn, 5)
    assert [m["sender_attr"] for m in messages] == ["friend", "self", "system"]
    assert [m["content"] for m in messages] == ["早", "早呀", "撤回"]


def test_inject_ambiguous_twin_creates_same_name_contact():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        "CREATE TABLE conversations (id INTEGER PRIMARY KEY AUTOINCREMENT, account_wxid TEXT, "
        "display_name TEXT, username TEXT, is_deleted INTEGER, updated_at INTEGER, created_at INTEGER)"
    )
    conn.execute(
        "INSERT INTO conversations (account_wxid, display_name, username, is_deleted, created_at, updated_at) "
        "VALUES ('wxid_a', '同名', 'wxid_real', 0, 1, 1)"
    )
    conn.commit()
    sample = {"account_wxid": "wxid_a", "display_name": "同名"}
    inject_ambiguous_twin(conn, sample, "g1")
    rows = conn.execute(
        "SELECT username FROM conversations WHERE account_wxid='wxid_a' AND display_name='同名'"
    ).fetchall()
    assert len(rows) == 2
