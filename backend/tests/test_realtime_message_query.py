"""Tests for realtime message query dedupe before LLM consumption."""

import json
import os
import sqlite3
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.realtime.message_query import get_messages_with_sentiment


def _make_db():
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE realtime_message_buffer (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
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
            is_processed INTEGER DEFAULT 0,
            batch_id TEXT,
            created_at INTEGER NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE realtime_sentiment_cache (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            message_id TEXT NOT NULL UNIQUE,
            polarity INTEGER,
            intensity REAL,
            confidence REAL,
            rules_applied TEXT
        )
        """
    )
    conn.commit()
    return conn


def test_get_messages_with_sentiment_dedupes_same_sender_recaptures(monkeypatch):
    conn = _make_db()
    monkeypatch.setattr("app.services.realtime.message_query.get_db", lambda: conn)

    conn.execute(
        """
        INSERT INTO realtime_message_buffer (
            talker_username, talker_display_name, message_hash, runtime_id,
            sender_attr, content, message_type, timestamp, captured_at, visible_index, batch_id, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "friend_user",
            "Friend",
            "hash-early",
            "runtime-42",
            "friend",
            "就拽就拽",
            "text",
            200,
            200,
            5,
            "batch-1",
            200,
        ),
    )
    conn.execute(
        """
        INSERT INTO realtime_message_buffer (
            talker_username, talker_display_name, message_hash, runtime_id,
            sender_attr, content, message_type, timestamp, captured_at, visible_index, batch_id, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "friend_user",
            "Friend",
            "hash-late",
            "runtime-99",
            "friend",
            "就拽就拽",
            "text",
            200,
            228,
            5,
            "batch-1",
            228,
        ),
    )
    conn.execute(
        """
        INSERT INTO realtime_sentiment_cache (
            message_id, polarity, intensity, confidence, rules_applied
        ) VALUES (?, ?, ?, ?, ?)
        """,
        ("hash-early", -1, -0.8, 0.9, json.dumps(["mock"], ensure_ascii=False)),
    )
    conn.commit()

    messages = get_messages_with_sentiment("batch-1", limit=10)

    assert len(messages) == 1
    assert messages[0]["runtime_id"] == "runtime-42"
    assert messages[0]["sender_attr"] == "friend"
    assert messages[0]["message_hash"] == "hash-early"
    assert messages[0]["sentiment"]["polarity"] == -1


def test_get_messages_with_sentiment_preserves_same_timestamp_visible_order(monkeypatch):
    conn = _make_db()
    monkeypatch.setattr("app.services.realtime.message_query.get_db", lambda: conn)

    rows = [
        ("hash-1", "runtime-1", "self", "应该是修好了", 1743078480, 10, 3, 310),
        ("hash-2", "runtime-2", "friend", "行", 1743078480, 11, 4, 311),
        ("hash-3", "runtime-3", "friend", "你是指什么时候", 1743078480, 12, 6, 312),
        ("hash-4", "runtime-4", "self", "今天晚上", 1743078480, 13, 7, 313),
    ]
    for message_hash, runtime_id, sender_attr, content, timestamp, captured_at, visible_index, created_at in reversed(rows):
        conn.execute(
            """
            INSERT INTO realtime_message_buffer (
                talker_username, talker_display_name, message_hash, runtime_id,
                sender_attr, content, message_type, timestamp, captured_at, visible_index, batch_id, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "friend_user",
                "Friend",
                message_hash,
                runtime_id,
                sender_attr,
                content,
                "text",
                timestamp,
                captured_at,
                visible_index,
                "batch-1",
                created_at,
            ),
        )
    conn.commit()

    messages = get_messages_with_sentiment("batch-1", limit=10, order_desc=False)

    assert [msg["content"] for msg in messages] == [
        "应该是修好了",
        "行",
        "你是指什么时候",
        "今天晚上",
    ]
