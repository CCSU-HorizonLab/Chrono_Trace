"""好感度历史分数：落库 affinity_scores（此前该表从未被写入）。

每次分析完成追加一行（只增不删）；读取最近两行计算趋势。跨口径
（analysis_version 不同）标记不可比，前端不显示趋势。
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Dict, List, Optional

from ...db.connection import get_db

logger = logging.getLogger(__name__)


def record_score_history(
    conversation_id: int,
    result: Any,
    stats: Any = None,
    config_snapshot: Optional[Dict[str, Any]] = None,
) -> None:
    """分析完成后落一行历史（失败仅记日志，不影响主流程）。"""
    try:
        def _dim_score(name: str) -> float:
            dim = getattr(result, name, None)
            return round(float(dim.score), 2) if dim is not None else 0.0

        def _dim_payload(name: str) -> Dict[str, Any]:
            dim = getattr(result, name, None)
            if dim is None:
                return {"score": None, "weight": 0.0, "sub_scores": {}}
            return {
                "score": dim.score,
                "weight": dim.weight,
                "weighted_score": dim.weighted_score,
                "sub_scores": dict(dim.sub_scores or {}),
            }

        sub_scores = {
            "emotional_resonance": _dim_payload("emotional_resonance"),
            "chat_positivity": _dim_payload("chat_positivity"),
            "attitude_tendency": _dim_payload("attitude_tendency"),
            "preference_compatibility": _dim_payload("preference_compatibility"),
            "intimacy_signals": _dim_payload("intimacy_signals"),
            "llm_relationship": _dim_payload("llm_relationship"),
        }
        get_db().execute(
            """
            INSERT INTO affinity_scores
            (conversation_id, analysis_version, overall_score,
             emotional_resonance_score, chat_positivity_score,
             attitude_tendency_score, preference_compatibility_score,
             sub_scores_json, message_count, interaction_pair_count,
             config_snapshot, analysis_duration_ms, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                int(conversation_id),
                int(getattr(result, "analysis_caliber", 0) or 0),
                float(result.overall_score or 0.0),
                _dim_score("emotional_resonance"),
                _dim_score("chat_positivity"),
                _dim_score("attitude_tendency"),
                _dim_score("preference_compatibility"),
                json.dumps(sub_scores, ensure_ascii=False),
                int(getattr(stats, "total_message_count", 0) or 0),
                int(getattr(stats, "total_interaction_pairs", 0) or 0),
                json.dumps(config_snapshot or {}, ensure_ascii=False, sort_keys=True),
                int(getattr(result, "analysis_duration_ms", 0) or 0),
                int(time.time()),
            ),
        )
        get_db().commit()
        logger.debug(f"[历史分数] 已落库 (会话 {conversation_id}, 总分 {result.overall_score})")
    except Exception as exc:
        logger.warning(f"[历史分数] 落库失败（不影响分析结果）: {exc}")


def get_recent_scores(conversation_id: int, limit: int = 2) -> List[Dict[str, Any]]:
    rows = get_db().execute(
        """
        SELECT overall_score, analysis_version, created_at
        FROM affinity_scores
        WHERE conversation_id = ?
        ORDER BY created_at DESC, id DESC
        LIMIT ?
        """,
        (int(conversation_id), int(limit)),
    ).fetchall()
    return [dict(row) for row in rows]


def compute_trend(conversation_id: int) -> Dict[str, Any]:
    """最近两行对比；口径不同则 comparable=False（前端不显示趋势）。"""
    rows = get_recent_scores(conversation_id, limit=2)
    history: Dict[str, Any] = {
        "last_score": None,
        "prev_score": None,
        "score_trend": None,
        "last_analysis_at": None,
        "comparable": False,
    }
    if not rows:
        return history
    history["last_score"] = round(float(rows[0]["overall_score"]), 2)
    history["last_analysis_at"] = int(rows[0]["created_at"] or 0)
    if len(rows) < 2:
        return history
    history["prev_score"] = round(float(rows[1]["overall_score"]), 2)
    same_caliber = int(rows[0]["analysis_version"] or 0) == int(
        rows[1]["analysis_version"] or 0
    )
    history["comparable"] = same_caliber
    if same_caliber:
        history["score_trend"] = round(
            history["last_score"] - history["prev_score"], 2
        )
    return history
