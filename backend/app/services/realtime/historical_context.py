"""Utilities for building historical suggestion context."""

from __future__ import annotations


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

    return historical_context
