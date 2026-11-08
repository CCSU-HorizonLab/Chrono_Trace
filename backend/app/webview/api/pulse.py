"""脉搏页聚合 API（指标直白化层）。

门面指标只翻译不新算（docs/product-redesign-2026-11.md §五）：关系温度/
主动天平/回应温度/本月速览/冷淡预警全部来自既有引擎产物（affinity 缓存与
历史表、initiative_stats、response_times、messages），本模块只做聚合与
话术化，不引入新的计算口径。

依赖说明：get_affinity_scores 由 Bridge 多继承组合提供（affinity.py 的
读出口带 sentinel 改写与 stale 标记，必须复用不可绕过）。
"""
from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

_DAY = 86400


# ----------------------------------------------------------------------
# 纯函数（模块级，便于单测）
# ----------------------------------------------------------------------

def _temperature_label(score: float) -> str:
    """关系温度分段话术（0-100）。"""
    if score >= 75:
        return "炽热"
    if score >= 60:
        return "温热"
    if score >= 45:
        return "温和"
    if score >= 30:
        return "转凉"
    return "冰点"


def _fmt_minutes(minutes: float) -> str:
    """中位回复时长的人话格式（判读句内用）。"""
    if minutes < 1:
        return f"{minutes * 60:.0f} 秒"
    if minutes < 60:
        return f"{minutes:.0f} 分钟"
    return f"{minutes / 60:.1f} 小时"


def _month_start_ts(now: int) -> int:
    """当前自然月起点（本地时区）。"""
    lt = time.localtime(now)
    return int(time.mktime((lt.tm_year, lt.tm_mon, 1, 0, 0, 0, 0, 0, -1)))


def _directional_response_medians(
    conversation_id: int, from_ts: int, to_ts: int
) -> Optional[Dict[str, Any]]:
    """双向回复中位数（秒）——口径同 deep 海报 _poster_reply_stats：
    response_times JOIN messages 按回消息发送方分侧，剔除异常与 NULL；
    中位数按序取中位段（偶数取两值均值，SQLite 无 MEDIAN）。无数据返回
    None。is_sender=1 的回消息 = 我回 TA；is_sender=0 = TA 回我。
    """
    from ...db.connection import get_db

    db = get_db()
    where = (
        "WHERE rt.conversation_id = ? AND m.timestamp BETWEEN ? AND ? "
        "AND rt.is_abnormal = 0 AND rt.response_time_seconds IS NOT NULL"
    )
    row = db.execute(
        f"""
        SELECT SUM(CASE WHEN m.is_sender = 1 THEN 1 ELSE 0 END),
               SUM(CASE WHEN m.is_sender = 0 THEN 1 ELSE 0 END)
        FROM response_times rt
        JOIN messages m ON m.id = rt.reply_message_id
        {where}
        """,
        (conversation_id, from_ts, to_ts),
    ).fetchone()
    me_count, ta_count = int(row[0] or 0), int(row[1] or 0)
    if not (me_count or ta_count):
        return None

    def _median(is_sender: int, count: int) -> Optional[float]:
        if not count:
            return None
        rows = db.execute(
            f"""
            SELECT rt.response_time_seconds
            FROM response_times rt
            JOIN messages m ON m.id = rt.reply_message_id
            {where} AND m.is_sender = ?
            ORDER BY rt.response_time_seconds
            LIMIT 2 OFFSET ?
            """,
            (conversation_id, from_ts, to_ts, is_sender, (count - 1) // 2),
        ).fetchall()
        vals = [float(r[0]) for r in rows if r[0] is not None]
        if not vals:
            return None
        if len(vals) == 2 and count % 2 == 0:
            return (vals[0] + vals[1]) / 2
        return vals[0]

    return {
        "me_to_ta_median_sec": _median(1, me_count),
        "ta_to_me_median_sec": _median(0, ta_count),
        "me_count": me_count,
        "ta_count": ta_count,
    }


def _medians_to_minutes(stats: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """秒 → 分钟（前端直接展示），中位缺失侧保 None。"""
    if not stats:
        return None

    def _m(sec) -> Optional[float]:
        return round(sec / 60.0, 1) if sec is not None else None

    return {
        "me_to_ta_median_min": _m(stats.get("me_to_ta_median_sec")),
        "ta_to_me_median_min": _m(stats.get("ta_to_me_median_sec")),
        "me_count": stats["me_count"],
        "ta_count": stats["ta_count"],
    }


def _monthly_overview(conversation_id: int, now: int) -> Dict[str, Any]:
    """本月速览：消息数/字数/深夜次数（当月自然月，messages 直聚合；
    深夜口径同 deep 海报 0-5 点本地时区）。"""
    from ...db.connection import get_db

    db = get_db()
    month_start = _month_start_ts(now)
    row = db.execute(
        """
        SELECT COUNT(*),
               SUM(CASE WHEN CAST(strftime('%H', timestamp, 'unixepoch', 'localtime')
                                AS INTEGER) BETWEEN 0 AND 5 THEN 1 ELSE 0 END),
               SUM(CASE WHEN CAST(strftime('%H', timestamp, 'unixepoch', 'localtime')
                                AS INTEGER) BETWEEN 0 AND 5 AND is_sender = 1
                          THEN 1 ELSE 0 END)
        FROM messages
        WHERE conversation_id = ? AND timestamp >= ?
        """,
        (conversation_id, month_start),
    ).fetchone()
    char_row = db.execute(
        """
        SELECT SUM(mp.char_count)
        FROM messages m
        JOIN message_preprocessed mp ON mp.message_id = m.id
        WHERE m.conversation_id = ? AND m.timestamp >= ? AND mp.is_valid = 1
        """,
        (conversation_id, month_start),
    ).fetchone()
    return {
        "messages": int(row[0] or 0),
        "chars": int(char_row[0] or 0),
        "late_night": int(row[1] or 0),
        "late_night_by_me": int(row[2] or 0),
    }


def _initiative_summary(conversation_id: int) -> Optional[Dict[str, Any]]:
    """主动天平：initiative_stats 表读回（分析期落库），发起占比换算。"""
    from ...db.connection import get_db

    row = get_db().execute(
        """
        SELECT total_sessions, user_initiated_sessions, other_initiated_sessions
        FROM initiative_stats WHERE conversation_id = ?
        """,
        (conversation_id,),
    ).fetchone()
    if not row:
        return None
    total, mine, theirs = int(row[0] or 0), int(row[1] or 0), int(row[2] or 0)
    me_pct = round(mine * 100.0 / (mine + theirs), 1) if (mine + theirs) else None
    return {
        "total_sessions": total,
        "user_initiated": mine,
        "other_initiated": theirs,
        "me_pct": me_pct,
    }


def _trend_line(conversation_id: int, caliber: int, limit: int = 30) -> List[Tuple[int, float]]:
    """好感历史折线（同口径才可比较，analysis_version 过滤；时间升序）。"""
    from ...db.connection import get_db

    rows = get_db().execute(
        """
        SELECT created_at, overall_score FROM affinity_scores
        WHERE conversation_id = ? AND analysis_version = ?
        ORDER BY created_at DESC LIMIT ?
        """,
        (conversation_id, caliber, limit),
    ).fetchall()
    return [(int(r[0]), float(r[1])) for r in reversed(rows)]


def _warning_from_risk(risk: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """冷淡预警直白化：risk_assessment → 只保留非「未见异常」信号；
    全部正常返回 None（前端整条隐藏，不占焦虑空间）。"""
    if not risk or not isinstance(risk, dict):
        return None
    highest = risk.get("highest_level")
    if not highest or highest == "未见异常":
        return None
    items = [
        {"label": sig.get("label", ""), "level": sig.get("level", ""), "note": sig.get("note", "")}
        for sig in (risk.get("signals") or {}).values()
        if isinstance(sig, dict) and sig.get("level") not in (None, "", "未见异常")
    ]
    return {"level": highest, "items": items} if items else None


def _template_verdict(
    temperature: Optional[Dict[str, Any]],
    initiative: Optional[Dict[str, Any]],
    response_recent: Optional[Dict[str, Any]],
) -> str:
    """LLM 缺席时的本地判读句：温度趋势 + 主动天平 + 回应节奏 三段拼接。"""
    parts: List[str] = []
    if temperature:
        line = f"关系温度 {round(temperature['score'])}（{temperature['label']}）"
        delta = temperature.get("delta")
        if delta is not None:
            line += f"，较上次{'上升' if delta >= 0 else '下降'} {abs(delta):.1f} 分"
        parts.append(line + "。")
    if initiative and initiative.get("me_pct") is not None:
        me = initiative["me_pct"]
        if me >= 60:
            parts.append(f"对话多由你发起（{me:.0f}%），关系目前由你在推动。")
        elif me <= 40:
            parts.append(f"对话多由 TA 发起（{100 - me:.0f}%），TA 的主动性更高。")
        else:
            parts.append("双方话题发起较为均衡。")
    if response_recent:
        ta = response_recent.get("ta_to_me_median_min")
        me = response_recent.get("me_to_ta_median_min")
        if ta is not None and me is not None:
            if ta < me:
                parts.append(
                    f"TA 回你（中位约 {_fmt_minutes(ta)}）比你回 TA（约 {_fmt_minutes(me)}）更快。"
                )
            elif ta > me:
                parts.append(
                    f"你回 TA（中位约 {_fmt_minutes(me)}）比 TA 回你（约 {_fmt_minutes(ta)}）更快。"
                )
            else:
                parts.append("双方回复节奏相当。")
    return "".join(parts)


# ----------------------------------------------------------------------
# Bridge Mixin
# ----------------------------------------------------------------------

class PulseApiMixin:
    """脉搏页：门面指标聚合（关系温度/主动天平/回应温度/本月速览/预警/判读）。"""

    def get_pulse_overview(self, conversation_id: int) -> dict:
        """单点聚合。professional 字段透传完整好感度结果供专业视图折叠层
        复用（四维雷达/风险卡/权重入口），前端无需二次调 get_affinity_scores。"""
        try:
            # 同 Bridge 上其它 mixin 方法（由 Bridge 多继承组合提供）
            base = self.get_affinity_scores(conversation_id)
            result = base.get("result")
            history = base.get("history") or {}
            now = int(time.time())

            temperature = None
            if result:
                delta = history.get("score_trend") if history.get("comparable") else None
                temperature = {
                    "score": result["overall_score"],
                    "label": _temperature_label(result["overall_score"]),
                    "delta": delta,
                    "trend_line": _trend_line(
                        conversation_id, result.get("analysis_caliber") or 0
                    ),
                }

            initiative = _initiative_summary(conversation_id)
            recent = _medians_to_minutes(
                _directional_response_medians(conversation_id, now - 30 * _DAY, now)
            )
            prev = _medians_to_minutes(
                _directional_response_medians(conversation_id, now - 60 * _DAY, now - 30 * _DAY)
            )
            response = (
                {"recent": recent, "prev": prev} if (recent or prev) else None
            )

            warning = _warning_from_risk(result.get("risk_assessment")) if result else None

            verdict = None
            if result:
                llm = result.get("llm_relationship")
                if llm and llm.get("interpretation"):
                    verdict = {"text": llm["interpretation"], "source": "llm"}
                else:
                    verdict = {
                        "text": _template_verdict(temperature, initiative, recent),
                        "source": "template",
                    }

            return {
                "ok": True,
                "analyzed": result is not None,
                "verdict": verdict,
                "temperature": temperature,
                "initiative": initiative,
                "response": response,
                "monthly": _monthly_overview(conversation_id, now),
                "warning": warning,
                "professional": {
                    "result": result,
                    "analysis_stale": base.get("analysis_stale", False),
                    "pending_message_count": base.get("pending_message_count", 0),
                    "absent_reason": (
                        result.get("llm_relationship_absent_reason") if result else None
                    ),
                },
            }
        except Exception as e:
            logger.error(f"[Pulse] 聚合失败 conversation={conversation_id}: {e}")
            return {"ok": False, "error": str(e)}
