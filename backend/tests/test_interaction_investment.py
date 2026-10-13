"""互动投入维度测试（内存 sqlite 真形表 + 纯公式）。"""

import os
import sqlite3
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import app.services.analysis.interaction_investment_service as imod
from app.services.analysis.engagement_metrics import EngagementMetrics
from app.services.analysis.interaction_investment_service import (
    InteractionInvestmentResult,
    InteractionInvestmentService,
)
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
        "CREATE TABLE interaction_pairs (id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "conversation_id INT, time_gap INT, semantic_similarity REAL)"
    )
    conn.execute(
        "CREATE TABLE sessions (id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "conversation_id INT, start_time INT, end_time INT, initiator TEXT)"
    )
    yield conn
    conn.close()


@pytest.fixture(autouse=True)
def patch_db(db, monkeypatch):
    monkeypatch.setattr(imod, "get_db", lambda: db)


@pytest.fixture
def service():
    return InteractionInvestmentService()


def add_msg(db, conv, is_sender, content, char_count=None, message_type=1):
    cur = db.execute(
        "INSERT INTO messages (conversation_id, is_sender, message_type, content, timestamp) "
        "VALUES (?, ?, ?, ?, ?)",
        (conv, is_sender, message_type, content, 1000),
    )
    msg_id = cur.lastrowid
    db.execute(
        "INSERT INTO message_preprocessed (message_id, is_valid, char_count, cleaned_content) "
        "VALUES (?, 1, ?, ?)",
        (msg_id, char_count if char_count is not None else len(content), content),
    )
    db.commit()
    return msg_id


def make_stats(total=100, days=10, sessions=10, contact_initiated=5):
    stats = PreprocessedStatistics()
    stats.total_message_count = total
    stats.conversation_duration_days = days
    stats.total_sessions = sessions
    stats.contact_initiated_count = contact_initiated
    return stats


# ===== 长时未回应（反向子项） =====


def test_long_unanswered_score_zero_point_anchor(service):
    # 每百条 6.7 次 → 0 分；0 次 → 100 分；3.35 次 → 50 分
    assert service._calculate_long_unanswered_score(6.7) == 0.0
    assert service._calculate_long_unanswered_score(0.0) == 100.0
    assert service._calculate_long_unanswered_score(3.35) == pytest.approx(50.0, abs=0.1)


def test_burst_unanswered_score_direction(service):
    # 双方均无连发 → 60 中性档
    assert service._calculate_burst_unanswered_score(0.0, 0.0) == 60.0
    # 对方每百条多 5 次连发 → +100 → 封顶
    assert service._calculate_burst_unanswered_score(5.0, 0.0) == 100.0
    # 我方连发未回为主 → 归零
    assert service._calculate_burst_unanswered_score(0.0, 5.0) == 0.0
    # 对称抵消 → 50
    assert service._calculate_burst_unanswered_score(3.0, 3.0) == 50.0


# ===== 回应对称性（自亲密度信号迁入） =====


def test_reply_symmetry_balanced_chars_score_high(db, service):
    for _ in range(10):
        add_msg(db, 1, 0, "你今天过得怎么样呀", char_count=100)
        add_msg(db, 1, 1, "挺好的，刚忙完一阵", char_count=100)

    score, meta = service._calculate_reply_symmetry(1, long_text_threshold=100)

    assert score > 70
    assert meta["well_balanced"] is True
    assert meta["char_balance"] == pytest.approx(0.5, abs=1e-6)


def test_reply_symmetry_flags_asymmetry_when_user_floods(db, service):
    # 我方长消息压倒性多于对方 → 字数失衡 + 长消息占比差 → 预警标记
    for _ in range(10):
        add_msg(db, 1, 0, "嗯", char_count=2)
        add_msg(db, 1, 1, "今天我想跟你详细说说这件事情的来龙去脉" * 6, char_count=180)

    score, meta = service._calculate_reply_symmetry(1, long_text_threshold=100)

    assert meta["char_balance"] < 0.35
    assert meta["asymmetry_warning"] is True
    assert score < 60


# ===== 综合公式 =====


def test_overall_score_weights_seven_subs_and_caps_bonus(service):
    result = InteractionInvestmentResult(
        daily_message_score=100.0,
        reply_timeliness_score=100.0,
        topic_continuity_score=100.0,
        active_initiation_score=100.0,
        reply_symmetry_score=100.0,
        long_unanswered_score=100.0,
        burst_unanswered_score=100.0,
        long_text_bonus=10.0,
    )
    assert service._calculate_overall_score(result) == 100.0

    result_zero = InteractionInvestmentResult(long_text_bonus=30.0)
    # 全零子项 + 加分 30 → 封顶逻辑在 min(100) 内为 30
    assert service._calculate_overall_score(result_zero) == 30.0


def test_calculate_scores_full_path(db, service, monkeypatch):
    # 各子项原始计算路径联通：交互对 15 条全及时（足量解除衰减）+ 高相似
    for gap, sim in [(60, 0.9), (120, 0.8), (100, 0.85), (90, 0.7), (200, 0.6)] * 3:
        db.execute(
            "INSERT INTO interaction_pairs (conversation_id, time_gap, semantic_similarity) "
            "VALUES (1, ?, ?)",
            (gap, sim),
        )
    db.commit()
    add_msg(db, 1, 0, "最近怎么样", char_count=20)
    add_msg(db, 1, 1, "还不错，周末去爬山了", char_count=30)

    stats = make_stats()
    metrics = EngagementMetrics(
        text_message_count=2,
        other_text_count=1,
        self_text_count=1,
        long_unanswered_other=0,
        burst_unanswered_other=0,
        burst_unanswered_self=0,
    )

    result = service.calculate_scores(1, stats, metrics)

    assert 0.0 <= result.overall_score <= 100.0
    assert result.reply_timeliness_score == 100.0
    assert result.topic_continuity_score > 50
    assert result.interpretation


# ===== 解释文本 =====


def test_interpretation_notes_long_unanswered_and_burst(service):
    result = InteractionInvestmentResult(
        overall_score=40.0,
        long_unanswered_other_per_100=6.0,
        burst_self_per_100=6.0,
        burst_other_per_100=1.0,
        confidence_meta={"asymmetry_warning": True},
    )
    text = service.generate_interpretation(result)
    assert "长时未回应偏多" in text
    assert "连发常未获回应" in text
    assert "不对称" in text
