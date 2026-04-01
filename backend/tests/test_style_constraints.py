import os
import sys


sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.analysis.preprocessing_orchestrator import PreprocessedStatistics
from app.services.realtime.historical_context import (
    augment_context_with_historical_data,
    build_historical_context,
)
from app.services.realtime.monitor_service import RealtimeMonitorService
from app.services.realtime.style_constraints import compute_style_constraints


def test_compute_style_constraints_prefers_self_profile_avg_and_maps_styles():
    constraints = compute_style_constraints(
        self_profile_features={"user_msg_style": {"avg_chars_per_msg": 8.5}},
        preprocessed_stats=PreprocessedStatistics(
            total_message_count=100,
            average_message_length=18.0,
            emoji_message_count=0,
            sender_initiated_count=20,
            contact_initiated_count=80,
            nickname_message_count=0,
        ),
        affinity_result={"emotional_resonance": {"score": 32}},
    )

    assert constraints.avg_msg_length == 8.5
    assert constraints.max_speech_length == 21
    assert constraints.communication_type == "reactive"
    assert constraints.emotional_style == "cold"
    assert constraints.nickname_usage is False


def test_compute_style_constraints_defaults_without_history():
    constraints = compute_style_constraints()

    assert constraints.avg_msg_length == 0.0
    assert constraints.max_speech_length == 15
    assert constraints.communication_type == "balanced"
    assert constraints.emotional_style == "neutral"
    assert constraints.nickname_usage is False


def test_compute_style_constraints_uses_attitude_tendency_to_avoid_false_cold():
    constraints = compute_style_constraints(
        preprocessed_stats=PreprocessedStatistics(
            total_message_count=80,
            average_message_length=9.0,
            emoji_message_count=2,
            sender_initiated_count=30,
            contact_initiated_count=50,
            nickname_message_count=1,
            sender_nickname_message_count=1,
            contact_nickname_message_count=0,
        ),
        affinity_result={
            "emotional_resonance": {"score": 30},
            "attitude_tendency": {"score": 82},
        },
    )

    assert constraints.emotional_style == "neutral"


def test_compute_style_constraints_prefers_sender_nickname_usage_when_available():
    constraints = compute_style_constraints(
        preprocessed_stats=PreprocessedStatistics(
            total_message_count=80,
            average_message_length=9.0,
            emoji_message_count=2,
            sender_initiated_count=30,
            contact_initiated_count=50,
            nickname_message_count=3,
            sender_nickname_message_count=0,
            contact_nickname_message_count=3,
        ),
    )

    assert constraints.nickname_usage is False


def test_build_historical_context_includes_style_constraints():
    historical = build_historical_context(
        recent_messages=[{"sender_attr": "other", "content": "test", "timestamp": 100}],
        self_profile_features={"user_msg_style": {"avg_chars_per_msg": 6.0}},
        preprocessed_stats=PreprocessedStatistics(
            total_message_count=50,
            average_message_length=10.0,
            emoji_message_count=5,
            sender_initiated_count=35,
            contact_initiated_count=15,
            nickname_message_count=2,
        ),
        affinity_result={"emotional_resonance": {"score": 78}},
    )

    assert "style_constraints" in historical
    assert historical["style_constraints"]["max_speech_length"] == 15
    assert historical["style_constraints"]["communication_type"] == "proactive"
    assert historical["style_constraints"]["emotional_style"] == "warm"
    assert historical["style_constraints"]["nickname_usage"] is True


def test_build_historical_context_skips_default_style_constraints_without_inputs():
    historical = build_historical_context(
        recent_messages=[{"sender_attr": "other", "content": "test", "timestamp": 100}],
    )

    assert "style_constraints" not in historical


def test_monitor_service_builds_augmented_historical_context_from_cache(monkeypatch):
    service = RealtimeMonitorService()
    ctx = {
        "recent_messages": [
            {"sender_attr": "other", "content": "有点累", "timestamp": 100},
            {"sender_attr": "self", "content": "早点休息", "timestamp": 101},
        ]
    }

    monkeypatch.setattr(
        "app.services.realtime.historical_context.load_cached_style_inputs",
        lambda conversation_id: (
            PreprocessedStatistics(
                total_message_count=20,
                average_message_length=12.0,
                emoji_message_count=0,
                sender_initiated_count=4,
                contact_initiated_count=16,
                nickname_message_count=0,
                sender_nickname_message_count=0,
                contact_nickname_message_count=0,
            ),
            {
                "emotional_resonance": {"score": 35},
                "attitude_tendency": {"score": 35},
            },
        ),
    )

    service._build_augmented_historical_context(
        ctx,
        self_profile_cache={
            "conversation_id": 123,
            "features_snapshot": {"user_msg_style": {"avg_chars_per_msg": 7.0}},
        },
    )

    style_constraints = ctx["historical_context"]["style_constraints"]
    assert style_constraints["avg_msg_length"] == 7.0
    assert style_constraints["max_speech_length"] == 17
    assert style_constraints["communication_type"] == "reactive"
    assert style_constraints["emotional_style"] == "cold"


def test_augment_context_with_historical_data_merges_shared_cached_inputs(monkeypatch):
    ctx = {
        "emotion_summary": {"trend": "positive"},
        "recent_messages": [{"sender_attr": "other", "content": "好耶", "timestamp": 100}],
    }

    monkeypatch.setattr(
        "app.services.realtime.historical_context.load_cached_style_inputs",
        lambda conversation_id: (
            PreprocessedStatistics(
                total_message_count=12,
                average_message_length=6.0,
                emoji_message_count=3,
                sender_initiated_count=8,
                contact_initiated_count=4,
                nickname_message_count=2,
                sender_nickname_message_count=2,
                contact_nickname_message_count=0,
            ),
            {
                "emotional_resonance": {"score": 80},
                "attitude_tendency": {"score": 78},
            },
        ),
    )

    historical_context = augment_context_with_historical_data(
        ctx,
        self_profile_cache={
            "conversation_id": 99,
            "features_snapshot": {"user_msg_style": {"avg_chars_per_msg": 7.5}},
        },
    )

    assert historical_context["style_constraints"]["max_speech_length"] == 18
    assert historical_context["style_constraints"]["emotional_style"] == "warm"
    assert ctx["self_profile_features"]["user_msg_style"]["avg_chars_per_msg"] == 7.5
    assert ctx["preprocessed_stats"].sender_nickname_message_count == 2
