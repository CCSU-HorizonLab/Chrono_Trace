"""亲近信号维度测试（投入方向子项纯公式 + 加分/编排真形表）。"""

import os
import sqlite3
import sys
from datetime import datetime
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import app.services.analysis.closeness_signals_service as cmod
from app.services.analysis.closeness_signals_service import ClosenessSignalsService
from app.services.analysis.engagement_metrics import EngagementMetrics
from app.services.analysis.preprocessing_orchestrator import PreprocessedStatistics


@pytest.fixture
def db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        "CREATE TABLE messages (id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "conversation_id INT, is_sender INT, message_type INT DEFAULT 1, "
        "content TEXT, timestamp INT)"
    )
    conn.execute(
        "CREATE TABLE message_preprocessed (message_id INT PRIMARY KEY, "
        "is_valid INT DEFAULT 1, char_count INT DEFAULT 0, cleaned_content TEXT)"
    )
    conn.execute(
        "CREATE TABLE sessions (id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "conversation_id INT, start_time INT, end_time INT, initiator TEXT)"
    )
    yield conn
    conn.close()


@pytest.fixture(autouse=True)
def patch_db(db, monkeypatch):
    monkeypatch.setattr(cmod, "get_db", lambda: db)


@pytest.fixture
def service():
    return ClosenessSignalsService()


def make_stats(
    total=100, days=30, chat_days=10, privacy=0, holidays=0, voice=0, video=0
):
    stats = PreprocessedStatistics()
    stats.total_message_count = total
    stats.conversation_duration_days = days
    stats.chat_days_count = chat_days
    stats.privacy_message_count = privacy
    stats.holidays_sent_count = holidays
    stats.voice_message_count = voice
    stats.video_message_count = video
    return stats


# ===== 投入方向子项（metrics 驱动） =====


def test_greeting_initiation_follows_other_share(service):
    # 全部对方发起 → 100；全部我方 → 40；无互动 → 50
    m = EngagementMetrics(
        morning_greeting_other=3, night_greeting_other=2,
        morning_greeting_self=0, night_greeting_self=0,
    )
    assert service._calculate_greeting_initiation(m)[0] == 100.0
    m_self = EngagementMetrics(
        morning_greeting_other=0, night_greeting_other=0,
        morning_greeting_self=2, night_greeting_self=3,
    )
    assert service._calculate_greeting_initiation(m_self)[0] == 40.0
    assert service._calculate_greeting_initiation(EngagementMetrics())[0] == 50.0


def test_icebreaking_follows_other_share(service):
    m = EngagementMetrics(icebreak_total=5, icebreak_other=4, icebreak_self=1)
    score, meta = service._calculate_icebreaking(m)
    assert score == pytest.approx(40 + 60 * 0.8)
    assert meta["icebreak_other_led"] is True
    m_self = EngagementMetrics(icebreak_total=5, icebreak_other=1, icebreak_self=4)
    _, meta_self = service._calculate_icebreaking(m_self)
    assert meta_self["icebreak_self_led"] is True
    assert service._calculate_icebreaking(EngagementMetrics())[0] == 50.0


def test_community_expression_anchors_thirty_percent(service):
    assert service._calculate_community_expression(
        EngagementMetrics(community_ratio_other=0.30)
    )[0] == 100.0
    assert service._calculate_community_expression(
        EngagementMetrics(community_ratio_other=0.15)
    )[0] == 50.0
    # 无第一人称指称 → 中性
    assert service._calculate_community_expression(EngagementMetrics())[0] == 50.0


# ===== 加分项（自态度倾向迁入） =====


def test_bonus_scores_compose_and_cap(service, monkeypatch):
    # 隐私 5 封顶 + 节日 7 + 语音视频 3 → 15；超限再压
    monkeypatch.setattr(
        service, "_calculate_holiday_greeting", lambda stats: 7.0
    )
    monkeypatch.setattr(
        service, "_calculate_multimedia_usage", lambda cid, stats: 3.0
    )
    stats = make_stats(privacy=9)

    bonus = service._calculate_bonus_scores(1, stats)

    assert bonus["privacy_bonus"] == 5.0
    assert bonus["holiday_bonus"] == 7.0
    assert bonus["multimedia_bonus"] == 3.0
    assert bonus["total_bonus"] == 15.0


def test_multimedia_bonus_uses_relationship_thresholds(service, monkeypatch):
    import app.services.analysis.relationship_context_service as rcs_mod

    mock_cls = MagicMock()
    mock_cls.return_value.get_multimedia_thresholds.return_value = {
        "relationship_type": "friend",
        "video": 3.0,
        "voice": 20.0,
    }
    monkeypatch.setattr(rcs_mod, "RelationshipContextService", mock_cls)

    # 30 活跃天 1 条视频（月均 1 < 3）+ 20 条语音（月均 20 = 阈值）
    stats = make_stats(chat_days=30, voice=20, video=1)
    bonus = service._calculate_multimedia_usage(1, stats)

    assert bonus == pytest.approx(5.0 / 3.0 + 10.0, abs=0.01)


# ===== 编排 =====


def test_calculate_overall_closeness_composes_subs_and_bonus(service, monkeypatch):
    monkeypatch.setattr(
        service, "_calculate_address_term_evolution", lambda cid: (80.0, {})
    )
    monkeypatch.setattr(
        service, "_calculate_late_night_engagement", lambda cid: (60.0, {})
    )
    monkeypatch.setattr(
        service, "_calculate_active_coverage", lambda cid, stats: (70.0, {})
    )
    monkeypatch.setattr(
        service, "_calculate_bonus_scores",
        lambda cid, stats: {
            "privacy_bonus": 0.0, "holiday_bonus": 0.0,
            "multimedia_bonus": 0.0, "total_bonus": 10.0,
        },
    )
    metrics = EngagementMetrics(
        morning_greeting_other=4, icebreak_total=4, icebreak_other=3,
        community_ratio_other=0.3,
    )

    result = service.calculate_overall_closeness(1, make_stats(), metrics)

    expected = (
        80.0 * 0.30 + 60.0 * 0.15 + 70.0 * 0.10
        + 100.0 * 0.15 + 85.0 * 0.15 + 100.0 * 0.15
    )
    assert result["overall_score"] == pytest.approx(min(100.0, expected + 10.0), abs=0.01)
    assert set(result["sub_scores"]) == {
        "address_term_evolution", "late_night_engagement", "active_coverage",
        "greeting_initiation", "icebreaking", "community_expression",
    }
    assert result["interpretation"]


def test_overall_closeness_caps_at_one_hundred(service, monkeypatch):
    for name, ret in (
        ("_calculate_address_term_evolution", lambda cid: (100.0, {})),
        ("_calculate_late_night_engagement", lambda cid: (100.0, {})),
        ("_calculate_active_coverage", lambda cid, stats: (100.0, {})),
    ):
        monkeypatch.setattr(service, name, ret)
    monkeypatch.setattr(
        service, "_calculate_bonus_scores",
        lambda cid, stats: {
            "privacy_bonus": 5.0, "holiday_bonus": 7.0,
            "multimedia_bonus": 5.0, "total_bonus": 15.0,
        },
    )
    metrics = EngagementMetrics(
        morning_greeting_other=5, icebreak_total=5, icebreak_other=5,
        community_ratio_other=0.5,
    )

    result = service.calculate_overall_closeness(1, make_stats(), metrics)
    assert result["overall_score"] == 100.0
