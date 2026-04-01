"""Tests for shared suggestion trigger resolution."""

import os
import sys


sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.realtime.emotion_state_tracker import TriggerEvent
from app.services.realtime.trigger_resolver import (
    MANUAL_REQUEST_TRIGGER,
    resolve_suggestion_trigger,
)


def make_recent_message(
    content: str,
    *,
    sender_attr: str = "other",
    polarity: int = 0,
    intensity: float = 0.0,
    confidence: float = 0.8,
    timestamp: int = 1,
    message_type: int = 1,
):
    return {
        "content": content,
        "sender_attr": sender_attr,
        "timestamp": timestamp,
        "message_type": message_type,
        "sentiment": {
            "polarity": polarity,
            "intensity": intensity,
            "confidence": confidence,
            "rules_applied": [],
        },
    }


class FakeTracker:
    def __init__(self, trend: str, latest_intent: str | None = None):
        self._trend = trend
        self._latest_intent = latest_intent

    def get_emotion_summary(self):
        return {
            "window_size": 3,
            "avg_polarity": 0.0,
            "avg_intensity": 0.0,
            "trend": self._trend,
            "recent_polarities": [0, 0, 0],
            "latest_intent": self._latest_intent,
        }


def test_explicit_trigger_has_highest_priority():
    resolved = resolve_suggestion_trigger(
        mode="manual",
        explicit_trigger_type="silence",
        explicit_trigger_context={"silent_seconds": 600},
        runtime_triggers=[TriggerEvent("topic_cooling", 1.0, "medium", {"drop_ratio": 0.8})],
        emotion_tracker=FakeTracker("negative"),
    )

    assert resolved.trigger_type == "silence"
    assert resolved.source == "explicit"
    assert resolved.trigger_context["silent_seconds"] == 600


def test_runtime_trigger_beats_fallback():
    resolved = resolve_suggestion_trigger(
        mode="full_auto",
        runtime_triggers=[TriggerEvent("topic_cooling", 1.0, "medium", {"drop_ratio": 0.8})],
        emotion_tracker=FakeTracker("negative"),
    )

    assert resolved.trigger_type == "topic_cooling"
    assert resolved.source == "runtime_trigger"


def test_full_auto_neutral_without_runtime_trigger_skips_generation():
    resolved = resolve_suggestion_trigger(
        mode="full_auto",
        emotion_tracker=FakeTracker("neutral"),
    )

    assert resolved.trigger_type is None
    assert resolved.should_generate is False


def test_manual_mode_without_trigger_uses_manual_request():
    resolved = resolve_suggestion_trigger(
        mode="manual",
        emotion_tracker=FakeTracker("neutral"),
    )

    assert resolved.trigger_type == MANUAL_REQUEST_TRIGGER
    assert resolved.source == "manual_request"
    assert resolved.should_generate is True


def test_full_auto_guard_skips_boundary_signal_without_runtime_trigger():
    resolved = resolve_suggestion_trigger(
        mode="full_auto",
        emotion_tracker=FakeTracker("negative", latest_intent="decline"),
    )

    assert resolved.trigger_type is None
    assert resolved.source == "full_auto_guard"
    assert resolved.should_generate is False


def test_recent_messages_only_return_trigger_from_latest_message():
    resolved = resolve_suggestion_trigger(
        mode="semi_auto",
        recent_messages=[
            make_recent_message("嗯", timestamp=1),
            make_recent_message("哦", timestamp=2),
            make_recent_message("好", timestamp=3),
            make_recent_message("这个我抖音刷到过", timestamp=4),
        ],
    )

    assert resolved.trigger_type is None
    assert resolved.should_generate is False


def test_recent_messages_preserve_message_type_for_trigger_inference():
    resolved = resolve_suggestion_trigger(
        mode="semi_auto",
        recent_messages=[
            make_recent_message("嗯", timestamp=1),
            make_recent_message("哦", timestamp=2),
            make_recent_message("好", timestamp=3, message_type=34),
        ],
    )

    assert resolved.trigger_type is None
    assert resolved.should_generate is False
