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


def get_messages_with_sentiment(
    batch_id: str,
    limit: int = 50,
    exclude_system: bool = True,
    order_desc: bool = True,
):
    """获取消息及其情感分析结果."""
    db = get_db()

    where_clause = "WHERE m.batch_id = ?"
    params = [batch_id]

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
            m.created_at,
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

    deduped_rows.sort(
        key=lambda row: (_safe_int(row["timestamp"]), _safe_int(row["id"])),
        reverse=bool(order_desc),
    )

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
