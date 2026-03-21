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

    assert score == 58.0


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

    assert score == 72.25


def test_polarity_consistency_uses_weighted_fusion(service, monkeypatch):
    monkeypatch.setattr(
        service,
        "_get_interaction_pairs",
        lambda conversation_id: [
            {"from_polarity": 1, "to_polarity": 1, "semantic_similarity": 0.4},
            {"from_polarity": 1, "to_polarity": 1, "semantic_similarity": 0.6},
            {"from_polarity": 1, "to_polarity": -1, "semantic_similarity": 0.9},
            {"from_polarity": 0, "to_polarity": -1, "semantic_similarity": 0.2},
        ],
    )

    score = service.calculate_polarity_consistency(1)

    assert score == 50.0


def test_empathy_recognition_returns_neutral_score_without_opportunities(service, monkeypatch):
    monkeypatch.setattr(
        service,
        "_get_interaction_pairs",
        lambda conversation_id: [
            {"from_polarity": 1, "to_polarity": 1, "to_content": "太好了", "time_gap": 60},
            {"from_polarity": 0, "to_polarity": 0, "to_content": "收到", "time_gap": 300},
        ],
    )

    score = service.calculate_empathy_recognition(1)

    assert score == 50.0


def test_empathy_recognition_uses_opportunity_based_scoring(service, monkeypatch):
    monkeypatch.setattr(
        service,
        "_get_interaction_pairs",
        lambda conversation_id: [
            {
                "from_polarity": -1,
                "from_content": "我有点难受",
                "to_polarity": 1,
                "to_content": "抱抱你，我在",
                "semantic_similarity": 0.80,
                "time_gap": 100,
            },
            {
                "from_polarity": -1,
                "from_content": "今天很累",
                "to_polarity": 0,
                "to_content": "怎么了，还好吗",
                "semantic_similarity": 0.52,
                "time_gap": 1200,
            },
            {
                "from_polarity": 1,
                "from_content": "今天挺开心",
                "to_polarity": 1,
                "to_content": "那太好了",
                "semantic_similarity": 0.60,
                "time_gap": 60,
            },
        ],
    )
    monkeypatch.setattr(
        service.direction_service,
        "classify",
        lambda content: type("Result", (), {"direction": "self"})(),
    )

    score = service.calculate_empathy_recognition(1)

    assert score == 90.95


def test_empathy_recognition_late_but_explicit_support_stays_high(service, monkeypatch):
    monkeypatch.setattr(
        service,
        "_get_interaction_pairs",
        lambda conversation_id: [
            {
                "from_polarity": -1,
                "from_content": "我现在特别难受",
                "to_polarity": 1,
                "to_content": "别担心，我理解你，会好起来的",
                "semantic_similarity": 0.78,
                "time_gap": 4000,
            },
        ],
    )
    monkeypatch.setattr(
        service.direction_service,
        "classify",
        lambda content: type("Result", (), {"direction": "self"})(),
    )

    score = service.calculate_empathy_recognition(1)

    assert score == 91.0


def test_empathy_recognition_fast_but_perfunctory_reply_does_not_score_high(service, monkeypatch):
    monkeypatch.setattr(
        service,
        "_get_interaction_pairs",
        lambda conversation_id: [
            {
                "from_polarity": -1,
                "from_content": "我今天真的很烦",
                "to_polarity": 0,
                "to_content": "哦",
                "semantic_similarity": 0.10,
                "time_gap": 60,
            },
        ],
    )
    monkeypatch.setattr(
        service.direction_service,
        "classify",
        lambda content: type("Result", (), {"direction": "self"})(),
    )

    score = service.calculate_empathy_recognition(1)

    assert score == 15.0


def test_empathy_recognition_neutral_question_reply_scores_mid(service, monkeypatch):
    monkeypatch.setattr(
        service,
        "_get_interaction_pairs",
        lambda conversation_id: [
            {
                "from_polarity": -1,
                "from_content": "我有点崩溃",
                "to_polarity": 0,
                "to_content": "怎么了，你还好吗",
                "semantic_similarity": 0.55,
                "time_gap": 1500,
            },
        ],
    )
    monkeypatch.setattr(
        service.direction_service,
        "classify",
        lambda content: type("Result", (), {"direction": "self"})(),
    )

    score = service.calculate_empathy_recognition(1)

    assert score == 81.9


def test_empathy_recognition_filters_negative_messages_aimed_at_others(service, monkeypatch):
    monkeypatch.setattr(
        service,
        "_get_interaction_pairs",
        lambda conversation_id: [
            {
                "from_polarity": -1,
                "from_content": "老板太离谱了",
                "to_polarity": 1,
                "to_content": "抱抱你",
                "semantic_similarity": 0.70,
                "time_gap": 100,
            },
        ],
    )
    monkeypatch.setattr(
        service.direction_service,
        "classify",
        lambda content: type("Result", (), {"direction": "to_others"})(),
    )

    score = service.calculate_empathy_recognition(1)

    assert score == 50.0


def test_negative_resolution_uses_weighted_pair_scores(service, monkeypatch):
    monkeypatch.setattr(
        service,
        "_get_interaction_pairs",
        lambda conversation_id: [
            {
                "from_polarity": -1,
                "from_content": "我好难受",
                "to_polarity": 1,
                "to_content": "没事的 我在",
                "time_gap": 100,
            },
            {
                "from_polarity": -1,
                "from_content": "今天特别累",
                "to_polarity": 1,
                "to_content": "抱抱你",
                "time_gap": 700,
            },
            {
                "from_polarity": -1,
                "from_content": "我现在好烦",
                "to_polarity": 0,
                "to_content": "先缓缓",
                "time_gap": 200,
            },
        ],
    )
    monkeypatch.setattr(
        service.direction_service,
        "classify",
        lambda content: type("Result", (), {"direction": "self"})(),
    )

    score = service.calculate_negative_resolution(1)

    assert score == 63.33
