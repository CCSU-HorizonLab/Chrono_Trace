"""Tests for suggestion observation analytics."""

import os
import sqlite3
import sys


sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.realtime.suggestion_observer import (
    EVENT_SHOWN,
    ensure_observation_table,
    mark_suggestion_viewed,
    record_observation,
)


def _setup_db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE realtime_suggestions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            account_wxid TEXT NOT NULL,
            batch_id TEXT NOT NULL,
            trigger_type TEXT NOT NULL,
            speeches TEXT NOT NULL,
            status TEXT DEFAULT 'pending',
            created_at INTEGER NOT NULL,
            read_at INTEGER,
            dismissed_at INTEGER
        )
        """
    )
    ensure_observation_table(conn)
    return conn


def test_mark_suggestion_viewed_sets_read_at_and_reuses_shown_context():
    conn = _setup_db()
    conn.execute(
        """
        INSERT INTO realtime_suggestions (id, account_wxid, batch_id, trigger_type, speeches, status, created_at)
        VALUES (1, 'wxid_test', 'batch-1', 'negative_streak', '[]', 'pending', 1000)
        """
    )
    record_observation(
        conn,
        suggestion_id=1,
        account_wxid="wxid_test",
        event_type=EVENT_SHOWN,
        batch_id="batch-1",
        display_name="阿澄",
        trigger_type="negative_streak",
        created_at=1000,
    )

    mark_suggestion_viewed(conn, 1, account_wxid="wxid_test", created_at=1010)
    conn.commit()

    read_row = conn.execute("SELECT read_at FROM realtime_suggestions WHERE id = 1").fetchone()
    viewed_row = conn.execute(
        """
        SELECT display_name, trigger_type, event_type
        FROM suggestion_observations
        WHERE suggestion_id = 1 AND event_type = 'viewed'
        """
    ).fetchone()

    assert read_row["read_at"] == 1010
    assert viewed_row["display_name"] == "阿澄"
    assert viewed_row["trigger_type"] == "negative_streak"
    assert viewed_row["event_type"] == "viewed"
