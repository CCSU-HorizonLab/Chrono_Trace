import json
import os
import sqlite3
import sys


sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.realtime.message_query import get_messages_with_sentiment
from app.services.realtime.session_thread_service import SessionThreadService
from app.webview.bridge import Bridge


def _setup_conn():
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE realtime_message_buffer (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            account_wxid TEXT NOT NULL,
            talker_username TEXT NOT NULL,
            talker_display_name TEXT NOT NULL,
            message_hash TEXT,
            runtime_id TEXT,
            sender_attr TEXT NOT NULL,
            content TEXT,
            message_type TEXT,
            timestamp INTEGER NOT NULL,
            captured_at INTEGER NOT NULL,
            visible_index INTEGER DEFAULT -1,
            batch_id TEXT,
            is_processed INTEGER DEFAULT 0,
            created_at INTEGER NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE realtime_suggestions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            account_wxid TEXT NOT NULL,
            batch_id TEXT NOT NULL,
            trigger_type TEXT NOT NULL,
            intent TEXT NOT NULL,
            severity TEXT DEFAULT 'medium',
            summary TEXT NOT NULL,
            speeches TEXT NOT NULL,
            confidence REAL DEFAULT 1.0,
            status TEXT DEFAULT 'pending',
            engine_type TEXT DEFAULT 'llm',
            trigger_context TEXT,
            created_at INTEGER NOT NULL,
            read_at INTEGER,
            dismissed_at INTEGER,
            reply TEXT,
            thought_process TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE suggestion_observations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            account_wxid TEXT NOT NULL,
            suggestion_id INTEGER NOT NULL,
            batch_id TEXT,
            display_name TEXT,
            trigger_type TEXT,
            event_type TEXT NOT NULL,
            similarity REAL,
            selected_speech TEXT,
            actual_message TEXT,
            actual_message_type TEXT,
            metadata_json TEXT,
            created_at INTEGER NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE session_threads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            account_wxid TEXT NOT NULL,
            batch_id TEXT NOT NULL,
            display_name TEXT NOT NULL,
            summary TEXT NOT NULL,
            keywords TEXT,
            messages_snapshot TEXT,
            suggestions_snapshot TEXT,
            user_chat_history_snapshot TEXT,
            message_count INTEGER,
            suggestion_count INTEGER,
            created_at INTEGER NOT NULL,
            duration_seconds INTEGER
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE realtime_sentiment_cache (
            message_id TEXT PRIMARY KEY,
            polarity TEXT,
            intensity REAL,
            confidence REAL,
            rules_applied TEXT
        )
        """
    )
    conn.commit()
    return conn


def test_get_messages_with_sentiment_filters_by_account(monkeypatch):
    conn = _setup_conn()
    conn.execute(
        """
        INSERT INTO realtime_message_buffer
        (account_wxid, talker_username, talker_display_name, message_hash, runtime_id, sender_attr,
         content, message_type, timestamp, captured_at, visible_index, batch_id, is_processed, created_at)
        VALUES
        ('wxid_a', 'friend', 'Friend', 'hash-a', 'runtime-a', 'friend', 'A', 'text', 1, 1, 0, 'batch-shared', 0, 1),
        ('wxid_b', 'friend', 'Friend', 'hash-b', 'runtime-b', 'friend', 'B', 'text', 2, 2, 1, 'batch-shared', 0, 2)
        """
    )
    conn.commit()

    monkeypatch.setattr("app.services.realtime.message_query.get_db", lambda: conn)

    messages = get_messages_with_sentiment("batch-shared", limit=10, account_wxid="wxid_a")

    assert [item["content"] for item in messages] == ["A"]


def test_load_thread_context_filters_by_account(monkeypatch):
    conn = _setup_conn()
    conn.execute(
        """
        INSERT INTO session_threads
        (id, account_wxid, batch_id, display_name, summary, keywords, messages_snapshot,
         suggestions_snapshot, user_chat_history_snapshot, message_count, suggestion_count, created_at, duration_seconds)
        VALUES (1, 'wxid_other', 'batch-1', 'Friend', 'summary', '', '[]', '[]', '[]', 1, 0, 1, 10)
        """
    )
    conn.commit()

    monkeypatch.setattr("app.db.connection.get_db", lambda: conn)

    service = SessionThreadService()

    assert service.load_thread_context(1, account_wxid="wxid_self") is None

    ctx = service.load_thread_context(1, account_wxid="wxid_other")
    assert ctx is not None
    assert ctx["account_wxid"] == "wxid_other"


def test_bridge_dismiss_suggestion_does_not_modify_other_account(monkeypatch):
    conn = _setup_conn()
    conn.execute(
        """
        INSERT INTO realtime_suggestions
        (id, account_wxid, batch_id, trigger_type, intent, severity, summary, speeches, confidence, status, created_at)
        VALUES (7, 'wxid_other', 'batch-1', 'topic_cooling', 'maintain', 'medium', '测试建议', ?, 0.9, 'pending', 1000)
        """,
        (json.dumps(["测试话术"], ensure_ascii=False),),
    )
    conn.commit()

    monkeypatch.setattr("app.db.connection.get_db", lambda: conn)

    bridge = Bridge.__new__(Bridge)
    bridge.settings = {"wechat_user_wxid": "wxid_self"}

    result = bridge.dismiss_suggestion(7)

    assert result["ok"] is False
    assert result["error"] == "suggestion_not_found"

    row = conn.execute(
        "SELECT status, dismissed_at FROM realtime_suggestions WHERE id = 7"
    ).fetchone()
    assert row["status"] == "pending"
    assert row["dismissed_at"] is None
    event_count = conn.execute(
        "SELECT COUNT(*) FROM suggestion_observations WHERE suggestion_id = 7 AND event_type = 'dismissed'"
    ).fetchone()[0]
    assert event_count == 0
