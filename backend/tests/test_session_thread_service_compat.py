import os
import sqlite3
import sys


sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import app.db.connection as db_mod
import app.services.realtime.session_thread_service as sts_mod
from app.services.realtime.session_thread_service import SessionThreadService


def test_archive_thread_adds_missing_user_chat_history_snapshot_column(monkeypatch):
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
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
            message_count INTEGER,
            suggestion_count INTEGER,
            created_at INTEGER NOT NULL,
            duration_seconds INTEGER
        )
        """
    )
    conn.commit()

    monkeypatch.setattr(db_mod, "get_db", lambda: conn)
    monkeypatch.setattr(sts_mod, "_print", lambda _msg: None)

    service = SessionThreadService()
    monkeypatch.setattr(
        service,
        "_generate_summary",
        lambda messages, suggestions: {"summary": "测试总结", "keywords": "测试"},
    )

    thread_id = service.archive_thread(
        batch_id="batch-compat",
        display_name="Friend",
        messages=[{"content": "hi", "sender_attr": "friend", "message_type": "text", "timestamp": 1}],
        suggestions=[],
        start_time=1,
        user_chat_history=[{"role": "user", "content": "hello"}],
        account_wxid="wxid_test",
    )

    assert thread_id is not None

    columns = {
        str(row["name"])
        for row in conn.execute("PRAGMA table_info(session_threads)").fetchall()
    }
    assert "user_chat_history_snapshot" in columns

    row = conn.execute(
        """
        SELECT account_wxid, batch_id, display_name, user_chat_history_snapshot
        FROM session_threads
        WHERE id = ?
        """,
        (thread_id,),
    ).fetchone()
    assert row is not None
    assert row["account_wxid"] == "wxid_test"
    assert row["batch_id"] == "batch-compat"
    assert row["display_name"] == "Friend"
    assert row["user_chat_history_snapshot"] is not None
