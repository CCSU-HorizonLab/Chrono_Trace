"""脉搏门面指标的共享口径层（指标直白化，docs/product-redesign-2026-11.md §五）。

纯查询与翻译函数的单一事实来源：webview/api/pulse.py（脉搏页聚合）与
weekly_report_service.py（关系周报）共用，改口径只动这里。

口径约定（只翻译不新算）：
- 回应中位：response_times JOIN messages 按回消息发送方分侧，剔除异常与
  NULL，偶数取两值均值（同 deep 海报 _poster_reply_stats）；is_sender=1 的
  回消息 = 我回 TA。
- 主动天平：initiative_stats 表读回（分析期落库，全期口径）。
- 好感折线：affinity_scores 按 analysis_version（同口径）过滤，时间升序。
"""
from __future__ import annotations

import time
from typing import Any, Dict, List, Optional, Tuple

_DAY = 86400


def temperature_label(score: float) -> str:
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


def fmt_minutes(minutes: float) -> str:
    """中位回复时长的人话格式（判读句内用）。"""
    if minutes < 1:
        return f"{minutes * 60:.0f} 秒"
    if minutes < 60:
        return f"{minutes:.0f} 分钟"
    return f"{minutes / 60:.1f} 小时"


def month_start_ts(now: int) -> int:
    """当前自然月起点（本地时区）。"""
    lt = time.localtime(now)
    return int(time.mktime((lt.tm_year, lt.tm_mon, 1, 0, 0, 0, 0, 0, -1)))


def week_start_ts(now: int) -> int:
    """本周一 00:00（本地时区）——关系周报的周期锚点。"""
    lt = time.localtime(now)
    monday = lt.tm_mday - lt.tm_wday  # tm_wday 周一=0
    return int(time.mktime((lt.tm_year, lt.tm_mon, monday, 0, 0, 0, 0, 0, -1)))


def directional_response_medians(
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


def medians_to_minutes(stats: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
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


def monthly_overview(conversation_id: int, now: int) -> Dict[str, Any]:
    """本月速览：消息数/字数/深夜次数（当月自然月，messages 直聚合；
    深夜口径同 deep 海报 0-5 点本地时区）。"""
    from ...db.connection import get_db

    db = get_db()
    start = month_start_ts(now)
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
        (conversation_id, start),
    ).fetchone()
    char_row = db.execute(
        """
        SELECT SUM(mp.char_count)
        FROM messages m
        JOIN message_preprocessed mp ON mp.message_id = m.id
        WHERE m.conversation_id = ? AND m.timestamp >= ? AND mp.is_valid = 1
        """,
        (conversation_id, start),
    ).fetchone()
    return {
        "messages": int(row[0] or 0),
        "chars": int(char_row[0] or 0),
        "late_night": int(row[1] or 0),
        "late_night_by_me": int(row[2] or 0),
    }


def window_activity(conversation_id: int, from_ts: int, to_ts: int) -> Dict[str, Any]:
    """时间窗活跃概览：消息数/我方占比/深夜次数（周报周窗与对照窗共用）。"""
    from ...db.connection import get_db

    row = get_db().execute(
        """
        SELECT COUNT(*),
               SUM(CASE WHEN is_sender = 1 THEN 1 ELSE 0 END),
               SUM(CASE WHEN CAST(strftime('%H', timestamp, 'unixepoch', 'localtime')
                                AS INTEGER) BETWEEN 0 AND 5 THEN 1 ELSE 0 END)
        FROM messages
        WHERE conversation_id = ? AND timestamp >= ? AND timestamp < ?
        """,
        (conversation_id, from_ts, to_ts),
    ).fetchone()
    total = int(row[0] or 0)
    mine = int(row[1] or 0)
    return {
        "messages": total,
        "me_messages": mine,
        "ta_messages": total - mine,
        "me_pct": round(mine * 100.0 / total, 1) if total else None,
        "late_night": int(row[2] or 0),
    }


def initiative_summary(conversation_id: int) -> Optional[Dict[str, Any]]:
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


def trend_line(conversation_id: int, caliber: int, limit: int = 30) -> List[Tuple[int, float]]:
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


def dimension_deltas(conversation_id: int, caliber: int) -> Optional[Dict[str, Any]]:
    """最近两次分析的差分（周报 LLM 输入）：总分 + 四维分数与变化。

    只有 ≥2 行同口径历史才给 delta；单独一维缺失（如喜好未配置）该维保
    None 不参与话术。"""
    from ...db.connection import get_db

    rows = get_db().execute(
        """
        SELECT overall_score, sub_scores_json FROM affinity_scores
        WHERE conversation_id = ? AND analysis_version = ?
        ORDER BY created_at DESC LIMIT 2
        """,
        (conversation_id, caliber),
    ).fetchall()
    if not rows:
        return None

    def _dims(row) -> Dict[str, Optional[float]]:
        try:
            import json as _json

            sub = _json.loads(row[1] or "{}")
        except Exception:
            sub = {}
        out: Dict[str, Optional[float]] = {}
        for key in (
            "interaction_investment",
            "emotional_resonance",
            "closeness_signals",
            "preference_compatibility",
        ):
            entry = sub.get(key)
            out[key] = float(entry["score"]) if isinstance(entry, dict) and entry.get("score") is not None else None
        return out

    latest_overall = float(rows[0][0])
    latest_dims = _dims(rows[0])
    if len(rows) < 2:
        return {
            "overall": latest_overall,
            "overall_delta": None,
            "dims": latest_dims,
            "dim_deltas": {k: None for k in latest_dims},
        }
    prev_overall = float(rows[1][0])
    prev_dims = _dims(rows[1])
    return {
        "overall": latest_overall,
        "overall_delta": round(latest_overall - prev_overall, 1),
        "dims": latest_dims,
        "dim_deltas": {
            k: (round(latest_dims[k] - prev_dims[k], 1)
                if latest_dims[k] is not None and prev_dims[k] is not None else None)
            for k in latest_dims
        },
    }


def warning_from_risk(risk: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
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


def template_verdict(
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
                    f"TA 回你（中位约 {fmt_minutes(ta)}）比你回 TA（约 {fmt_minutes(me)}）更快。"
                )
            elif ta > me:
                parts.append(
                    f"你回 TA（中位约 {fmt_minutes(me)}）比 TA 回你（约 {fmt_minutes(ta)}）更快。"
                )
            else:
                parts.append("双方回复节奏相当。")
    return "".join(parts)
