"""Focused tests for full_auto trigger selection in RealtimeMonitorService."""

import os
import sys


sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.realtime.emotion_state_tracker import TriggerEvent
from app.services.realtime.monitor_service import RealtimeMonitorService


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


def _make_service() -> RealtimeMonitorService:
    service = RealtimeMonitorService()
    service._suggestion_config = {
        "trigger_mode": "full_auto",
        "intent": "maintain",
        "auto_rate_limit": 10,
        "engine_type": "llm",
    }
    service._last_auto_suggestion_time = 0
    return service


def test_select_full_auto_trigger_prefers_runtime_trigger():
    service = _make_service()
    service.emotion_tracker = FakeTracker("neutral")

    trigger_type, trigger_context = service._select_full_auto_trigger(
        [TriggerEvent("topic_cooling", 123.0, "medium", {"drop_ratio": 0.8})]
    )

    assert trigger_type == "topic_cooling"
    assert trigger_context["drop_ratio"] == 0.8


def test_select_full_auto_trigger_skips_neutral_without_runtime_trigger():
    service = _make_service()
    service.emotion_tracker = FakeTracker("neutral")

    trigger_type, trigger_context = service._select_full_auto_trigger([])

    assert trigger_type is None
    assert trigger_context == {}


def test_select_full_auto_trigger_uses_negative_trend_fallback():
    service = _make_service()
    service.emotion_tracker = FakeTracker("negative")

    trigger_type, trigger_context = service._select_full_auto_trigger([])

    assert trigger_type == "negative_streak"
    assert trigger_context["source"] == "full_auto_fallback"


def test_full_auto_skip_does_not_consume_rate_limit():
    service = _make_service()
    service.emotion_tracker = FakeTracker("neutral")

    service._handle_full_auto_suggestion({"polarity": 0}, runtime_triggers=[])

    assert service._last_auto_suggestion_time == 0
