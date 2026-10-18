"""画像长期背景（全时段基线）统计。

rolling 滚动窗对长关系只覆盖尾部（窗内采样目标填满即不回看更早），
画像会丢掉绝大部分历史——本模块给两 profiler 提供同一份全时段统计
（纯 SQL，零 LLM 成本），以【长期背景】块注入 prompt，口径与
_poster_stats / 词云一致（message_type=1 且非空白、本地时区）。

LLM 同时看到「窗口内的他」与「全时段的他」，窗口覆盖比一行是关键：
画像结论以窗口为主，长期数字用于对照演变（同 affinity 的
caliber='full_period' 先例）。
"""

from __future__ import annotations

from typing import Any

_TEXT_SQL = "message_type = 1 AND TRIM(COALESCE(content, '')) != ''"


def collect_full_period_baseline(
    conn: Any,
    conversation_id: int,
    current_from: int,
    current_to: int,
) -> dict:
    """全时段基线统计。current_from/current_to 为本次画像窗口（闭区间），
    用于计算窗口对全时段的覆盖率。返回空 dict 表示无文本消息（整块跳过）。"""
    row = conn.execute(
        f"""
        SELECT MIN(timestamp) AS first_ts, MAX(timestamp) AS last_ts,
               COUNT(*) AS text_total,
               SUM(is_sender = 1) AS text_user,
               SUM(is_sender = 0) AS text_other,
               COUNT(DISTINCT DATE(timestamp, 'unixepoch', 'localtime')) AS active_days
        FROM messages
        WHERE conversation_id = ? AND {_TEXT_SQL}
        """,
        (conversation_id,),
    ).fetchone()
    if not row or not row["text_total"]:
        return {}

    from datetime import datetime

    fmt = lambda ts: datetime.fromtimestamp(int(ts)).strftime("%Y-%m-%d")  # noqa: E731
    baseline: dict = {
        "first_date": fmt(row["first_ts"]),
        "last_date": fmt(row["last_ts"]),
        "span_days": (int(row["last_ts"]) - int(row["first_ts"])) // 86400 + 1,
        "active_days": int(row["active_days"] or 0),
        "text_total": int(row["text_total"]),
        "text_user": int(row["text_user"] or 0),
        "text_other": int(row["text_other"] or 0),
    }

    # 分年消息量（呈现长期演变：哪年热、哪年冷）
    yearly = conn.execute(
        f"""
        SELECT strftime('%Y', timestamp, 'unixepoch', 'localtime') AS year, COUNT(*) AS cnt
        FROM messages
        WHERE conversation_id = ? AND {_TEXT_SQL}
        GROUP BY year ORDER BY year
        """,
        (conversation_id,),
    ).fetchall()
    baseline["yearly"] = [(r["year"], int(r["cnt"])) for r in yearly]

    # 深夜占比（0-5 点；CAST 整数比较——字符串 BETWEEN 会把 '23' 错配进档）
    late = conn.execute(
        f"""
        SELECT COUNT(*) AS cnt FROM messages
        WHERE conversation_id = ? AND {_TEXT_SQL}
          AND CAST(strftime('%H', timestamp, 'unixepoch', 'localtime') AS INTEGER) BETWEEN 0 AND 5
        """,
        (conversation_id,),
    ).fetchone()
    if late and late["cnt"]:
        baseline["late_night_ratio"] = late["cnt"] / baseline["text_total"]

    # 本次窗口覆盖（rolling 名义窗 / custom 指定窗同口径）
    if current_from and current_to:
        win = conn.execute(
            f"""
            SELECT COUNT(*) AS cnt FROM messages
            WHERE conversation_id = ? AND {_TEXT_SQL}
              AND timestamp >= ? AND timestamp <= ?
            """,
            (conversation_id, current_from, current_to),
        ).fetchone()
        if win and win["cnt"]:
            baseline["window_text_count"] = int(win["cnt"])
            baseline["window_coverage"] = win["cnt"] / baseline["text_total"]

    return baseline


def render_baseline_block(baseline: dict) -> str:
    """渲染【长期背景】prompt 块；空 baseline 返回空串（调用方跳过）。"""
    if not baseline:
        return ""
    lines = [
        "【长期背景】（全时段统计，仅供基线参考；画像结论以窗口样本为主，长期数字用于对照演变）",
        (
            f"- 全时段: {baseline['first_date']} ~ {baseline['last_date']}"
            f"（{baseline['span_days']} 天），活跃 {baseline['active_days']} 天，"
            f"文本消息 {baseline['text_total']} 条"
            f"（我 {baseline['text_user']} / 对方 {baseline['text_other']}）"
        ),
    ]
    if baseline.get("yearly"):
        lines.append("- 分年消息量: " + " / ".join(f"{y} 年 {c} 条" for y, c in baseline["yearly"]))
    if baseline.get("late_night_ratio") is not None:
        lines.append(f"- 深夜（0-5 点）消息占比: {baseline['late_night_ratio']:.0%}")
    cov = baseline.get("window_coverage")
    if cov is not None:
        lines.append(
            f"- 本次窗口样本覆盖: 全时段的 {cov:.0%}"
            f"（{baseline['window_text_count']}/{baseline['text_total']} 条）"
        )
    return "\n".join(lines)
