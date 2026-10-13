"""关系体检报告导出：单文件 HTML（内联 CSS + Python 计算 SVG，无 JS 依赖）。

组装：好感度结果（缓存）+ 历史趋势（affinity_scores 最近 N 次，口径标记）
+ 风险预警 + RAG 画像摘要 + 基础统计。产物写入 chrono_trace_export
临时目录，与聊天记录导出同约定（前端 open_external_url 打开所在目录）。
"""
from __future__ import annotations

import html as html_module
import logging
import math
import time
from typing import Any, Dict, List, Optional, Tuple

from ...db.connection import get_db

logger = logging.getLogger(__name__)

HISTORY_LIMIT = 10
RADAR_CENTER = 110.0
RADAR_RADIUS = 90.0

# 维度展示序（与雷达图一致；缺席维度跳过）
_DIMENSIONS: List[Tuple[str, str]] = [
    ("interaction_investment", "互动投入"),
    ("emotional_resonance", "情感共鸣"),
    ("closeness_signals", "亲近信号"),
    ("preference_compatibility", "喜好兼容度"),
    ("llm_relationship", "AI 关系评估"),
]

_SUB_LABELS = {
    "daily_message": "日均消息量", "reply_timeliness": "回复及时性",
    "topic_continuity": "话题延续性", "active_initiation": "主动发起",
    "reply_symmetry": "回应对称性", "long_unanswered": "长时未回应",
    "burst_unanswered": "连发未回",
    "bidirectional_positive": "双向积极互动", "polarity_consistency": "情绪一致性",
    "intensity_matching": "情绪强度匹配", "valence_balance": "正负平衡",
    "perfunctory_reply": "敷衍回复", "empathy_recognition": "共情识别",
    "negative_resolution": "负面情绪化解",
    "address_term_evolution": "称谓演变", "late_night_engagement": "深夜时段互动",
    "active_coverage": "活跃覆盖", "greeting_initiation": "早晚安发起",
    "icebreaking": "主动破冰", "community_expression": "共同体表达",
    "topic_mention": "共同话题提及",
    "communication_quality": "沟通质量", "relationship_warmth": "关系温度",
}

_LEVEL_COLORS = {"预警": "#e11d48", "留意": "#f59e0b", "未见异常": "#10b981"}

_CSS = """
:root { color-scheme: light; }
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: 'PingFang SC', 'Microsoft YaHei', sans-serif; background: #f4f6fb; color: #1f2937; padding: 32px 16px; line-height: 1.7; }
.page { max-width: 860px; margin: 0 auto; }
h1 { font-size: 22px; margin-bottom: 4px; }
h2 { font-size: 15px; margin: 28px 0 12px; padding-left: 10px; border-left: 3px solid #5b6be0; }
.meta { color: #6b7280; font-size: 12px; margin-bottom: 20px; }
.card { background: #fff; border: 1px solid #e5e7eb; border-radius: 12px; padding: 20px; margin-bottom: 16px; }
.score-hero { display: flex; align-items: center; gap: 24px; }
.score-num { font-size: 52px; font-weight: 700; color: #5b6be0; }
.score-num small { font-size: 18px; color: #9ca3af; }
.interpretation { flex: 1; font-size: 13px; color: #4b5563; }
.dims { display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap: 12px; }
.dim h3 { font-size: 13px; display: flex; justify-content: space-between; margin-bottom: 6px; }
.dim h3 em { font-style: normal; color: #5b6be0; font-family: monospace; }
.bar { height: 8px; border-radius: 4px; background: #eef0f6; overflow: hidden; margin-bottom: 10px; }
.bar i { display: block; height: 100%; background: linear-gradient(90deg, #5b6be0, #8b5cf6); border-radius: 4px; }
.subs { font-size: 11px; color: #6b7280; }
.subs span { display: inline-block; margin: 0 10px 4px 0; }
.subs b { color: #374151; font-family: monospace; font-weight: 600; }
.risk-item { padding: 10px 12px; border-left: 3px solid #d1d5db; background: #f9fafb; border-radius: 6px; margin-bottom: 8px; font-size: 12px; }
.risk-item.alert { border-left-color: #e11d48; }
.risk-item.watch { border-left-color: #f59e0b; }
.risk-item.normal { border-left-color: #10b981; }
.risk-head { display: flex; justify-content: space-between; font-weight: 600; margin-bottom: 4px; }
.risk-level { font-size: 11px; padding: 1px 8px; border-radius: 999px; color: #fff; }
.evidence { color: #6b7280; font-style: italic; margin-top: 4px; }
table { width: 100%; border-collapse: collapse; font-size: 12px; }
th, td { text-align: left; padding: 6px 8px; border-bottom: 1px solid #e5e7eb; }
th { color: #6b7280; font-weight: 500; font-size: 11px; }
.tags span { display: inline-block; background: #eef0ff; color: #5b6be0; border-radius: 999px; padding: 2px 10px; font-size: 12px; margin: 0 6px 6px 0; }
.note { font-size: 11px; color: #9ca3af; margin-top: 16px; }
"""


class AffinityReportExportError(Exception):
    """报告导出失败（message 面向用户展示）"""


def _esc(text: Any) -> str:
    return html_module.escape(str(text if text is not None else ""))


def _pct(score: float) -> int:
    return max(0, min(100, int(round(float(score)))))


def _fmt_time(ts: Any) -> str:
    try:
        return time.strftime("%Y-%m-%d %H:%M", time.localtime(int(ts)))
    except (TypeError, ValueError):
        return "--"


def _radar_svg(points: List[Tuple[str, float]]) -> str:
    """Python 计算的五边形雷达（网格 + 数据多边形 + 轴标签），无 JS。"""
    count = len(points)
    if count < 3:
        return ""

    def vertex(i: int, ratio: float) -> Tuple[float, float]:
        angle = -math.pi / 2 + 2 * math.pi * i / count
        return (
            RADAR_CENTER + math.cos(angle) * RADAR_RADIUS * ratio,
            RADAR_CENTER + math.sin(angle) * RADAR_RADIUS * ratio,
        )

    def poly(ratio: float) -> str:
        return " ".join(f"{x:.1f},{y:.1f}" for x, y in (vertex(i, ratio) for i in range(count)))

    grids = "".join(
        f'<polygon points="{poly(r)}" fill="none" stroke="#e5e7eb" stroke-dasharray="3 3"/>'
        for r in (0.25, 0.5, 0.75, 1.0)
    )
    axes = "".join(
        f'<line x1="{RADAR_CENTER}" y1="{RADAR_CENTER}" x2="{vertex(i, 1.0)[0]:.1f}"'
        f' y2="{vertex(i, 1.0)[1]:.1f}" stroke="#e5e7eb"/>'
        for i in range(count)
    )
    data_poly = " ".join(
        f"{x:.1f},{y:.1f}"
        for x, y in (vertex(i, float(score) / 100.0) for i, (_, score) in enumerate(points))
    )
    labels = []
    for i, (name, _) in enumerate(points):
        lx, ly = vertex(i, 1.18)
        anchor = "middle"
        if lx < RADAR_CENTER - 10:
            anchor = "end"
        elif lx > RADAR_CENTER + 10:
            anchor = "start"
        labels.append(
            f'<text x="{lx:.1f}" y="{ly:.1f}" text-anchor="{anchor}" dominant-baseline="middle"'
            f' font-size="12" font-weight="600" fill="#4b5563">{_esc(name)}</text>'
        )
    dots = "".join(
        f'<circle cx="{x:.1f}" cy="{y:.1f}" r="3.5" fill="#5b6be0" stroke="#fff" stroke-width="1.5"/>'
        for x, y in (vertex(i, float(score) / 100.0) for i, (_, score) in enumerate(points))
    )
    return (
        # viewBox 四周留出轴标签空间（中文标签最宽约 5 字 × 12px）
        f'<svg viewBox="-60 -12 340 246" width="300" height="217" role="img">'
        f"{grids}{axes}"
        f'<polygon points="{data_poly}" fill="rgba(91,107,224,0.18)" stroke="#5b6be0" stroke-width="2"/>'
        f"{dots}{''.join(labels)}</svg>"
    )


def render_affinity_report(
    conversation: Dict[str, Any],
    result: Any,
    history: List[Dict[str, Any]],
    profile: Optional[Dict[str, Any]],
    basic_stats: Dict[str, Any],
) -> str:
    """组装单文件 HTML（所有动态文本过 _esc）。"""
    name = _esc(conversation.get("display_name") or "联系人")
    exported_at = _fmt_time(time.time())
    caliber = int(getattr(result, "analysis_caliber", 0) or 0)

    dims = []
    radar_points = []
    for key, label in _DIMENSIONS:
        dim = getattr(result, key, None)
        if dim is None or not getattr(dim, "weight", 0):
            continue
        dims.append((label, dim))
        radar_points.append((label, float(dim.score)))

    dim_cards = []
    for label, dim in dims:
        subs = "".join(
            f"<span>{_esc(_SUB_LABELS.get(k, k))} <b>{float(v):.1f}</b></span>"
            for k, v in (dim.sub_scores or {}).items()
        )
        weight_pct = int(round(float(dim.weight) * 100))
        dim_cards.append(
            f'<div class="dim card"><h3><span>{_esc(label)}'
            f'{"（加分项）" if weight_pct == 0 else ""}</span><em>{float(dim.score):.1f}'
            f'{" / " + str(weight_pct) + "%" if weight_pct else ""}</em></h3>'
            f'<div class="bar"><i style="width:{_pct(dim.score)}%"></i></div>'
            f'<div class="subs">{subs}</div>'
            f'<div class="subs" style="color:#9ca3af">{_esc(dim.interpretation or "")}</div></div>'
        )

    # 风险预警（独立于总分；缺席时说明）
    risk = getattr(result, "risk_assessment", None)
    if risk and isinstance(risk, dict):
        risk_rows = []
        for signal in (risk.get("signals") or {}).values():
            level = _esc(signal.get("level") or "未见异常")
            color = _LEVEL_COLORS.get(signal.get("level"), "#10b981")
            item_cls = {"预警": "alert", "留意": "watch"}.get(signal.get("level"), "normal")
            quotes = "".join(
                f'<div class="evidence">“{_esc(q)}”</div>' for q in (signal.get("evidence") or [])
            )
            note = f'<div class="evidence">{_esc(signal.get("note") or "")}</div>' if signal.get("note") else ""
            risk_rows.append(
                f'<div class="risk-item {item_cls}">'
                f'<div class="risk-head"><span>{_esc(signal.get("label") or "")}</span>'
                f'<span class="risk-level" style="background:{color}">{level}</span></div>'
                f'<div>{_esc(signal.get("stat_basis") or "")}</div>{quotes}{note}</div>'
            )
        risk_section = "".join(risk_rows) or '<p class="note">未产出风险信号。</p>'
    else:
        risk_section = '<p class="note">本次分析未包含风险预警（可能未启用 AI 关系评估）。</p>'

    # 历史趋势（跨口径行标记，不做跨口径对比）
    if history:
        hist_rows = "".join(
            f"<tr><td>{_fmt_time(row.get('created_at'))}</td>"
            f"<td>{float(row.get('overall_score') or 0):.1f}</td>"
            f"<td>v{_esc(row.get('analysis_version') or '?')}</td></tr>"
            for row in history
        )
        history_table = f"<table><tr><th>分析时间</th><th>总分</th><th>口径</th></tr>{hist_rows}</table>"
    else:
        history_table = '<p class="note">暂无历史分析记录。</p>'

    # 画像摘要
    if profile:
        tags = "".join(f"<span>{_esc(t)}</span>" for t in (profile.get("personality_tags") or []))
        profile_section = (
            f'<div class="tags">{tags}</div>'
            f'<p class="subs" style="font-size:12px">{_esc(profile.get("chat_style") or "")}</p>'
            f'<p class="subs" style="font-size:12px">{_esc(profile.get("relationship_note") or "")}</p>'
        )
    else:
        profile_section = '<p class="note">暂未生成联系人画像（建议页可生成）。</p>'

    llm_absent = getattr(result, "llm_relationship_absent_reason", None)
    llm_note = f'<p class="note">AI 关系评估未参与：{_esc(llm_absent)}</p>' if llm_absent else ""

    stats_line = (
        f"消息 {basic_stats.get('message_count', 0)} 条 · "
        f"活跃 {basic_stats.get('active_days', 0)} 天 · "
        f"跨度 {_fmt_time(basic_stats.get('first_ts'))} 至 {_fmt_time(basic_stats.get('last_ts'))}"
    )

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>{name} 关系体检报告</title>
<style>{_CSS}</style>
</head>
<body>
<div class="page">
  <h1>{name} · 关系体检报告</h1>
  <p class="meta">导出时间 {_esc(exported_at)} · 评分口径 v{_esc(caliber)} · 数据仅在本机生成</p>

  <div class="card score-hero">
    <div class="score-num">{float(result.overall_score):.0f}<small> /100</small></div>
    <div class="interpretation">{_esc(result.overall_interpretation or "")}<br>
      <span class="note">{_esc(stats_line)}</span></div>
    {_radar_svg(radar_points)}
  </div>

  <h2>维度详情</h2>
  <div class="dims">{''.join(dim_cards) or '<p class="note">无在场维度。</p>'}</div>
  {llm_note}

  <h2>风险预警</h2>
  <div class="card">{risk_section}</div>

  <h2>分析历史</h2>
  <div class="card">{history_table}
    <p class="note">口径版本不同的行之间分数不可直接比较。</p></div>

  <h2>联系人画像摘要</h2>
  <div class="card">{profile_section}</div>

  <p class="note">本报告由 Chrono Trace 在本地生成；好感度衡量关系质量，风险预警独立判定，二者互不抵扣。报告内含聊天原文摘录（风险证据等），外发分享前请知悉。</p>
</div>
</body>
</html>
"""


def export_affinity_report(conversation_id: int) -> Dict[str, Any]:
    """读取缓存分析结果并渲染报告，写入 chrono_trace_export 目录。"""
    from .affinity_analysis_service import AffinityAnalysisService
    from .affinity_history import get_recent_scores

    conn = get_db()
    conv_row = conn.execute(
        "SELECT display_name, account_wxid FROM conversations WHERE id = ?",
        (int(conversation_id),),
    ).fetchone()
    if conv_row is None:
        raise AffinityReportExportError("会话不存在")

    result = AffinityAnalysisService().get_scores(int(conversation_id))
    if result is None:
        raise AffinityReportExportError("该联系人还没有好感度分析结果，请先完成全面分析")

    history = []
    try:
        history = get_recent_scores(int(conversation_id), limit=HISTORY_LIMIT)
    except Exception as exc:
        logger.debug("[体检报告] 历史读取跳过: %s", exc)

    profile = None
    try:
        from ..realtime.contact_profiler import ContactProfiler

        profile = ContactProfiler().get_profile(
            str(conv_row[0] or ""), str(conv_row[1] or "")
        )
    except Exception as exc:
        logger.debug("[体检报告] 画像读取跳过: %s", exc)

    basic_row = conn.execute(
        """
        SELECT COUNT(*), COUNT(DISTINCT date(timestamp, 'unixepoch', 'localtime')),
               MIN(timestamp), MAX(timestamp)
        FROM messages WHERE conversation_id = ?
        """,
        (int(conversation_id),),
    ).fetchone()
    basic_stats = {
        "message_count": basic_row[0] or 0,
        "active_days": basic_row[1] or 0,
        "first_ts": basic_row[2],
        "last_ts": basic_row[3],
    }

    html_text = render_affinity_report(
        {"display_name": conv_row[0]}, result, history, profile, basic_stats
    )

    import tempfile
    from pathlib import Path

    safe_name = "".join(
        c for c in str(conv_row[0] or "联系人") if c.isalnum() or c in "（）()-_ "
    ).strip() or "contact"
    tmp_dir = Path(tempfile.gettempdir()) / "chrono_trace_export"
    tmp_dir.mkdir(exist_ok=True)
    file_path = tmp_dir / f"{safe_name}_关系体检报告_{time.strftime('%Y%m%d')}.html"
    file_path.write_text(html_text, encoding="utf-8")

    return {"ok": True, "file_path": str(file_path), "file_name": file_path.name}
