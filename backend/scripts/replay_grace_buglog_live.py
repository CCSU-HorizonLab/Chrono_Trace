"""Quasi-production LLM replay for Grace.'s bug.log scenarios."""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable


sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.realtime.contact_profiler import ContactProfiler
from app.services.realtime.feedback_rule_extractor import FeedbackRuleExtractor
from app.services.realtime.historical_context import build_historical_context
from app.services.realtime.llm_engine import LLMSuggestionEngine
from app.services.realtime.self_profiler import SelfProfiler
from app.services.realtime.session_thread_service import SessionThreadService
from app.services.realtime.style_constraints import StyleConstraints, load_cached_style_inputs
from app.services.realtime.trigger_resolver import resolve_suggestion_trigger


DISPLAY_NAME = "Grace."
LOG_DIR = Path(__file__).resolve().parents[1] / "data" / "logs"
DEFAULT_MULTI_CONTACT_LIMIT = 4
REAL_HISTORY_MESSAGE_LIMIT = 240
REAL_HISTORY_WINDOW_SIZE = 10
REAL_HISTORY_MAX_CASES_PER_CONTACT = 4
REAL_HISTORY_TRIGGER_LIMIT = 2
REAL_HISTORY_NO_TRIGGER_LIMIT = 2
REAL_HISTORY_MIN_GAP = 6


def _configure_utf8_stdio() -> None:
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8")
            except ValueError:
                continue


_configure_utf8_stdio()


def build_messages(items: list[tuple]) -> list[dict]:
    return [
        {
            "id": index,
            "timestamp": index,
            "sender_attr": sender_attr,
            "content": content,
            "sentiment": {
                "polarity": polarity,
                "intensity": intensity,
                "confidence": confidence,
                "rules": [],
            },
        }
        for index, (sender_attr, content, polarity, intensity, confidence) in enumerate(
            [_normalize_message_item(item) for item in items],
            start=1,
        )
    ]


def _normalize_message_item(item: tuple) -> tuple[str, str, int, float, float]:
    if len(item) == 3:
        sender_attr, content, polarity = item
        intensity = float(polarity) if polarity != 0 else 0.0
        confidence = 0.9
        return sender_attr, content, polarity, intensity, confidence
    if len(item) == 4:
        sender_attr, content, polarity, intensity = item
        return sender_attr, content, polarity, intensity, 0.9
    if len(item) == 5:
        sender_attr, content, polarity, intensity, confidence = item
        return sender_attr, content, polarity, intensity, confidence
    raise ValueError(f"Unsupported message item shape: {item}")


def build_emotion_summary(messages: list[dict]) -> dict:
    other_messages = [msg for msg in messages if msg.get("sender_attr") == "other"][-5:]
    if not other_messages:
        return {
            "window_size": 0,
            "avg_polarity": 0.0,
            "avg_intensity": 0.0,
            "trend": "neutral",
            "recent_polarities": [],
        }

    polarities = [(msg.get("sentiment") or {}).get("polarity", 0) for msg in other_messages]
    intensities = [(msg.get("sentiment") or {}).get("intensity", 0.0) for msg in other_messages]
    avg_polarity = sum(polarities) / len(polarities)
    if avg_polarity > 0.3:
        trend = "positive"
    elif avg_polarity < -0.3:
        trend = "negative"
    else:
        trend = "neutral"
    return {
        "window_size": len(other_messages),
        "avg_polarity": round(avg_polarity, 3),
        "avg_intensity": round(sum(intensities) / len(intensities), 3),
        "trend": trend,
        "recent_polarities": polarities,
    }


CASES = {
    "hongkong_study_plan": {
        "trigger_type": "topic_cooling",
        "notes": "对方仍在提供具体计划，不应误判冷场",
        "messages": build_messages(
            [
                ("self", "等我毕业再说吧。", 0),
                ("self", "挺好", 0),
                ("self", "毕业么 你打算考研还是就业啊", 0),
                ("other", "看能不能去香港留学", 0),
            ]
        ),
    },
    "dorm_annoyance": {
        "trigger_type": "emotion_shift",
        "notes": "负面抱怨后跟非语言内容，不应继续放大成情绪突变建议",
        "messages": build_messages(
            [
                ("other", "我们被记也不会为难学委，毕竟知道是导员要求的，不燃学委也不抓...", 0),
                ("self", "所以说啊 我记别人 就没人跟我急眼的 这个哥们是黑皮 有点喜...", 0),
                ("self", "宿舍里熬夜打CS 大吼大叫", 0),
                ("self", "幸好大三换寝室了", 0),
                ("other", "我很讨厌体育队还有打游戏大吼大叫", -1),
                ("other", "动画表情", 0),
            ]
        ),
    },
    "part_time_money": {
        "trigger_type": "emotion_shift",
        "notes": "职业/兼职规划是中性推进，不应误判情绪下坠",
        "messages": build_messages(
            [
                ("self", "土死了，玩烂梗自以为美式的", -1),
                ("self", "长沙这边做软件开发6k 我干服务员都有4k[Emm] 薪资低...", 0),
                ("other", "我打算毕业去兼职赚点小钱", 0),
            ]
        ),
    },
    "clear_negative_streak": {
        "trigger_type": "negative_streak",
        "notes": "连续三条明确负面，应生成克制的安抚/顺接建议",
        "messages": build_messages(
            [
                ("self", "今天怎么了", 0),
                ("other", "今天真有点累", -1, -0.65, 0.92),
                ("other", "而且事情都堆一起了", -1, -0.72, 0.93),
                ("other", "现在真的很烦", -1, -0.78, 0.95),
            ]
        ),
    },
    "clear_positive_window": {
        "trigger_type": "positive_window",
        "notes": "连续三条高强度正面，应给出顺势推进关系的自然话术",
        "messages": build_messages(
            [
                ("self", "今天怎么样", 0),
                ("other", "今天真的超开心", 1, 0.82, 0.94),
                ("other", "事情居然都顺顺利利", 1, 0.76, 0.92),
                ("other", "现在心情特别好", 1, 0.81, 0.95),
            ]
        ),
    },
    "decline_boundary": {
        "trigger_type": "no_trigger",
        "notes": "明确拒绝/收口场景，应避免系统主动介入",
        "messages": build_messages(
            [
                ("self", "周末一起去吗", 0),
                ("other", "不了 你和wwj去吧", -1, -0.72, 0.95),
            ]
        ),
    },
}


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _decode_content(content: Any) -> str:
    if isinstance(content, bytes):
        return content.decode("utf-8", errors="replace")
    if content is None:
        return ""
    return str(content)


def _looks_binaryish(text: str) -> bool:
    if not text:
        return False
    replacement_count = text.count("\ufffd")
    control_count = sum(
        1 for char in text if ord(char) < 32 and char not in ("\n", "\r", "\t")
    )
    suspicious_ratio = (replacement_count + control_count) / max(len(text), 1)
    return suspicious_ratio > 0.05


def _message_content_for_eval(message_type: int, content: Any) -> str:
    normalized = _decode_content(content).replace("\x00", "").strip()
    if normalized and not _looks_binaryish(normalized):
        return normalized
    fallback_by_type = {
        3: "图片",
        34: "语音",
        43: "视频通话",
        47: "动画表情",
    }
    if _safe_int(message_type) == 1:
        return ""
    return fallback_by_type.get(_safe_int(message_type), "")


def load_recent_conversation_messages(
    conversation_id: int,
    *,
    limit: int = REAL_HISTORY_MESSAGE_LIMIT,
) -> list[dict[str, Any]]:
    from app.db.connection import get_db

    conn = get_db()
    rows = conn.execute(
        """
        SELECT *
        FROM (
            SELECT
                m.id,
                m.is_sender,
                m.message_type,
                m.content,
                m.timestamp,
                s.polarity,
                s.intensity
            FROM messages m
            LEFT JOIN sentiment_cache s ON s.message_id = m.id
            WHERE m.conversation_id = ?
            ORDER BY m.timestamp DESC, m.id DESC
            LIMIT ?
        ) recent
        ORDER BY recent.timestamp ASC, recent.id ASC
        """,
        (conversation_id, limit),
    ).fetchall()

    messages: list[dict[str, Any]] = []
    for row in rows:
        content = _message_content_for_eval(row["message_type"], row["content"])
        if not content:
            continue

        sentiment = None
        if row["polarity"] is not None:
            sentiment = {
                "polarity": row["polarity"],
                "intensity": float(row["intensity"] or 0.0),
                "confidence": 1.0,
                "rules": [],
            }

        messages.append(
            {
                "id": row["id"],
                "timestamp": row["timestamp"],
                "sender_attr": "self" if row["is_sender"] else "other",
                "content": content,
                "message_type": row["message_type"],
                "sentiment": sentiment,
            }
        )
    return messages


def fill_missing_history_sentiments(
    messages: list[dict[str, Any]],
    *,
    sentiment_analyzer: Callable[[list[str]], list[dict[str, Any]]] | None = None,
) -> int:
    missing_indexes: list[int] = []
    texts: list[str] = []
    for index, message in enumerate(messages):
        if _safe_int(message.get("message_type"), 1) != 1:
            continue
        if message.get("sentiment") is not None:
            continue
        content = str(message.get("content") or "").strip()
        if not content:
            continue
        missing_indexes.append(index)
        texts.append(content)

    if not texts:
        return 0

    if sentiment_analyzer is None:
        from app.services.realtime.realtime_sentiment_service import RealtimeSentimentService

        analyzer = RealtimeSentimentService().analyze_batch
    else:
        analyzer = sentiment_analyzer

    results = analyzer(texts)
    for position, message_index in enumerate(missing_indexes):
        result = results[position] if position < len(results) else {}
        messages[message_index]["sentiment"] = {
            "polarity": _safe_int(result.get("polarity"), 0),
            "intensity": float(result.get("intensity") or 0.0),
            "confidence": float(result.get("confidence") or 0.0),
            "rules": list(result.get("rules_applied") or []),
        }
    return len(missing_indexes)


def _window_has_meaningful_dialogue(window: list[dict[str, Any]]) -> bool:
    if len(window) < 4:
        return False
    if window[-1].get("sender_attr") != "other":
        return False

    self_count = sum(1 for msg in window if msg.get("sender_attr") == "self")
    other_count = sum(1 for msg in window if msg.get("sender_attr") == "other")
    if self_count < 1 or other_count < 2:
        return False

    meaningful_count = sum(1 for msg in window if str(msg.get("content") or "").strip())
    return meaningful_count >= 4


def _is_far_enough_from_selected(
    end_index: int,
    selected_end_indexes: list[int],
    *,
    min_gap: int,
) -> bool:
    return all(abs(end_index - selected) >= min_gap for selected in selected_end_indexes)


def _real_history_note(window: list[dict[str, Any]], trigger_type: str | None) -> str:
    latest_message = window[-1]
    latest_dt = datetime.fromtimestamp(_safe_int(latest_message.get("timestamp"))).strftime(
        "%Y-%m-%d %H:%M"
    )
    preview = str(latest_message.get("content") or "").replace("\n", " ").strip()
    preview = preview[:40]
    trigger_label = trigger_type or "no_trigger"
    return f"真实历史窗口 | {latest_dt} | {trigger_label} | latest={preview}"


def select_real_history_case_entries(
    display_name: str,
    messages: list[dict[str, Any]],
    *,
    max_cases: int = REAL_HISTORY_MAX_CASES_PER_CONTACT,
    window_size: int = REAL_HISTORY_WINDOW_SIZE,
    trigger_limit: int = REAL_HISTORY_TRIGGER_LIMIT,
    no_trigger_limit: int = REAL_HISTORY_NO_TRIGGER_LIMIT,
    min_gap: int = REAL_HISTORY_MIN_GAP,
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for end_index in range(len(messages) - 1, -1, -1):
        window = messages[max(0, end_index - window_size + 1): end_index + 1]
        if not _window_has_meaningful_dialogue(window):
            continue

        computed_trigger, trigger_context = detect_trigger(window)
        latest_message_id = window[-1].get("id") or end_index
        case_name = f"real_history_{display_name}_{latest_message_id}"
        candidates.append(
            {
                "case_name": case_name,
                "payload": {
                    "trigger_type": computed_trigger or "no_trigger",
                    "notes": _real_history_note(window, computed_trigger),
                    "messages": window,
                    "source": "real_history",
                },
                "computed_trigger": computed_trigger,
                "trigger_context": trigger_context,
                "end_index": end_index,
                "trigger_key": computed_trigger or "no_trigger",
            }
        )

    selected: list[dict[str, Any]] = []
    selected_end_indexes: list[int] = []
    selected_trigger_types: set[str] = set()

    def _append_candidate(candidate: dict[str, Any]) -> bool:
        if candidate in selected:
            return False
        if not _is_far_enough_from_selected(
            candidate["end_index"],
            selected_end_indexes,
            min_gap=min_gap,
        ):
            return False
        selected.append(candidate)
        selected_end_indexes.append(candidate["end_index"])
        if candidate["computed_trigger"]:
            selected_trigger_types.add(candidate["computed_trigger"])
        return True

    for candidate in candidates:
        if len(selected) >= max_cases:
            break
        if not candidate["computed_trigger"]:
            continue
        if candidate["computed_trigger"] in selected_trigger_types:
            continue
        if sum(1 for item in selected if item["computed_trigger"]) >= trigger_limit:
            break
        _append_candidate(candidate)

    for candidate in candidates:
        if len(selected) >= max_cases:
            break
        if not candidate["computed_trigger"]:
            continue
        if sum(1 for item in selected if item["computed_trigger"]) >= trigger_limit:
            break
        _append_candidate(candidate)

    for candidate in candidates:
        if len(selected) >= max_cases:
            break
        if candidate["computed_trigger"]:
            continue
        if sum(1 for item in selected if not item["computed_trigger"]) >= no_trigger_limit:
            break
        _append_candidate(candidate)

    for candidate in candidates:
        if len(selected) >= max_cases:
            break
        _append_candidate(candidate)

    return selected


def build_context(display_name: str, case_name: str, payload: dict) -> dict:
    recent_messages = payload["messages"]
    emotion_summary = build_emotion_summary(recent_messages)
    contact_profile = ContactProfiler().get_profile(display_name)
    self_profile = SelfProfiler().get_profile(display_name)
    rules = FeedbackRuleExtractor().get_active_rules(display_name)
    memories = SessionThreadService().retrieve_relevant_memories(display_name, recent_messages)
    self_profile_features = None
    preprocessed_stats = None
    affinity_result = None
    if self_profile and not self_profile.get("expired"):
        self_profile_features = self_profile.get("features_snapshot") or None
        preprocessed_stats, affinity_result = load_cached_style_inputs(
            self_profile.get("conversation_id")
        )

    ctx = {
        "recent_messages": recent_messages,
        "emotion_summary": emotion_summary,
        "historical_context": build_historical_context(
            contact_profile=None if not contact_profile or contact_profile.get("expired") else contact_profile["profile"],
            emotion_summary=emotion_summary,
            recent_messages=recent_messages,
            self_profile_features=self_profile_features,
            preprocessed_stats=preprocessed_stats,
            affinity_result=affinity_result,
        ),
        "display_name": display_name,
        "trigger_context": {
            "source": "buglog_live_replay",
            "case": case_name,
            "active_rules_count": len(rules),
        },
    }
    if contact_profile and not contact_profile.get("expired"):
        ctx["contact_profile"] = contact_profile["profile"]
    if self_profile and not self_profile.get("expired"):
        ctx["self_profile"] = self_profile["profile"]
        ctx["self_profile_features"] = self_profile_features
    if preprocessed_stats is not None:
        ctx["preprocessed_stats"] = preprocessed_stats
    if affinity_result is not None:
        ctx["affinity_result"] = affinity_result
    if memories:
        ctx["relevant_memories"] = memories
    return ctx


def detect_trigger(messages: list[dict]) -> tuple[str | None, dict]:
    resolved = resolve_suggestion_trigger(
        mode="semi_auto",
        recent_messages=messages,
    )
    return resolved.trigger_type, resolved.trigger_context


def _resolve_style_constraints(ctx: dict) -> StyleConstraints:
    raw_constraints = (ctx.get("historical_context") or {}).get("style_constraints") or {}
    try:
        return StyleConstraints(**raw_constraints)
    except TypeError:
        return StyleConstraints()


def _evaluate_speeches(engine: LLMSuggestionEngine, ctx: dict, speeches: list[str]) -> dict[str, Any]:
    style_constraints = _resolve_style_constraints(ctx)
    emoji_policy = engine._emoji_policy(style_constraints)
    lengths = [len(speech) for speech in speeches]
    emoji_counts = [engine._count_emojis(speech) for speech in speeches]
    antipattern_hits = [speech for speech in speeches if engine._contains_ai_antipattern(speech)]

    if emoji_policy == "forbidden":
        emoji_ok = all(count == 0 for count in emoji_counts)
    elif emoji_policy == "limited":
        emoji_ok = all(count <= 1 for count in emoji_counts)
    else:
        emoji_ok = True

    max_len = style_constraints.max_speech_length or 48
    return {
        "style_constraints": style_constraints.to_dict(),
        "speech_count": len(speeches),
        "speech_lengths": lengths,
        "max_length_ok": all(length <= max_len for length in lengths),
        "emoji_policy": emoji_policy,
        "emoji_counts": emoji_counts,
        "emoji_ok": emoji_ok,
        "antipattern_hits": antipattern_hits,
    }


def _build_result_payload(
    engine: LLMSuggestionEngine,
    case_name: str,
    payload: dict,
    computed_trigger: str | None,
    trigger_context: dict,
    ctx: dict,
) -> dict[str, Any]:
    result_payload = {
        "case": case_name,
        "notes": payload.get("notes", ""),
        "historical_trigger_type": payload["trigger_type"],
        "computed_trigger_type": computed_trigger or "no_trigger",
        "trigger_context": trigger_context,
        "emotion_summary": ctx["emotion_summary"],
        "style_constraints": (ctx.get("historical_context") or {}).get("style_constraints"),
    }

    if computed_trigger is None:
        result_payload.update(
            {
                "summary": "[NO_TRIGGER] 当前代码不会为这段上下文生成建议",
                "speeches": [],
                "thought_process": "当前 EmotionStateTracker 没有命中任何触发条件，因此这段对话更接近自然推进而非系统介入。",
                "reply": None,
                "evaluation": _evaluate_speeches(engine, ctx, []),
            }
        )
        return result_payload

    try:
        result = engine.generate(computed_trigger, "maintain", ctx)
        result_payload.update(
            {
                "summary": result.summary,
                "speeches": result.speeches,
                "thought_process": result.thought_process,
                "reply": result.reply,
                "evaluation": _evaluate_speeches(engine, ctx, result.speeches),
            }
        )
    except Exception as exc:
        result_payload.update(
            {
                "summary": "[ERROR] 评估执行失败",
                "speeches": [],
                "thought_process": None,
                "reply": None,
                "error": str(exc),
                "evaluation": _evaluate_speeches(engine, ctx, []),
            }
        )
    return result_payload


def _finalize_report(
    display_name: str,
    cases_output: list[dict[str, Any]],
    *,
    mode: str = "standard",
    conversation_id: int | None = None,
    message_pool_size: int | None = None,
    sentiment_filled_count: int = 0,
) -> dict[str, Any]:
    generated_cases = [item for item in cases_output if item["computed_trigger_type"] != "no_trigger"]
    zero_emoji_cases = [
        item for item in generated_cases
        if (item.get("style_constraints") or {}).get("emoji_density", 0.0) < 0.01
    ]
    report = {
        "display_name": display_name,
        "generated_at": int(time.time()),
        "mode": mode,
        "case_count": len(cases_output),
        "generated_case_count": len(generated_cases),
        "no_trigger_case_count": len(cases_output) - len(generated_cases),
        "zero_emoji_cases_all_clean": all(
            item["evaluation"]["emoji_ok"] for item in zero_emoji_cases
        ) if zero_emoji_cases else True,
        "all_generated_cases_within_length_limit": all(
            item["evaluation"]["max_length_ok"] for item in generated_cases
        ) if generated_cases else True,
        "all_generated_cases_without_antipattern": all(
            not item["evaluation"]["antipattern_hits"] for item in generated_cases
        ) if generated_cases else True,
        "cases": cases_output,
    }
    if conversation_id is not None:
        report["conversation_id"] = conversation_id
    if message_pool_size is not None:
        report["message_pool_size"] = message_pool_size
    if sentiment_filled_count:
        report["sentiment_filled_count"] = sentiment_filled_count
    return report


def _evaluate_case_entries(
    display_name: str,
    case_entries: list[dict[str, Any]],
    *,
    mode: str = "standard",
    conversation_id: int | None = None,
    message_pool_size: int | None = None,
    sentiment_filled_count: int = 0,
) -> dict[str, Any]:
    engine = LLMSuggestionEngine(timeout=90)
    cases_output: list[dict[str, Any]] = []

    for entry in case_entries:
        case_name = entry["case_name"]
        payload = entry["payload"]
        computed_trigger = entry["computed_trigger"]
        trigger_context = entry["trigger_context"]
        ctx = build_context(display_name, case_name, payload)
        ctx.setdefault("trigger_context", {}).update(trigger_context)
        case_output = _build_result_payload(
            engine,
            case_name,
            payload,
            computed_trigger,
            trigger_context,
            ctx,
        )
        if entry.get("meta"):
            case_output.update(entry["meta"])
        cases_output.append(case_output)

    return _finalize_report(
        display_name,
        cases_output,
        mode=mode,
        conversation_id=conversation_id,
        message_pool_size=message_pool_size,
        sentiment_filled_count=sentiment_filled_count,
    )


def run_evaluation(display_name: str = DISPLAY_NAME) -> dict[str, Any]:
    case_entries: list[dict[str, Any]] = []
    for case_name, payload in CASES.items():
        computed_trigger, trigger_context = detect_trigger(payload["messages"])
        case_entries.append(
            {
                "case_name": case_name,
                "payload": payload,
                "computed_trigger": computed_trigger,
                "trigger_context": trigger_context,
            }
        )
    return _evaluate_case_entries(display_name, case_entries)


def run_real_history_evaluation(
    display_name: str,
    *,
    max_cases: int = REAL_HISTORY_MAX_CASES_PER_CONTACT,
    message_limit: int = REAL_HISTORY_MESSAGE_LIMIT,
    window_size: int = REAL_HISTORY_WINDOW_SIZE,
) -> dict[str, Any]:
    self_profile = SelfProfiler().get_profile(display_name)
    conversation_id = _safe_int((self_profile or {}).get("conversation_id"))
    if not conversation_id:
        return _finalize_report(
            display_name,
            [],
            mode="real_history",
        )

    messages = load_recent_conversation_messages(conversation_id, limit=message_limit)
    sentiment_filled_count = fill_missing_history_sentiments(messages)
    case_entries = select_real_history_case_entries(
        display_name,
        messages,
        max_cases=max_cases,
        window_size=window_size,
    )
    return _evaluate_case_entries(
        display_name,
        case_entries,
        mode="real_history",
        conversation_id=conversation_id,
        message_pool_size=len(messages),
        sentiment_filled_count=sentiment_filled_count,
    )


def _dedupe_display_names(display_names: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for display_name in display_names:
        if not display_name or display_name in seen:
            continue
        seen.add(display_name)
        deduped.append(display_name)
    return deduped


def list_cached_display_names(limit: int = DEFAULT_MULTI_CONTACT_LIMIT) -> list[str]:
    from app.db.connection import get_db

    conn = get_db()
    rows = conn.execute(
        """
        SELECT sp.display_name
        FROM self_profiles sp
        LEFT JOIN contact_profiles cp ON cp.display_name = sp.display_name
        ORDER BY sp.id DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    return _dedupe_display_names(
        [str(row["display_name"]) for row in rows if row and row["display_name"]]
    )


def run_multi_evaluation(display_names: list[str] | None = None) -> dict[str, Any]:
    if display_names is None:
        selected_display_names = list_cached_display_names()
    else:
        selected_display_names = _dedupe_display_names(list(display_names))
    reports = [run_evaluation(display_name) for display_name in selected_display_names]

    contact_summaries = []
    all_generated_cases = 0
    all_no_trigger_cases = 0
    all_zero_emoji_clean = True
    all_within_length_limit = True
    all_without_antipattern = True

    for report in reports:
        generated_cases = [
            case for case in report["cases"]
            if case["computed_trigger_type"] != "no_trigger"
        ]
        sample_speeches = []
        for case in generated_cases[:2]:
            sample_speeches.extend(case.get("speeches", [])[:2])

        contact_summaries.append(
            {
                "display_name": report["display_name"],
                "generated_case_count": report["generated_case_count"],
                "no_trigger_case_count": report["no_trigger_case_count"],
                "zero_emoji_cases_all_clean": report["zero_emoji_cases_all_clean"],
                "all_generated_cases_within_length_limit": report["all_generated_cases_within_length_limit"],
                "all_generated_cases_without_antipattern": report["all_generated_cases_without_antipattern"],
                "sample_speeches": sample_speeches[:4],
            }
        )

        all_generated_cases += report["generated_case_count"]
        all_no_trigger_cases += report["no_trigger_case_count"]
        all_zero_emoji_clean = all_zero_emoji_clean and report["zero_emoji_cases_all_clean"]
        all_within_length_limit = (
            all_within_length_limit and report["all_generated_cases_within_length_limit"]
        )
        all_without_antipattern = (
            all_without_antipattern and report["all_generated_cases_without_antipattern"]
        )

    return {
        "generated_at": int(time.time()),
        "mode": "standard_multi",
        "display_names": selected_display_names,
        "contact_count": len(reports),
        "generated_case_count": all_generated_cases,
        "no_trigger_case_count": all_no_trigger_cases,
        "all_zero_emoji_cases_clean": all_zero_emoji_clean,
        "all_generated_cases_within_length_limit": all_within_length_limit,
        "all_generated_cases_without_antipattern": all_without_antipattern,
        "contact_summaries": contact_summaries,
        "reports": reports,
    }


def run_real_history_multi_evaluation(
    display_names: list[str] | None = None,
    *,
    max_cases: int = REAL_HISTORY_MAX_CASES_PER_CONTACT,
    message_limit: int = REAL_HISTORY_MESSAGE_LIMIT,
    window_size: int = REAL_HISTORY_WINDOW_SIZE,
) -> dict[str, Any]:
    if display_names is None:
        selected_display_names = list_cached_display_names()
    else:
        selected_display_names = _dedupe_display_names(list(display_names))

    reports = [
        run_real_history_evaluation(
            display_name,
            max_cases=max_cases,
            message_limit=message_limit,
            window_size=window_size,
        )
        for display_name in selected_display_names
    ]

    contact_summaries = []
    all_generated_cases = 0
    all_no_trigger_cases = 0
    all_zero_emoji_clean = True
    all_within_length_limit = True
    all_without_antipattern = True
    total_sentiment_filled = 0

    for report in reports:
        generated_cases = [
            case for case in report["cases"]
            if case["computed_trigger_type"] != "no_trigger"
        ]
        sample_speeches = []
        sample_windows = []
        for case in report["cases"][:2]:
            sample_windows.append(case.get("notes", ""))
        for case in generated_cases[:2]:
            sample_speeches.extend(case.get("speeches", [])[:2])

        contact_summaries.append(
            {
                "display_name": report["display_name"],
                "conversation_id": report.get("conversation_id"),
                "message_pool_size": report.get("message_pool_size", 0),
                "generated_case_count": report["generated_case_count"],
                "no_trigger_case_count": report["no_trigger_case_count"],
                "sentiment_filled_count": report.get("sentiment_filled_count", 0),
                "zero_emoji_cases_all_clean": report["zero_emoji_cases_all_clean"],
                "all_generated_cases_within_length_limit": report["all_generated_cases_within_length_limit"],
                "all_generated_cases_without_antipattern": report["all_generated_cases_without_antipattern"],
                "sample_windows": sample_windows,
                "sample_speeches": sample_speeches[:4],
            }
        )

        all_generated_cases += report["generated_case_count"]
        all_no_trigger_cases += report["no_trigger_case_count"]
        total_sentiment_filled += report.get("sentiment_filled_count", 0)
        all_zero_emoji_clean = all_zero_emoji_clean and report["zero_emoji_cases_all_clean"]
        all_within_length_limit = (
            all_within_length_limit and report["all_generated_cases_within_length_limit"]
        )
        all_without_antipattern = (
            all_without_antipattern and report["all_generated_cases_without_antipattern"]
        )

    return {
        "generated_at": int(time.time()),
        "mode": "real_history_multi",
        "display_names": selected_display_names,
        "contact_count": len(reports),
        "generated_case_count": all_generated_cases,
        "no_trigger_case_count": all_no_trigger_cases,
        "total_sentiment_filled_count": total_sentiment_filled,
        "all_zero_emoji_cases_clean": all_zero_emoji_clean,
        "all_generated_cases_within_length_limit": all_within_length_limit,
        "all_generated_cases_without_antipattern": all_without_antipattern,
        "contact_summaries": contact_summaries,
        "reports": reports,
    }


def save_report(report: dict[str, Any]) -> Path:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    mode = report.get("mode")
    if mode == "real_history_multi":
        filename_prefix = "realtime_suggestion_eval_real_history_multi"
    elif mode == "real_history":
        filename_prefix = "realtime_suggestion_eval_real_history"
    elif "reports" in report:
        filename_prefix = "realtime_suggestion_eval_multi"
    else:
        filename_prefix = "realtime_suggestion_eval"
    output_path = LOG_DIR / f"{filename_prefix}_{report['generated_at']}.json"
    output_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return output_path


def main() -> None:
    report = run_real_history_multi_evaluation()
    output_path = save_report(report)
    print(f"Saved evaluation report to: {output_path}")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
