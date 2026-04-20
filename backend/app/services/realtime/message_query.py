"""实时消息查询服务

提供消息列表查询功能,联合查询消息和情感分析结果
"""

import json

from ...db.connection import get_db
from .providers.models import normalize_text


def _safe_int(value, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _build_recent_message_dedupe_key(row) -> str:
    """Collapse repeated captures of the same visible bubble before prompting the LLM."""
    semantic_key = "|".join(
        [
            normalize_text(row["sender_attr"]),
            normalize_text(row["message_type"]).lower(),
            normalize_text(row["content"]),
            str(_safe_int(row["timestamp"])),
        ]
    )
    if semantic_key.strip("|"):
        return semantic_key

    message_hash = normalize_text(row["message_hash"])
    if message_hash:
        return f"hash:{message_hash}"

    return ""


def _row_value(row, key: str, default=None):
    try:
        return row[key]
    except Exception:
        return default


def _has_visible_index_column(db) -> bool:
    try:
        rows = db.execute("PRAGMA table_info(realtime_message_buffer)").fetchall()
    except Exception:
        return False
    for row in rows:
        try:
            name = row["name"]
        except Exception:
            name = row[1]
        if str(name) == "visible_index":
            return True
    return False


def _recent_message_sort_key(row) -> tuple[int, int, int, int, int]:
    timestamp = _safe_int(_row_value(row, "timestamp"))
    visible_index = _safe_int(_row_value(row, "visible_index"), -1)
    created_at = _safe_int(_row_value(row, "created_at"))
    captured_at = _safe_int(_row_value(row, "captured_at"))
    row_id = _safe_int(_row_value(row, "id"))
    if visible_index >= 0:
        return (timestamp, 0, visible_index, created_at, row_id)
    return (timestamp, 1, created_at or captured_at, row_id, row_id)


def get_messages_with_sentiment(
    batch_id: str,
    limit: int = 50,
    exclude_system: bool = True,
    order_desc: bool = True,
    account_wxid: str = "",
):
    """获取消息及其情感分析结果."""
    db = get_db()
    visible_index_sql = "m.visible_index AS visible_index" if _has_visible_index_column(db) else "-1 AS visible_index"

    where_clause = "WHERE m.batch_id = ?"
    params = [batch_id]
    normalized_account_wxid = str(account_wxid or "").strip()
    if normalized_account_wxid:
        where_clause += " AND m.account_wxid = ?"
        params.append(normalized_account_wxid)

    if exclude_system:
        where_clause += " AND m.sender_attr != 'system'"

    cursor = db.execute(
        f"""
        SELECT
            m.id,
            m.message_hash,
            m.runtime_id,
            m.sender_attr,
            m.content,
            m.message_type,
            m.timestamp,
            m.captured_at,
            m.created_at,
            {visible_index_sql},
            s.polarity,
            s.intensity,
            s.confidence,
            s.rules_applied
        FROM realtime_message_buffer m
        LEFT JOIN realtime_sentiment_cache s ON m.message_hash = s.message_id
        {where_clause}
        ORDER BY m.created_at ASC, m.id ASC
        """,
        params,
    )

    deduped_rows = []
    seen_dedupe_keys = set()
    for row in cursor.fetchall():
        dedupe_key = _build_recent_message_dedupe_key(row)
        if dedupe_key and dedupe_key in seen_dedupe_keys:
            continue
        if dedupe_key:
            seen_dedupe_keys.add(dedupe_key)
        deduped_rows.append(row)

    deduped_rows.sort(key=_recent_message_sort_key)
    if order_desc:
        deduped_rows.reverse()

    messages = []
    for row in deduped_rows[: max(0, int(limit or 0))]:
        message = {
            "id": row["id"],
            "message_hash": row["message_hash"],
            "runtime_id": row["runtime_id"],
            "sender": row["sender_attr"],
            "sender_attr": row["sender_attr"],
            "content": row["content"],
            "type": row["message_type"],
            "message_type": row["message_type"],
            "timestamp": row["timestamp"],
            "visible_index": _row_value(row, "visible_index", -1),
            "created_at": row["created_at"],
            "captured_at": row["captured_at"],
        }

        if row["polarity"] is not None:
            message["sentiment"] = {
                "polarity": row["polarity"],
                "intensity": row["intensity"],
                "confidence": row["confidence"],
                "rules": json.loads(row["rules_applied"]) if row["rules_applied"] else [],
            }
        else:
            message["sentiment"] = None

        messages.append(message)

    return messages
