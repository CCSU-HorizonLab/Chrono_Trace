"""Utilities for building historical suggestion context."""

from __future__ import annotations

from typing import Any, Callable

from .style_constraints import compute_style_constraints, load_cached_style_inputs


def compute_chart_stats(messages: list[dict] | None) -> dict:
    """Build lightweight chat statistics for prompt conditioning."""
    msgs = messages or []
    friend_msgs = [msg for msg in msgs if msg.get("sender_attr") == "friend"]
    self_msgs = [msg for msg in msgs if msg.get("sender_attr") == "self"]

    replied_count = 0
    for index, msg in enumerate(msgs):
        if msg.get("sender_attr") != "self":
            continue
        if any(next_msg.get("sender_attr") == "friend" for next_msg in msgs[index + 1:]):
            replied_count += 1

    positive_count = sum(1 for msg in friend_msgs if (msg.get("sentiment") or {}).get("polarity", 0) > 0)
    positive_rate = f"{positive_count / len(friend_msgs):.2f}" if friend_msgs else "N/A"
    reply_rate = f"{replied_count / len(self_msgs):.2f}" if self_msgs else "N/A"
    msg_ratio = f"{len(self_msgs)}:{len(friend_msgs)}" if (self_msgs or friend_msgs) else "N/A"

    gaps: list[int] = []
    for index in range(1, len(friend_msgs)):
        prev_ts = int(friend_msgs[index - 1].get("timestamp", 0) or 0)
        current_ts = int(friend_msgs[index].get("timestamp", 0) or 0)
        gap = current_ts - prev_ts
        if 0 < gap < 3600:
            gaps.append(gap)

    avg_reply_gap = round(sum(gaps) / len(gaps)) if gaps else None

    return {
        "reply_rate": reply_rate,
        "positive_rate": positive_rate,
        "msg_ratio": msg_ratio,
        "avg_reply_gap": avg_reply_gap,
        "friend_msg_count": len(friend_msgs),
        "self_msg_count": len(self_msgs),
    }


def build_historical_context(
    contact_profile: dict | None = None,
    emotion_summary: dict | None = None,
    recent_messages: list[dict] | None = None,
    self_profile_features: dict | None = None,
    preprocessed_stats=None,
    affinity_result=None,
) -> dict:
    """Build a compact optional historical context payload."""
    historical_context: dict = {}
    if contact_profile:
        historical_context["profile"] = contact_profile
    if emotion_summary:
        historical_context["emotion_summary"] = emotion_summary

    chart_stats = compute_chart_stats(recent_messages)
    if any(value not in (None, "N/A", 0) for value in chart_stats.values()):
        historical_context["chart_stats"] = chart_stats

    if any(
        value is not None
        for value in (self_profile_features, preprocessed_stats, affinity_result)
    ):
        style_constraints = compute_style_constraints(
            self_profile_features=self_profile_features,
            preprocessed_stats=preprocessed_stats,
            affinity_result=affinity_result,
        )
        historical_context["style_constraints"] = style_constraints.to_dict()

    return historical_context


def augment_context_with_historical_data(
    ctx: dict[str, Any],
    *,
    self_profile_cache: dict[str, Any] | None = None,
    load_style_inputs: Callable[[int | None], tuple[Any, Any] | tuple[None, None]] | None = None,
) -> dict[str, Any]:
    """Merge cached historical/style inputs into an existing runtime context."""
    conversation_id = None
    self_profile_features = None
    if self_profile_cache:
        conversation_id = self_profile_cache.get("conversation_id")
        self_profile_features = self_profile_cache.get("features_snapshot") or None

    style_loader = load_style_inputs or load_cached_style_inputs
    preprocessed_stats, affinity_result = style_loader(conversation_id)

    historical_context = ctx.get("historical_context", {})
    if not isinstance(historical_context, dict):
        historical_context = {}

    auto_historical = build_historical_context(
        contact_profile=ctx.get("contact_profile"),
        emotion_summary=ctx.get("emotion_summary"),
        recent_messages=ctx.get("recent_messages"),
        self_profile_features=self_profile_features,
        preprocessed_stats=preprocessed_stats,
        affinity_result=affinity_result,
    )
    for key, value in auto_historical.items():
        historical_context.setdefault(key, value)

    if historical_context:
        ctx["historical_context"] = historical_context
    if self_profile_features is not None:
        ctx.setdefault("self_profile_features", self_profile_features)
    if preprocessed_stats is not None:
        ctx.setdefault("preprocessed_stats", preprocessed_stats)
    if affinity_result is not None:
        ctx.setdefault("affinity_result", affinity_result)

    return historical_context
