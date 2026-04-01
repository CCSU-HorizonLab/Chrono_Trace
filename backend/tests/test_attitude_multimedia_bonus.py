import os
import sys
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.analysis.attitude_tendency_service import AttitudeTendencyService
from app.services.analysis.preprocessing_orchestrator import PreprocessedStatistics
from app.services.analysis.relationship_context_service import (
    RelationshipContext,
    RelationshipContextService,
)


def make_stats(
    *,
    total_message_count: int = 100,
    chat_days_count: int = 30,
    voice_message_count: int = 0,
    video_message_count: int = 0,
    privacy_message_count: int = 0,
) -> PreprocessedStatistics:
    stats = PreprocessedStatistics()
    stats.total_message_count = total_message_count
    stats.chat_days_count = chat_days_count
    stats.voice_message_count = voice_message_count
    stats.video_message_count = video_message_count
    stats.privacy_message_count = privacy_message_count
    return stats


class TestRelationshipContextServiceMediaThresholds:
    def test_returns_friend_defaults_without_context(self, monkeypatch):
        service = RelationshipContextService()
        monkeypatch.setattr(service, "get_context", lambda conversation_id: None)

        result = service.get_multimedia_thresholds(1)

        assert result == {
            "relationship_type": "friend",
            "video": 3.0,
            "voice": 20.0,
        }

    @pytest.mark.parametrize(
        ("relationship_type", "expected_video", "expected_voice"),
        [
            ("lover", 4.0, 20.0),
            ("crush", 4.0, 20.0),
            ("friend", 3.0, 20.0),
            ("family", 3.0, 20.0),
            ("colleague", 1.0, 10.0),
            ("other", 1.0, 10.0),
        ],
    )
    def test_returns_expected_thresholds_by_relationship_type(
        self, monkeypatch, relationship_type, expected_video, expected_voice
    ):
        service = RelationshipContextService()
        ctx = RelationshipContext(relationship_type=relationship_type)
        monkeypatch.setattr(service, "get_context", lambda conversation_id: ctx)

        result = service.get_multimedia_thresholds(1)

        assert result["relationship_type"] == relationship_type
        assert result["video"] == expected_video
        assert result["voice"] == expected_voice


class TestAttitudeTendencyServiceMultimediaBonus:
    @pytest.fixture
    def service(self):
        service = AttitudeTendencyService()
        service.orchestrator = MagicMock()
        service.relationship_context_service = MagicMock()
        return service

    def test_video_bonus_only_uses_video_threshold(self, service):
        service.orchestrator.get_preprocessed_statistics.return_value = make_stats(
            video_message_count=4,
            voice_message_count=0,
        )
        service.relationship_context_service.get_multimedia_thresholds.return_value = {
            "relationship_type": "lover",
            "video": 4.0,
            "voice": 20.0,
        }

        result = service.calculate_multimedia_usage(1)

        assert result["video_bonus"] == 10.0
        assert result["voice_bonus"] == 0.0
        assert result["multimedia_bonus"] == 10.0

    def test_voice_bonus_only_uses_voice_threshold(self, service):
        service.orchestrator.get_preprocessed_statistics.return_value = make_stats(
            video_message_count=0,
            voice_message_count=20,
        )
        service.relationship_context_service.get_multimedia_thresholds.return_value = {
            "relationship_type": "friend",
            "video": 3.0,
            "voice": 20.0,
        }

        result = service.calculate_multimedia_usage(1)

        assert result["video_bonus"] == 0.0
        assert result["voice_bonus"] == 20.0
        assert result["multimedia_bonus"] == 20.0

    def test_multimedia_bonus_sums_voice_and_video(self, service):
        service.orchestrator.get_preprocessed_statistics.return_value = make_stats(
            video_message_count=2,
            voice_message_count=10,
        )
        service.relationship_context_service.get_multimedia_thresholds.return_value = {
            "relationship_type": "colleague",
            "video": 1.0,
            "voice": 10.0,
        }

        result = service.calculate_multimedia_usage(1)

        assert result["video_bonus"] == 10.0
        assert result["voice_bonus"] == 20.0
        assert result["multimedia_bonus"] == 30.0

    def test_zero_message_stats_return_zero_bonus(self, service):
        service.orchestrator.get_preprocessed_statistics.return_value = make_stats(
            total_message_count=0,
            video_message_count=5,
            voice_message_count=5,
        )
        service.relationship_context_service.get_multimedia_thresholds.return_value = {
            "relationship_type": "friend",
            "video": 3.0,
            "voice": 20.0,
        }

        result = service.calculate_multimedia_usage(1)

        assert result["video_bonus"] == 0.0
        assert result["voice_bonus"] == 0.0
        assert result["multimedia_bonus"] == 0.0

    def test_overall_attitude_includes_split_bonus_scores(self, service, monkeypatch):
        service.orchestrator.get_preprocessed_statistics.return_value = make_stats()
        monkeypatch.setattr(service, "calculate_positive_word_frequency", lambda conversation_id: 60.0)
        monkeypatch.setattr(
            service,
            "calculate_negative_with_direction",
            lambda conversation_id: {
                "raw_frequency": 5.0,
                "negative_score": 80.0,
                "trust_bonus": 0.0,
                "to_me_count": 0,
                "to_others_count": 0,
                "ambiguous_count": 0,
                "total_negative_count": 0,
            },
        )
        monkeypatch.setattr(
            service,
            "calculate_multimedia_usage",
            lambda conversation_id: {
                "video_bonus": 7.5,
                "voice_bonus": 12.5,
                "multimedia_bonus": 20.0,
                "video_calls_per_month": 3.0,
                "voice_calls_per_month": 12.5,
                "video_threshold": 4.0,
                "voice_threshold": 20.0,
                "relationship_type": "lover",
            },
        )
        monkeypatch.setattr(service, "calculate_nickname_frequency", lambda conversation_id: 0.0)
        monkeypatch.setattr(service, "calculate_holiday_greeting", lambda conversation_id: 0.0)

        result = service.calculate_overall_attitude(1)

        assert result["bonus_scores"]["multimedia_bonus"] == 20.0
        assert result["bonus_scores"]["video_bonus"] == 7.5
        assert result["bonus_scores"]["voice_bonus"] == 12.5
        assert result["overall_score"] == 90.0
