"""Suggestion observation helpers for analytics and feedback loops."""

from __future__ import annotations

import json
import time
from typing import Any
from ..wechat.account_settings import get_active_wechat_account_wxid, load_settings_from_file


EVENT_SHOWN = "shown"
EVENT_VIEWED = "viewed"
EVENT_DISMISSED = "dismissed"
EVENT_ADOPTED = "adopted"
EVENT_REWRITTEN = "rewritten"
EVENT_IGNORED = "ignored"

TERMINAL_EVENT_TYPES = (
    EVENT_DISMISSED,
    EVENT_ADOPTED,
    EVENT_REWRITTEN,
    EVENT_IGNORED,
)
SINGLETON_EVENT_TYPES = {
    EVENT_SHOWN,
    EVENT_VIEWED,
    EVENT_DISMISSED,
    EVENT_ADOPTED,
    EVENT_REWRITTEN,
    EVENT_IGNORED,
}
DEFAULT_IGNORED_AFTER_SECONDS = 900


def _resolve_account_wxid(account_wxid: str | None = None) -> str:
    normalized = str(account_wxid or "").strip()
    if normalized:
        return normalized
    try:
        return get_active_wechat_account_wxid(load_settings_from_file())
    except Exception:
        return ""


def ensure_observation_table(conn) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS suggestion_observations (
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
        CREATE UNIQUE INDEX IF NOT EXISTS idx_suggestion_observations_singleton
        ON suggestion_observations(suggestion_id, event_type)
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_suggestion_observations_event_created
        ON suggestion_observations(event_type, created_at DESC)
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_suggestion_observations_account_display
        ON suggestion_observations(account_wxid, display_name, created_at DESC)
        """
    )


def _resolve_event_context(conn, suggestion_id: int) -> dict[str, Any]:
    ensure_observation_table(conn)
    shown_row = conn.execute(
        """
        SELECT account_wxid, batch_id, display_name, trigger_type
        FROM suggestion_observations
        WHERE suggestion_id = ? AND event_type = ?
        LIMIT 1
        """,
        (suggestion_id, EVENT_SHOWN),
    ).fetchone()
    if shown_row:
        return {
            "account_wxid": shown_row["account_wxid"],
            "batch_id": shown_row["batch_id"],
            "display_name": shown_row["display_name"],
            "trigger_type": shown_row["trigger_type"],
        }

    suggestion_row = conn.execute(
        """
        SELECT account_wxid, batch_id, trigger_type
        FROM realtime_suggestions
        WHERE id = ?
        LIMIT 1
        """,
        (suggestion_id,),
    ).fetchone()
    if suggestion_row:
        return {
            "account_wxid": suggestion_row["account_wxid"],
            "batch_id": suggestion_row["batch_id"],
            "display_name": None,
            "trigger_type": suggestion_row["trigger_type"],
        }
    return {
        "account_wxid": _resolve_account_wxid(),
        "batch_id": None,
        "display_name": None,
        "trigger_type": None,
    }


def record_observation(
    conn,
    *,
    suggestion_id: int,
    account_wxid: str | None = None,
    event_type: str,
    batch_id: str | None = None,
    display_name: str | None = None,
    trigger_type: str | None = None,
    similarity: float | None = None,
    selected_speech: str | None = None,
    actual_message: str | None = None,
    actual_message_type: str | int | None = None,
    metadata: dict[str, Any] | None = None,
    created_at: int | None = None,
) -> None:
    ensure_observation_table(conn)
    base_context = _resolve_event_context(conn, suggestion_id)
    payload = {
        "suggestion_id": int(suggestion_id),
        "account_wxid": _resolve_account_wxid(account_wxid if account_wxid is not None else base_context.get("account_wxid")),
        "batch_id": batch_id if batch_id is not None else base_context.get("batch_id"),
        "display_name": display_name if display_name is not None else base_context.get("display_name"),
        "trigger_type": trigger_type if trigger_type is not None else base_context.get("trigger_type"),
        "event_type": event_type,
        "similarity": similarity,
        "selected_speech": selected_speech,
        "actual_message": actual_message,
        "actual_message_type": None if actual_message_type is None else str(actual_message_type),
        "metadata_json": json.dumps(metadata, ensure_ascii=False) if metadata else None,
        "created_at": int(created_at or time.time()),
    }

    if event_type in SINGLETON_EVENT_TYPES:
        conn.execute(
            """
            INSERT OR IGNORE INTO suggestion_observations
            (account_wxid, suggestion_id, batch_id, display_name, trigger_type, event_type,
             similarity, selected_speech, actual_message, actual_message_type,
             metadata_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                payload["account_wxid"],
                payload["suggestion_id"],
                payload["batch_id"],
                payload["display_name"],
                payload["trigger_type"],
                payload["event_type"],
                payload["similarity"],
                payload["selected_speech"],
                payload["actual_message"],
                payload["actual_message_type"],
                payload["metadata_json"],
                payload["created_at"],
            ),
        )
        return

    conn.execute(
        """
        INSERT INTO suggestion_observations
        (account_wxid, suggestion_id, batch_id, display_name, trigger_type, event_type,
         similarity, selected_speech, actual_message, actual_message_type,
         metadata_json, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            payload["account_wxid"],
            payload["suggestion_id"],
            payload["batch_id"],
            payload["display_name"],
            payload["trigger_type"],
            payload["event_type"],
            payload["similarity"],
            payload["selected_speech"],
            payload["actual_message"],
            payload["actual_message_type"],
            payload["metadata_json"],
            payload["created_at"],
        ),
    )


def mark_suggestion_viewed(
    conn,
    suggestion_id: int,
    *,
    account_wxid: str | None = None,
    batch_id: str | None = None,
    display_name: str | None = None,
    trigger_type: str | None = None,
    created_at: int | None = None,
) -> None:
    ts = int(created_at or time.time())
    conn.execute(
        """
        UPDATE realtime_suggestions
        SET read_at = COALESCE(read_at, ?)
        WHERE id = ?
        """,
        (ts, suggestion_id),
    )
    record_observation(
        conn,
        suggestion_id=suggestion_id,
        account_wxid=account_wxid,
        event_type=EVENT_VIEWED,
        batch_id=batch_id,
        display_name=display_name,
        trigger_type=trigger_type,
        created_at=ts,
    )


def sweep_ignored_suggestions(
    conn,
    *,
    account_wxid: str | None = None,
    older_than_seconds: int = DEFAULT_IGNORED_AFTER_SECONDS,
    now_ts: int | None = None,
) -> int:
    ensure_observation_table(conn)
    ref_now = int(now_ts or time.time())
    cutoff = ref_now - int(older_than_seconds)
    resolved_account_wxid = _resolve_account_wxid(account_wxid)

    rows = conn.execute(
        f"""
        SELECT s.id, shown.account_wxid, shown.batch_id, shown.display_name, shown.trigger_type
        FROM realtime_suggestions s
        INNER JOIN suggestion_observations shown
          ON shown.suggestion_id = s.id AND shown.event_type = ?
        LEFT JOIN (
            SELECT suggestion_id, MAX(created_at) AS latest_terminal_at
            FROM suggestion_observations
            WHERE event_type IN ({",".join("?" for _ in TERMINAL_EVENT_TYPES)})
            GROUP BY suggestion_id
        ) terminal
          ON terminal.suggestion_id = s.id
        WHERE s.account_wxid = ?
          AND s.created_at <= ?
          AND s.status NOT IN ('feedback_processing', 'dismissed')
          AND s.dismissed_at IS NULL
          AND terminal.suggestion_id IS NULL
        """,
        (EVENT_SHOWN, *TERMINAL_EVENT_TYPES, resolved_account_wxid, cutoff),
    ).fetchall()

    for row in rows:
        record_observation(
            conn,
            suggestion_id=row["id"],
            account_wxid=row["account_wxid"],
            event_type=EVENT_IGNORED,
            batch_id=row["batch_id"],
            display_name=row["display_name"],
            trigger_type=row["trigger_type"],
            created_at=ref_now,
        )
    return len(rows)


def _build_group_metrics(items: list[dict[str, Any]], key: str) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    for item in items:
        group_key = str(item.get(key) or "unknown")
        summary = grouped.setdefault(
            group_key,
            {
                key: group_key,
                "shown_count": 0,
                "viewed_count": 0,
                "dismissed_count": 0,
                "adopted_count": 0,
                "rewritten_count": 0,
                "ignored_count": 0,
            },
        )
        summary["shown_count"] += 1
        if item.get("viewed"):
            summary["viewed_count"] += 1
        outcome = item.get("terminal_event")
        if outcome == EVENT_DISMISSED:
            summary["dismissed_count"] += 1
        elif outcome == EVENT_ADOPTED:
            summary["adopted_count"] += 1
        elif outcome == EVENT_REWRITTEN:
            summary["rewritten_count"] += 1
        elif outcome == EVENT_IGNORED:
            summary["ignored_count"] += 1

    results = list(grouped.values())
    for result in results:
        shown_count = max(1, result["shown_count"])
        result["view_rate"] = round(result["viewed_count"] / shown_count, 3)
        result["dismiss_rate"] = round(result["dismissed_count"] / shown_count, 3)
        result["adoption_rate"] = round(result["adopted_count"] / shown_count, 3)
        result["rewrite_rate"] = round(result["rewritten_count"] / shown_count, 3)
        result["ignored_rate"] = round(result["ignored_count"] / shown_count, 3)
    return sorted(results, key=lambda item: (-item["shown_count"], item[key]))


def get_suggestion_metrics(
    conn,
    *,
    account_wxid: str | None = None,
    days: int = 7,
    ignored_after_seconds: int = DEFAULT_IGNORED_AFTER_SECONDS,
    now_ts: int | None = None,
) -> dict[str, Any]:
    ensure_observation_table(conn)
    ref_now = int(now_ts or time.time())
    resolved_account_wxid = _resolve_account_wxid(account_wxid)
    sweep_ignored_suggestions(
        conn,
        account_wxid=resolved_account_wxid,
        older_than_seconds=ignored_after_seconds,
        now_ts=ref_now,
    )
    conn.commit()

    cutoff = ref_now - int(days * 86400)
    shown_rows = conn.execute(
        """
        SELECT suggestion_id, batch_id, display_name, trigger_type, created_at
        FROM suggestion_observations
        WHERE account_wxid = ? AND event_type = ? AND created_at >= ?
        ORDER BY created_at DESC
        """,
        (resolved_account_wxid, EVENT_SHOWN, cutoff),
    ).fetchall()

    suggestion_items = [
        {
            "suggestion_id": row["suggestion_id"],
            "batch_id": row["batch_id"],
            "display_name": row["display_name"],
            "trigger_type": row["trigger_type"],
            "shown_at": row["created_at"],
            "viewed": False,
            "terminal_event": None,
        }
        for row in shown_rows
    ]
    if not suggestion_items:
        return {
            "generated_at": ref_now,
            "days": int(days),
            "ignored_after_seconds": int(ignored_after_seconds),
            "shown_count": 0,
            "viewed_count": 0,
            "dismissed_count": 0,
            "adopted_count": 0,
            "rewritten_count": 0,
            "ignored_count": 0,
            "view_rate": 0.0,
            "dismiss_rate": 0.0,
            "adoption_rate": 0.0,
            "rewrite_rate": 0.0,
            "ignored_rate": 0.0,
            "by_trigger_type": [],
            "by_display_name": [],
        }

    by_id = {item["suggestion_id"]: item for item in suggestion_items}
    placeholders = ",".join("?" for _ in by_id)
    event_rows = conn.execute(
        f"""
        SELECT suggestion_id, event_type, created_at
        FROM suggestion_observations
        WHERE suggestion_id IN ({placeholders})
        ORDER BY created_at ASC, id ASC
        """,
        tuple(by_id.keys()),
    ).fetchall()

    for row in event_rows:
        item = by_id.get(row["suggestion_id"])
        if not item:
            continue
        event_type = row["event_type"]
        if event_type == EVENT_VIEWED:
            item["viewed"] = True
        elif event_type in TERMINAL_EVENT_TYPES:
            item["terminal_event"] = event_type

    shown_count = len(suggestion_items)
    viewed_count = sum(1 for item in suggestion_items if item["viewed"])
    dismissed_count = sum(1 for item in suggestion_items if item["terminal_event"] == EVENT_DISMISSED)
    adopted_count = sum(1 for item in suggestion_items if item["terminal_event"] == EVENT_ADOPTED)
    rewritten_count = sum(1 for item in suggestion_items if item["terminal_event"] == EVENT_REWRITTEN)
    ignored_count = sum(1 for item in suggestion_items if item["terminal_event"] == EVENT_IGNORED)

    return {
        "generated_at": ref_now,
        "days": int(days),
        "ignored_after_seconds": int(ignored_after_seconds),
        "shown_count": shown_count,
        "viewed_count": viewed_count,
        "dismissed_count": dismissed_count,
        "adopted_count": adopted_count,
        "rewritten_count": rewritten_count,
        "ignored_count": ignored_count,
        "view_rate": round(viewed_count / shown_count, 3),
        "dismiss_rate": round(dismissed_count / shown_count, 3),
        "adoption_rate": round(adopted_count / shown_count, 3),
        "rewrite_rate": round(rewritten_count / shown_count, 3),
        "ignored_rate": round(ignored_count / shown_count, 3),
        "by_trigger_type": _build_group_metrics(suggestion_items, "trigger_type"),
        "by_display_name": _build_group_metrics(suggestion_items, "display_name"),
    }
