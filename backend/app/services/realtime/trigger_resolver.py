"""Shared trigger resolution for suggestion entrypoints."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .emotion_state_tracker import EmotionStateTracker


MANUAL_REQUEST_TRIGGER = "manual_request"


@dataclass
class ResolvedSuggestionTrigger:
    trigger_type: str | None
    trigger_context: dict[str, Any] = field(default_factory=dict)
    source: str = "none"
    should_generate: bool = False


def _normalize_sentiment(message: dict) -> dict:
    sentiment = message.get("sentiment") or {}
    return {
        "polarity": sentiment.get("polarity", 0),
        "intensity": sentiment.get("intensity", 0.0),
        "confidence": sentiment.get("confidence", 0.0),
        "rules_applied": sentiment.get("rules_applied", sentiment.get("rules", [])),
    }


def resolve_runtime_trigger_from_messages(
    messages: list[dict],
) -> ResolvedSuggestionTrigger:
    """Replay helper: infer the latest trigger from a recent message window."""
    tracker = EmotionStateTracker()
    last_event = None

    for message in messages:
        events = tracker.update(
            _normalize_sentiment(message),
            {
                "content": message.get("content", ""),
                "sender_attr": "friend" if message.get("sender_attr") == "other" else message.get("sender_attr"),
                "timestamp": message.get("timestamp"),
            },
            current_time=float(message.get("timestamp", 0) or 0),
        )
        if events:
            last_event = events[-1]

    if not last_event:
        return ResolvedSuggestionTrigger(
            trigger_type=None,
            trigger_context={},
            source="recent_messages",
            should_generate=False,
        )

    return ResolvedSuggestionTrigger(
        trigger_type=last_event.trigger_type,
        trigger_context=last_event.context or {},
        source="recent_messages",
        should_generate=True,
    )


def resolve_suggestion_trigger(
    *,
    mode: str,
    explicit_trigger_type: str | None = None,
    explicit_trigger_context: dict[str, Any] | None = None,
    runtime_triggers: list[Any] | None = None,
    emotion_tracker: Any | None = None,
    recent_messages: list[dict] | None = None,
) -> ResolvedSuggestionTrigger:
    """
    Resolve a single trigger across auto/full_auto/manual entrypoints.

    Priority:
    1. explicit trigger
    2. runtime trigger events from EmotionStateTracker
    3. replay/manual recent_messages inference
    4. full_auto trend fallback
    5. manual_request fallback
    """
    if explicit_trigger_type:
        return ResolvedSuggestionTrigger(
            trigger_type=explicit_trigger_type,
            trigger_context=explicit_trigger_context or {},
            source="explicit",
            should_generate=True,
        )

    runtime_triggers = runtime_triggers or []
    if runtime_triggers:
        primary_trigger = runtime_triggers[0]
        return ResolvedSuggestionTrigger(
            trigger_type=primary_trigger.trigger_type,
            trigger_context=primary_trigger.context or {},
            source="runtime_trigger",
            should_generate=True,
        )

    if recent_messages:
        inferred = resolve_runtime_trigger_from_messages(recent_messages)
        if inferred.should_generate:
            return inferred

    if mode == "full_auto" and emotion_tracker:
        summary = emotion_tracker.get_emotion_summary()
        trend = summary.get("trend")
        if trend == "negative":
            return ResolvedSuggestionTrigger(
                trigger_type="negative_streak",
                trigger_context={"source": "full_auto_fallback", "trend": trend},
                source="full_auto_fallback",
                should_generate=True,
            )
        if trend == "positive":
            return ResolvedSuggestionTrigger(
                trigger_type="positive_window",
                trigger_context={"source": "full_auto_fallback", "trend": trend},
                source="full_auto_fallback",
                should_generate=True,
            )

    if mode == "manual":
        return ResolvedSuggestionTrigger(
            trigger_type=MANUAL_REQUEST_TRIGGER,
            trigger_context={"source": "manual_request"},
            source="manual_request",
            should_generate=True,
        )

    return ResolvedSuggestionTrigger(
        trigger_type=None,
        trigger_context={},
        source="none",
        should_generate=False,
    )
