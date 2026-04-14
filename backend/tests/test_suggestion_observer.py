"""Tests for suggestion observation analytics."""

import os
import sqlite3
import sys


sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.realtime.suggestion_observer import (
    EVENT_ADOPTED,
    EVENT_DISMISSED,
    EVENT_IGNORED,
    EVENT_SHOWN,
    ensure_observation_table,
    get_suggestion_metrics,
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


def test_get_suggestion_metrics_uses_latest_terminal_outcome():
    conn = _setup_db()
    suggestions = [
        (1, "batch-1", "negative_streak", 1000),
        (2, "batch-2", "topic_cooling", 1010),
        (3, "batch-3", "positive_window", 1020),
    ]
    for suggestion_id, batch_id, trigger_type, created_at in suggestions:
        conn.execute(
            """
            INSERT INTO realtime_suggestions (id, account_wxid, batch_id, trigger_type, speeches, status, created_at)
            VALUES (?, 'wxid_test', ?, ?, '[]', 'pending', ?)
            """,
            (suggestion_id, batch_id, trigger_type, created_at),
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
    mark_suggestion_viewed(conn, 1, account_wxid="wxid_test", created_at=1001)
    record_observation(
        conn,
        suggestion_id=1,
        account_wxid="wxid_test",
        event_type=EVENT_IGNORED,
        created_at=1002,
    )
    record_observation(
        conn,
        suggestion_id=1,
        account_wxid="wxid_test",
        event_type=EVENT_ADOPTED,
        similarity=0.93,
        selected_speech="测试话术",
        actual_message="测试话术",
        actual_message_type="text",
        created_at=1003,
    )

    record_observation(
        conn,
        suggestion_id=2,
        account_wxid="wxid_test",
        event_type=EVENT_SHOWN,
        batch_id="batch-2",
        display_name="妈",
        trigger_type="topic_cooling",
        created_at=1010,
    )
    record_observation(
        conn,
        suggestion_id=2,
        account_wxid="wxid_test",
        event_type=EVENT_DISMISSED,
        created_at=1015,
    )

    record_observation(
        conn,
        suggestion_id=3,
        account_wxid="wxid_test",
        event_type=EVENT_SHOWN,
        batch_id="batch-3",
        display_name="阿澄",
        trigger_type="positive_window",
        created_at=1020,
    )

    metrics = get_suggestion_metrics(
        conn,
        days=7,
        account_wxid="wxid_test",
        ignored_after_seconds=60,
        now_ts=1200,
    )

    assert metrics["shown_count"] == 3
    assert metrics["viewed_count"] == 1
    assert metrics["adopted_count"] == 1
    assert metrics["dismissed_count"] == 1
    assert metrics["ignored_count"] == 1
    assert metrics["adoption_rate"] == 0.333
    assert metrics["by_trigger_type"][0]["shown_count"] >= 1
    by_display = {item["display_name"]: item for item in metrics["by_display_name"]}
    assert by_display["阿澄"]["adopted_count"] == 1
    assert by_display["阿澄"]["ignored_count"] == 1
