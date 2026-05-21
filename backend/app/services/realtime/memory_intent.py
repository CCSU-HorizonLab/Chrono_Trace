"""Lightweight context labels for contact-scoped RAG retrieval."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import re
from typing import Any, Literal


MemoryIntentMode = Literal["none", "ambient", "memory_request", "relationship_context"]


@dataclass(frozen=True)
class MemoryIntent:
    should_retrieve: bool = False
    mode: MemoryIntentMode = "none"
    confidence: float = 0.0
    query: str = ""
    reason: str = "default_none"
    no_hit_eligible: bool = False
    continuation: bool = False
    manual_request: bool = False

    @classmethod
    def none(cls, reason: str = "default_none") -> "MemoryIntent":
        return cls(False, "none", 0.0, "", reason)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def detect_memory_intent(context: dict[str, Any] | None) -> MemoryIntent:
    """Return auxiliary labels; this no longer decides whether RAG is queried."""
    context = context or {}
    try:
        latest = _latest_user_input(context)
        manual_request = _is_manual_request(context)
        if not latest:
            return MemoryIntent(False, "none", 0.0, "", "empty_user_input", False, False, manual_request)

        inherited = _detect_continuation(context, latest, manual_request)
        if inherited:
            return inherited

        query = _build_query(latest)
        if _looks_like_relationship_question(latest):
            return MemoryIntent(
                True,
                "relationship_context",
                0.66,
                query,
                "relationship_context_signal",
                True,
                False,
                manual_request,
            )
        if _looks_like_history_question(latest):
            return MemoryIntent(
                True,
                "memory_request",
                0.68,
                query,
                "history_answer_signal",
                True,
                False,
                manual_request,
            )

        return MemoryIntent(
            False,
            "none",
            0.0,
            query,
            "no_direct_memory_label",
            False,
            False,
            manual_request,
        )
    except Exception:
        return MemoryIntent.none("detector_exception")


def _detect_continuation(
    context: dict[str, Any],
    latest: str,
    manual_request: bool,
) -> MemoryIntent | None:
    if _looks_like_topic_switch(latest) or not _looks_like_followup(latest):
        return None

    previous_turns = _previous_user_inputs(context)[-4:]
    for previous in reversed(previous_turns):
        if _looks_like_history_question(previous):
            return MemoryIntent(
                True,
                "memory_request",
                0.62,
                _build_query(f"{latest} {previous}"),
                "continued_recent_memory_context",
                True,
                True,
                manual_request,
            )
        if _looks_like_relationship_question(previous):
            return MemoryIntent(
                True,
                "relationship_context",
                0.60,
                _build_query(f"{latest} {previous}"),
                "continued_recent_relationship_context",
                True,
                True,
                manual_request,
            )

    for item in reversed(context.get("memory_intent_history") or []):
        if not isinstance(item, dict) or _contact_changed(context, item):
            continue
        if item.get("mode") in {"memory_request", "relationship_context"}:
            return MemoryIntent(
                True,
                item.get("mode"),
                0.60,
                _build_query(f"{latest} {item.get('query') or ''}"),
                f"continued_history_{item.get('mode')}",
                True,
                True,
                manual_request,
            )
    return None


def _latest_user_input(context: dict[str, Any]) -> str:
    user_context = context.get("user_context")
    if isinstance(user_context, list):
        for msg in reversed(user_context):
            if isinstance(msg, dict) and msg.get("role") == "user":
                return str(msg.get("content") or "").strip()
    if isinstance(user_context, str):
        return user_context.strip()
    trigger_context = context.get("trigger_context")
    if isinstance(trigger_context, dict):
        for key in ("user_input", "manual_input", "text", "content"):
            value = trigger_context.get(key)
            if value:
                return str(value).strip()
    return ""


def _previous_user_inputs(context: dict[str, Any]) -> list[str]:
    user_context = context.get("user_context")
    if not isinstance(user_context, list):
        return []
    return [
        str(msg.get("content") or "").strip()
        for msg in user_context[:-1]
        if isinstance(msg, dict) and msg.get("role") == "user" and str(msg.get("content") or "").strip()
    ]


def _is_manual_request(context: dict[str, Any]) -> bool:
    trigger_context = context.get("trigger_context")
    if isinstance(trigger_context, dict) and trigger_context.get("manual_input"):
        return True
    return str(context.get("trigger_type") or context.get("_trigger_type") or "") == "manual_request"


def _looks_like_history_question(text: str) -> bool:
    compact = _compact(text)
    if not compact:
        return False
    has_temporal_anchor = any(token in compact for token in ("上次", "上回", "之前", "以前", "那次", "刚刚", "上轮"))
    asks_detail = any(token in compact for token in ("啥", "什么", "哪", "谁", "记得", "不记得", "说过", "聊过", "提过"))
    has_actor = any(token in compact for token in ("她", "他", "对方", "我们", "ta", "TA"))
    reported_memory = any(token in compact for token in ("说过", "聊过", "提过", "说的", "聊的", "提的"))
    referential_anchor = any(token in compact for token in ("那个", "那家", "那次", "这个", "这家"))
    direct_lookup = any(token in compact for token in ("找一下", "找下", "查一下", "查下", "翻一下", "翻下"))
    return (
        (has_temporal_anchor and asks_detail and has_actor)
        or (has_actor and reported_memory and asks_detail)
        or (has_actor and referential_anchor and reported_memory)
        or (direct_lookup and (has_temporal_anchor or reported_memory))
    )


def _looks_like_relationship_question(text: str) -> bool:
    compact = _compact(text)
    if not compact:
        return False
    asks_strategy = any(token in compact for token in ("适合", "能不能", "可不可以", "该不该", "怎么", "如何"))
    relation_axis = any(token in compact for token in ("开玩笑", "玩笑", "调侃", "关系", "边界", "分寸", "相处", "沟通", "习惯", "风格"))
    has_actor = any(token in compact for token in ("这个人", "对方", "她", "他", "我们", "ta", "TA"))
    return asks_strategy and relation_axis and has_actor


def _looks_like_followup(text: str) -> bool:
    compact = _compact(text)
    if not compact:
        return False
    if len(compact) <= 12:
        return True
    return any(token in compact for token in ("那", "具体", "哪家", "哪个", "还有", "相关建议", "怎么回", "给建议", "话术"))


def _looks_like_topic_switch(text: str) -> bool:
    compact = _compact(text)
    return any(token in compact for token in ("换个话题", "不说这个", "先不聊", "另外", "新话题", "说别的"))


def _contact_changed(context: dict[str, Any], item: dict[str, Any]) -> bool:
    current = str(context.get("conversation_id") or context.get("_rag_conversation_id") or "")
    previous = str(item.get("conversation_id") or "")
    return bool(current and previous and current != previous)


def _build_query(text: str) -> str:
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    text = re.sub(r"[`\"'“”‘’]", "", text)
    return text[:180]


def _compact(text: str) -> str:
    return re.sub(r"\s+", "", str(text or "")).strip()
