"""关系周报（docs/product-redesign-2026-11.md §6.4）。

每周 3-5 句趋势判读，落 weekly_reports 供脉搏页横幅与「展开周报」：
- 输入全是统计指标（四维差分/主动天平/回应双窗/周活跃对照），不含任何
  对话原文与人名——远程 LLM 只见数字，隐私红线（P4）天然满足，无需脱敏。
- 配置了激活 LLM 模型时走 LLM 生成；未配置或调用失败降级本地模板句，
  横幅不空。LLM 版完成后 UPSERT 覆盖同周模板版。
- 周期锚点：周一 00:00 本地时区（pulse_metrics.week_start_ts）。

指标查询与翻译复用 pulse_metrics（单一口径来源）。
"""
from __future__ import annotations

import json
import logging
import re
import threading
import time
from typing import Any, Dict, Optional

from .pulse_metrics import (
    dimension_deltas,
    directional_response_medians,
    fmt_minutes,
    initiative_summary,
    medians_to_minutes,
    temperature_label,
    week_start_ts,
    window_activity,
)

logger = logging.getLogger(__name__)

_DAY = 86400

# LLM 生成在后台线程去重（同一会话同周只跑一个）
_inflight: Dict[int, float] = {}
_inflight_lock = threading.Lock()

_DIM_LABELS = {
    "interaction_investment": "互动投入",
    "emotional_resonance": "情感共鸣",
    "closeness_signals": "亲近信号",
    "preference_compatibility": "喜好兼容度",
}


def _get_db():
    from ...db.connection import get_db

    return get_db()


def _current_caliber(conversation_id: int) -> Optional[int]:
    row = _get_db().execute(
        "SELECT analysis_version FROM affinity_scores WHERE conversation_id = ?"
        " ORDER BY created_at DESC LIMIT 1",
        (conversation_id,),
    ).fetchone()
    return int(row[0]) if row else None


def collect_snapshot(conversation_id: int) -> Optional[Dict[str, Any]]:
    """周报输入快照。无好感历史（从未分析）返回 None。"""
    caliber = _current_caliber(conversation_id)
    if caliber is None:
        return None
    now = int(time.time())
    ws = week_start_ts(now)
    return {
        "week_start": time.strftime("%Y-%m-%d", time.localtime(ws)),
        "deltas": dimension_deltas(conversation_id, caliber),
        "initiative": initiative_summary(conversation_id),
        "response_recent": medians_to_minutes(
            directional_response_medians(conversation_id, now - 30 * _DAY, now)
        ),
        "response_prev": medians_to_minutes(
            directional_response_medians(conversation_id, now - 60 * _DAY, now - 30 * _DAY)
        ),
        "week_now": window_activity(conversation_id, ws, ws + 7 * _DAY),
        "week_prev": window_activity(conversation_id, ws - 7 * _DAY, ws),
    }


# ----------------------------------------------------------------------
# 模板版（本地规则，LLM 缺席兜底）
# ----------------------------------------------------------------------

def _trend_sentence(deltas: Optional[Dict[str, Any]]) -> str:
    if not deltas:
        return ""
    overall = deltas.get("overall")
    if overall is None:
        return ""
    line = f"关系温度 {round(overall)}（{temperature_label(overall)}）"
    delta = deltas.get("overall_delta")
    if delta is not None:
        line += f"，较上次分析{'上升' if delta >= 0 else '下降'} {abs(delta):.1f} 分"
    moved = [
        f"{_DIM_LABELS[k]}{'上升' if v >= 0 else '下降'} {abs(v):.1f}"
        for k, v in (deltas.get("dim_deltas") or {}).items()
        if v is not None and abs(v) >= 3
    ]
    if moved:
        line += f"（{'、'.join(moved[:2])}）"
    return line + "。"


def _week_activity_sentence(now_w: Dict[str, Any], prev_w: Dict[str, Any]) -> str:
    if not now_w.get("messages"):
        return "本周没有新消息，对话处于停歇。"
    parts = [f"本周 {now_w['messages']} 条消息"]
    if prev_w.get("messages"):
        pct = (now_w["messages"] - prev_w["messages"]) * 100.0 / prev_w["messages"]
        if abs(pct) >= 20:
            parts.append(f"较上周{'增多' if pct > 0 else '减少'} {abs(pct):.0f}%")
    me = now_w.get("me_pct")
    if me is not None and (me >= 65 or me <= 35):
        parts.append("主要由你输出" if me >= 65 else "TA 的输出更多")
    if now_w.get("late_night"):
        parts.append(f"深夜对话 {now_w['late_night']} 次")
    return "，".join(parts) + "。"


def _response_sentence(recent: Optional[Dict[str, Any]], prev: Optional[Dict[str, Any]]) -> str:
    if not recent:
        return ""
    ta, me = recent.get("ta_to_me_median_min"), recent.get("me_to_ta_median_min")
    if ta is None or me is None:
        return ""
    ta_prev = (prev or {}).get("ta_to_me_median_min")
    if ta_prev is not None and abs(ta - ta_prev) >= 1 and ta_prev > 0:
        pct = (ta - ta_prev) * 100.0 / ta_prev
        if abs(pct) >= 25:
            faster = "变快" if pct < 0 else "变慢"
            return (
                f"TA 回你的中位回复约 {fmt_minutes(ta)}，近一个月{faster} "
                f"{abs(pct):.0f}%；你回 TA 约 {fmt_minutes(me)}。"
            )
    return f"TA 回你中位约 {fmt_minutes(ta)}，你回 TA 约 {fmt_minutes(me)}，节奏稳定。"


def template_report(snapshot: Dict[str, Any]) -> str:
    """3-4 句本地判读：趋势 + 周活跃 + 回应节奏。"""
    parts = [
        p for p in (
            _trend_sentence(snapshot.get("deltas")),
            _week_activity_sentence(snapshot.get("week_now") or {}, snapshot.get("week_prev") or {}),
            _response_sentence(snapshot.get("response_recent"), snapshot.get("response_prev")),
        )
        if p
    ]
    if not parts:
        parts.append("本周数据不足，暂无可说的趋势。")
    return "".join(parts[:4])


# ----------------------------------------------------------------------
# LLM 版（配置了激活模型时）
# ----------------------------------------------------------------------

def _render_prompt(snapshot: Dict[str, Any]) -> str:
    d = snapshot.get("deltas") or {}
    dims = "；".join(
        f"{_DIM_LABELS[k]} {v}"
        + (f"（较上次 {('+' if (d.get('dim_deltas') or {}).get(k, 0) >= 0 else '')}{(d.get('dim_deltas') or {}).get(k)}）"
           if (d.get("dim_deltas") or {}).get(k) is not None else "")
        for k, v in (d.get("dims") or {}).items() if v is not None
    ) or "暂无维度数据"
    overall = d.get("overall")
    delta = d.get("overall_delta")
    trend = f"总分 {overall}" + (f"（较上次 {'+' if delta >= 0 else ''}{delta}）" if delta is not None else "") if overall is not None else "暂无分析"
    r, p = snapshot.get("response_recent") or {}, snapshot.get("response_prev") or {}
    wn, wp = snapshot.get("week_now") or {}, snapshot.get("week_prev") or {}
    init = snapshot.get("initiative") or {}
    return (
        f"【关系温度】{trend}\n"
        f"【四维】{dims}\n"
        f"【本周】消息 {wn.get('messages', 0)} 条（上周 {wp.get('messages', 0)} 条），"
        f"你发 {wn.get('me_pct')}%，深夜 {wn.get('late_night', 0)} 次\n"
        f"【回应】TA 回你中位 {fmt_minutes(r['ta_to_me_median_min']) if r.get('ta_to_me_median_min') is not None else '无数据'}"
        f"（前 30 天 {fmt_minutes(p['ta_to_me_median_min']) if p.get('ta_to_me_median_min') is not None else '无数据'}）；"
        f"你回 TA 中位 {fmt_minutes(r['me_to_ta_median_min']) if r.get('me_to_ta_median_min') is not None else '无数据'}\n"
        f"【主动性】话题发起你占 {init.get('me_pct')}%（全期统计，{init.get('total_sessions', 0)} 段对话）\n"
        "请写本周关系判读。"
    )


def llm_report(snapshot: Dict[str, Any]) -> Optional[str]:
    """LLM 生成周报正文；未配置模型或失败返回 None（调用方保模板版）。"""
    try:
        from ..realtime.rag.fact_llm import get_active_model_config
        from ..realtime.llm_http import post_json_with_retries

        model = get_active_model_config()
        if not model:
            return None
        base_url = str(model.get("api_base_url") or "").rstrip("/")
        if not base_url:
            return None
        from ..realtime.llm_http import apply_deep_call_effort

        headers = {}
        api_key = str(model.get("api_key") or "").strip()
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        payload = {
            "model": model.get("model_id"),
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "你是关系分析师，基于统计指标写每周关系判读。"
                        "输出 3-5 句中文正文：不要标题、不要列表、不要 markdown；"
                        "语气克制诚实，好坏都直说，每句都锚定给定数字，不臆测、不建议分手或表白。"
                    ),
                },
                {"role": "user", "content": _render_prompt(snapshot)},
            ],
            "temperature": 0.3,
            # 500 会被思考模型的思维链吃尽（实测截断出半截推理文本），800 给正文留足
            "max_tokens": 800,
            "stream": False,
        }
        # 思考模型定档 medium + 模型级 extra_body 显式优先（与 history_qa/group_summary 同源）
        apply_deep_call_effort(payload, model)
        body = post_json_with_retries(
            url=f"{base_url}/chat/completions",
            payload=payload,
            headers=headers,
            timeout=60,
            max_retries=1,
            log=logger.debug,
            log_prefix="[关系周报]",
        )
        message = (body.get("choices") or [{}])[0].get("message") or {}
        # 不兜底 reasoning_content：思维链是模型自言自语不是正文，当判读
        # 交付会输出半成品推理草稿；content 空就交给模板版（调用方兜底）
        content = str(message.get("content") or "").strip()
        # 部分部署把思考段以 <think>…</think> 内联进 content，剥掉再交付
        if "<think>" in content:
            content = re.sub(r"<think>.*?</think>", "", content, flags=re.S).strip()
        return content or None
    except Exception as exc:
        logger.warning("[关系周报] LLM 生成失败，保留模板版: %s", exc)
        return None


# ----------------------------------------------------------------------
# 落库与读出口
# ----------------------------------------------------------------------

def _upsert(conversation_id: int, week_start: str, verdict: str, source: str, snapshot: Dict[str, Any]) -> None:
    now = int(time.time())
    _get_db().execute(
        """
        INSERT INTO weekly_reports(conversation_id, week_start, verdict, source, snapshot_json, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(conversation_id, week_start) DO UPDATE SET
            verdict = excluded.verdict, source = excluded.source,
            snapshot_json = excluded.snapshot_json, updated_at = excluded.updated_at
        """,
        (conversation_id, week_start, verdict, source, json.dumps(snapshot, ensure_ascii=False), now, now),
    )
    _get_db().commit()


def get_current(conversation_id: int) -> Optional[Dict[str, Any]]:
    """读本周周报（不存在返回 None）。"""
    week_start = time.strftime("%Y-%m-%d", time.localtime(week_start_ts(int(time.time()))))
    row = _get_db().execute(
        "SELECT week_start, verdict, source, snapshot_json, updated_at"
        " FROM weekly_reports WHERE conversation_id = ? AND week_start = ?",
        (conversation_id, week_start),
    ).fetchone()
    if not row:
        return None
    try:
        snapshot = json.loads(row[3] or "{}")
    except Exception:
        snapshot = {}
    return {
        "week_start": row[0],
        "verdict": row[1],
        "source": row[2],
        "snapshot": snapshot,
        "updated_at": int(row[4]),
    }


def ensure_template(conversation_id: int) -> Optional[Dict[str, Any]]:
    """本周无周报时同步落一版模板句（秒级），返回本周周报。

    无分析基线（collect_snapshot 为 None）返回 None。
    """
    current = get_current(conversation_id)
    if current:
        return current
    snapshot = collect_snapshot(conversation_id)
    if snapshot is None:
        return None
    _upsert(conversation_id, snapshot["week_start"], template_report(snapshot), "template", snapshot)
    return get_current(conversation_id)


def request_llm_upgrade(conversation_id: int) -> Dict[str, Any]:
    """后台线程升级本周周报为 LLM 版（同会话去重；失败保留模板版）。

    返回 {ok, started, reason?}：未配模型/无基线/已在跑 → started=False。
    """
    with _inflight_lock:
        if conversation_id in _inflight and time.time() - _inflight[conversation_id] < 300:
            return {"ok": True, "started": False, "reason": "already_running"}
        _inflight[conversation_id] = time.time()

    def _worker():
        try:
            snapshot = collect_snapshot(conversation_id)
            if snapshot is None:
                return
            verdict = llm_report(snapshot)
            if verdict:
                _upsert(conversation_id, snapshot["week_start"], verdict, "llm", snapshot)
                logger.info("[关系周报] LLM 版已落库 conversation=%s", conversation_id)
        except Exception as exc:
            logger.warning("[关系周报] 后台升级失败 conversation=%s: %s", conversation_id, exc)
        finally:
            with _inflight_lock:
                _inflight.pop(conversation_id, None)

    threading.Thread(target=_worker, name=f"weekly-llm-{conversation_id}", daemon=True).start()
    return {"ok": True, "started": True}


def llm_configured() -> bool:
    try:
        from ..realtime.rag.fact_llm import get_active_model_config

        return bool(get_active_model_config())
    except Exception:
        return False
