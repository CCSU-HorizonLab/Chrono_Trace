"""Tests for realtime message buffer persistence."""

import os
import sqlite3
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.realtime.message_buffer import MessageBuffer


def _make_db():
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
    conn.commit()
    return conn


def test_save_message_persists_batch_id(monkeypatch):
    conn = _make_db()
    monkeypatch.setattr("app.services.realtime.message_buffer.get_db", lambda: conn)

    buffer = MessageBuffer()

    ok = buffer.save_message(
        batch_id="batch-42",
        account_wxid="wxid_test",
        talker_username="friend_user",
        talker_display_name="Friend",
        message_data={
            "message_hash": "hash-1",
            "runtime_id": "runtime-1",
            "sender_attr": "friend",
            "content": "hello",
            "message_type": "text",
            "timestamp": 1234567890,
            "visible_index": 7,
        },
    )

    assert ok is True

    row = conn.execute(
        """
        SELECT account_wxid, talker_username, talker_display_name, message_hash,
               runtime_id, sender_attr, content, message_type, timestamp,
               visible_index, batch_id, is_processed
        FROM realtime_message_buffer
        """
    ).fetchone()

    assert row is not None
    assert row["account_wxid"] == "wxid_test"
    assert row["talker_username"] == "friend_user"
    assert row["talker_display_name"] == "Friend"
    assert row["message_hash"] == "hash-1"
    assert row["runtime_id"] == "runtime-1"
    assert row["sender_attr"] == "friend"
    assert row["content"] == "hello"
    assert row["message_type"] == "text"
    assert row["timestamp"] == 1234567890
    assert row["visible_index"] == 7
    assert row["batch_id"] == "batch-42"
    assert row["is_processed"] == 0
