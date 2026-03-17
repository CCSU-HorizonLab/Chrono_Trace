import os
import sys

import pytest


sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.analysis.emotional_resonance_service import EmotionalResonanceService


@pytest.fixture
def service():
    return EmotionalResonanceService()


def test_bidirectional_positive_response_counts_strong_and_soft_replies(service, monkeypatch):
    monkeypatch.setattr(
        service,
        "_get_interaction_pairs",
        lambda conversation_id: [
            {"from_polarity": 1, "to_polarity": 1, "to_intensity": 0.8, "to_content": "太好了", "time_gap": 60},
            {"from_polarity": 1, "to_polarity": 0, "to_intensity": 0.2, "to_content": "好呀", "time_gap": 120},
            {"from_polarity": 1, "to_polarity": 0, "to_intensity": 0.0, "to_content": "收到", "time_gap": 180},
            {"from_polarity": 1, "to_polarity": -1, "to_intensity": -0.6, "to_content": "不行", "time_gap": 240},
        ],
    )

    score = service.calculate_bidirectional_positive_response(1)

    assert score == 58.67


def test_bidirectional_positive_response_ignores_replies_outside_time_window(service, monkeypatch):
    monkeypatch.setattr(
        service,
        "_get_interaction_pairs",
        lambda conversation_id: [
            {"from_polarity": 1, "to_polarity": 1, "to_intensity": 0.6, "to_content": "好呀", "time_gap": 60},
            {"from_polarity": 1, "to_polarity": 1, "to_intensity": 0.7, "to_content": "当然可以", "time_gap": 9999},
        ],
    )

    score = service.calculate_bidirectional_positive_response(1)

    assert score == 100.0


def test_bidirectional_positive_response_returns_zero_without_positive_initiation(service, monkeypatch):
    monkeypatch.setattr(
        service,
        "_get_interaction_pairs",
        lambda conversation_id: [
            {"from_polarity": 0, "to_polarity": 1, "to_intensity": 0.6, "to_content": "好呀", "time_gap": 60},
            {"from_polarity": -1, "to_polarity": 1, "to_intensity": 0.7, "to_content": "抱抱你", "time_gap": 120},
        ],
    )

    score = service.calculate_bidirectional_positive_response(1)

    assert score == 0.0


def test_bidirectional_positive_response_rewards_engaged_neutral_reply(service, monkeypatch):
    monkeypatch.setattr(
        service,
        "_get_interaction_pairs",
        lambda conversation_id: [
            {
                "from_polarity": 1,
                "to_polarity": 0,
                "to_intensity": 0.20,
                "to_content": "真的呀 哈哈",
                "semantic_similarity": 0.72,
                "time_gap": 90,
            },
        ],
    )

    score = service.calculate_bidirectional_positive_response(1)

    assert score == 63.0
