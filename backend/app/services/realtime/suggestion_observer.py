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

TERMINAL_EVENT_TYPES = (
    EVENT_DISMISSED,
    EVENT_ADOPTED,
    EVENT_REWRITTEN,
)
SINGLETON_EVENT_TYPES = {
    EVENT_SHOWN,
    EVENT_VIEWED,
    EVENT_DISMISSED,
    EVENT_ADOPTED,
    EVENT_REWRITTEN,
}

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


def _record_outcome_policy_signal(
    conn,
    *,
    suggestion_id: int,
    account_wxid: str | None,
    event_type: str,
    detail: dict[str, Any] | None = None,
) -> None:
    """P2.1：建议终态（adopted/rewritten/preface_then_reply）影子信号。

    只记录不决策——把该建议实际使用的策略（检索日志 policy_ids/
    contact_preference_ids/injected facts）与终态绑定，为后续
    "反馈→策略修正"提供审计底账。任何异常静默跳过，绝不阻塞事件。
    """
    try:
        from .rag.store import RagStore

        store = RagStore(conn)
        existing = conn.execute(
            """
            SELECT 1 FROM rag_feedback_policy_signals
            WHERE suggestion_id = ? AND action = ? LIMIT 1
            """,
            (int(suggestion_id), str(event_type)),
        ).fetchone()
        if existing:
            return
        log = conn.execute(
            """
            SELECT id, account_wxid, conversation_id, policy_ids_json,
                   contact_preference_ids_json, injected_item_ids_json
            FROM rag_retrieval_logs WHERE suggestion_id = ? ORDER BY id DESC LIMIT 1
            """,
            (int(suggestion_id),),
        ).fetchone()
        if log is None:
            return
        store.record_feedback_policy_signal(
            account_wxid=str(log["account_wxid"] or account_wxid or ""),
            conversation_id=log["conversation_id"],
            suggestion_id=int(suggestion_id),
            action=str(event_type),
            signal_kind="suggestion_outcome",
            affected_policy_ids=json.loads(log["policy_ids_json"] or "[]"),
            outcome="recorded",
            retrieval_log_id=int(log["id"]),
            detail={
                "contact_preference_ids": json.loads(log["contact_preference_ids_json"] or "[]"),
                "injected_item_ids": json.loads(log["injected_item_ids_json"] or "[]"),
                **(detail or {}),
            },
        )
    except Exception:
        pass


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
        if event_type in {"adopted", "rewritten", "preface_then_reply"}:
            _record_outcome_policy_signal(
                conn,
                suggestion_id=int(suggestion_id),
                account_wxid=payload["account_wxid"],
                event_type=event_type,
                detail={"selected_speech": (selected_speech or "")[:200]},
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
    normalized_account_wxid = _resolve_account_wxid(account_wxid) if account_wxid is not None else ""
    if normalized_account_wxid:
        conn.execute(
            """
            UPDATE realtime_suggestions
            SET read_at = COALESCE(read_at, ?)
            WHERE id = ? AND account_wxid = ?
            """,
            (ts, suggestion_id, normalized_account_wxid),
        )
    else:
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
