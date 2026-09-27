"""分析新鲜度状态机（stale）：导入/监听写入新消息 → 打脏 → 前端提示重分析。

设计要点：
- **stale 的真源是写入钩子**，不是 max(messages.timestamp) 对比——OR IGNORE
  全跳过的重复导入（rowcount==0 不进 touched_conversations）不该误报；
- 打脏时顺手删除 settings 的 preprocessing_stats_v2_{id} 缓存行——该缓存
  此前无消息集维度失效条件，导入新消息后非 force 路径会吐旧统计（既有
  bug，此处一并修复）；
- 完成点（特征提取/好感度分析成功尾部）写 stale=0 + 快照两列。
"""
from __future__ import annotations

import logging
from typing import Iterable, Optional

from ...db.connection import get_db

logger = logging.getLogger(__name__)

_STATS_KEY_PREFIX = "preprocessing_stats_v2_"


def mark_conversations_stale(conversation_ids: Iterable[int]) -> None:
    """标记会话分析结果待更新，并失效预处理统计缓存。

    幂等；空列表直接返回。失败只丢提示不阻断调用方（导入/监听主流程）。
    """
    ids = [int(cid) for cid in conversation_ids if cid]
    if not ids:
        return
    try:
        conn = get_db()
        placeholders = ",".join(["?"] * len(ids))
        conn.execute(
            f"UPDATE conversations SET analysis_stale = 1 WHERE id IN ({placeholders})",
            ids,
        )
        # 既有 bug 修复：preprocessing_stats 缓存不随消息集变化失效
        conn.execute(
            "DELETE FROM settings WHERE key IN ("
            + ",".join([f"?"] * len(ids)) + ")",
            [f"{_STATS_KEY_PREFIX}{cid}" for cid in ids],
        )
        conn.commit()
        logger.debug("[分析状态] 已标记 %d 个会话待重新分析", len(ids))
    except Exception as exc:
        logger.warning("[分析状态] 打脏失败（忽略，不阻断导入）: %s", exc)


def mark_analysis_complete(conversation_id: int) -> None:
    """分析完成：清脏 + 快照当前消息集规模。

    快照用 COUNT(*)（而非 MAX(timestamp)）做 pending 计数基准——能捕捉
    timestamp 早于水位的乱序回填。
    """
    try:
        conn = get_db()
        conn.execute(
            """
            UPDATE conversations
            SET analysis_stale = 0,
                analysis_message_count = (
                    SELECT COUNT(*) FROM messages
                    WHERE messages.conversation_id = conversations.id
                ),
                analysis_watermark_ts = (
                    SELECT MAX(timestamp) FROM messages
                    WHERE messages.conversation_id = conversations.id
                )
            WHERE id = ?
            """,
            (int(conversation_id),),
        )
        conn.commit()
    except Exception as exc:
        logger.warning("[分析状态] 完成标记失败（忽略）: %s", exc)


def get_analysis_freshness(conversation_id: int) -> dict:
    """读取会话分析新鲜度（读端透出用）。"""
    try:
        row = get_db().execute(
            """
            SELECT c.analysis_stale, c.analysis_message_count, c.message_count
            FROM conversations c
            WHERE c.id = ?
            """,
            (int(conversation_id),),
        ).fetchone()
    except Exception as exc:
        logger.debug("[分析状态] 新鲜度读取失败: %s", exc)
        return {"stale": False, "pending_message_count": 0}

    if row is None:
        return {"stale": False, "pending_message_count": 0}

    stale = bool(row["analysis_stale"])
    analyzed = row["analysis_message_count"]
    current = row["message_count"] or 0
    pending: Optional[int]
    if analyzed is None:
        pending = None  # 从未分析过：无从计算增量，前端显示「未分析」
    else:
        pending = max(0, current - (analyzed or 0))
    return {"stale": stale, "pending_message_count": pending}
