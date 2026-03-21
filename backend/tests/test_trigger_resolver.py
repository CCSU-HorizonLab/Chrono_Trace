"""Tests for shared suggestion trigger resolution."""

import os
import sys


sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.realtime.emotion_state_tracker import TriggerEvent
from app.services.realtime.trigger_resolver import (
    MANUAL_REQUEST_TRIGGER,
    resolve_suggestion_trigger,
)


class FakeTracker:
    def __init__(self, trend: str):
        self._trend = trend

    def get_emotion_summary(self):
        return {
            "window_size": 3,
            "avg_polarity": 0.0,
            "avg_intensity": 0.0,
            "trend": self._trend,
            "recent_polarities": [0, 0, 0],
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
