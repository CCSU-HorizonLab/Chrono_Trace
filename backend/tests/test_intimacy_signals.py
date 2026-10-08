"""亲密度信号维度测试（内存库夹具，monkeypatch get_db）。"""

import os
import sqlite3
import sys
from datetime import datetime, timedelta

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import app.services.analysis.intimacy_signals_service as intimacy_module
from app.services.analysis.intimacy_signals_service import IntimacySignalsService
from app.services.analysis.preprocessing_orchestrator import PreprocessedStatistics


BASE_TS = int(datetime(2026, 8, 1, 12, 0, 0).timestamp())


@pytest.fixture
def db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE messages (id INTEGER PRIMARY KEY, conversation_id INT, is_sender INT, message_type INT, content TEXT, timestamp INT)")
    conn.execute("CREATE TABLE message_preprocessed (message_id INTEGER PRIMARY KEY, cleaned_content TEXT, char_count INT, is_valid INT)")
    conn.execute("CREATE TABLE sessions (id INTEGER PRIMARY KEY, conversation_id INT, start_time INT, end_time INT, initiator TEXT)")
    yield conn
    conn.close()


@pytest.fixture
def service(db, monkeypatch):
    monkeypatch.setattr(intimacy_module, "get_db", lambda: db)
    svc = IntimacySignalsService()
    # 词库走内存桩，保证称谓判定确定性
    monkeypatch.setattr(
        svc.keyword_libraries,
        "get_keywords",
        lambda category: ["老王", "小美", "宝"] if category == "nickname" else [],
    )
    return svc


def add_message(db, msg_id, is_sender, content, ts, message_type=1, chars=None):
    db.execute(
        "INSERT INTO messages (id, conversation_id, is_sender, message_type, content, timestamp) VALUES (?, 1, ?, ?, ?, ?)",
        (msg_id, is_sender, message_type, content, ts),
    )
    if message_type == 1:
        db.execute(
            "INSERT INTO message_preprocessed (message_id, cleaned_content, char_count, is_valid) VALUES (?, ?, ?, 1)",
            (msg_id, content, chars if chars is not None else len(content)),
        )


def stats_with(chat_days=10):
    stats = PreprocessedStatistics()
    stats.chat_days_count = chat_days
    stats.total_message_count = 100
    return stats


# ---------- 称谓演变 ----------

def test_address_term_warming_up_scores_high(service, db):
    # 前半段正式称谓，后半段昵称：升温轨迹
    add_message(db, 1, 0, "王总，材料我发您邮箱", BASE_TS)
    add_message(db, 2, 0, "王总看到了吗", BASE_TS + 3600)
    for i in range(6):
        add_message(db, 10 + i, 0, "老王今晚吃饭不", BASE_TS + 86400 * (i + 1))
    score, meta = service._calculate_address_term_evolution(1)
    assert meta.get("address_warming") is True
    assert score >= 70


def test_address_term_absent_returns_neutral_50_low_confidence(service, db):
    for i in range(8):
        add_message(db, 1 + i, 0, "今天天气不错去散步了", BASE_TS + 3600 * i)
    score, meta = service._calculate_address_term_evolution(1)
    assert score == 50.0
    assert meta.get("address_term_low_confidence") is True


def test_job_title_tier_counts_partial(service, db):
    # 全程正式称谓（Tier1）：只作在场证据不计亲密度——中等偏低分、
    # 无低置信（有称谓互动）也无升温
    for i in range(8):
        add_message(db, 1 + i, 0, "李老师明天有空吗", BASE_TS + 86400 * i)
    score, meta = service._calculate_address_term_evolution(1)
    assert 35 <= score <= 55
    assert "address_warming" not in meta
    assert not meta.get("address_term_low_confidence")


# ---------- 时段与投入 ----------

def test_time_investment_late_night_and_offhours_initiation(service, db):
    late = datetime(2026, 8, 5, 23, 30).timestamp()
    weekend = datetime(2026, 8, 8, 15, 0).timestamp()  # 周六
    workday = datetime(2026, 8, 6, 10, 0).timestamp()
    db.executemany(
        "INSERT INTO sessions (conversation_id, start_time, end_time, initiator) VALUES (1, ?, ?, ?)",
        [
            (late, late + 600, "other"),
            (weekend, weekend + 600, "other"),
            (workday, workday + 600, "other"),
        ],
    )
    # 对方消息含深夜消息
    add_message(db, 1, 0, "睡了吗", int(late))
    add_message(db, 2, 0, "白天聊", int(workday))
    add_message(db, 3, 0, "深夜吐槽数条一", int(late))
    add_message(db, 4, 0, "深夜吐槽数条二", int(late))
    score, meta = service._calculate_time_investment(1, stats_with())
    assert meta.get("offhours_initiation_rate", 0) > 0.5
    assert meta.get("late_night_message_rate", 0) >= 0.5
    assert score >= 60


def test_time_investment_empty_sessions_neutral(service, db):
    score, meta = service._calculate_time_investment(1, stats_with())
    assert meta.get("time_low_confidence") is True
    assert 40 <= score <= 60


# ---------- 回复对称性 ----------

def test_reply_asymmetry_balanced_high(service, db):
    for i in range(10):
        add_message(db, 1 + i, 0, "x" * 50, BASE_TS + 60 * i, chars=50)
        add_message(db, 100 + i, 1, "y" * 50, BASE_TS + 60 * i + 30, chars=50)
    # 各加一条表情包
    add_message(db, 200, 0, "[sticker]", BASE_TS, message_type=47)
    score, meta = service._calculate_reply_asymmetry(1)
    assert meta.get("well_balanced") is True
    assert score >= 70


def test_reply_asymmetry_one_sided_low_with_warning(service, db):
    # 对方只有只言片语，用户长篇大论
    for i in range(10):
        add_message(db, 1 + i, 0, "嗯", BASE_TS + 60 * i, chars=2)
        add_message(db, 100 + i, 1, "z" * 300, BASE_TS + 60 * i + 30, chars=300)
    score, meta = service._calculate_reply_asymmetry(1)
    assert meta.get("asymmetry_warning") is True
    assert score < 60


def test_reply_asymmetry_counts_sticker_messages(service, db):
    add_message(db, 1, 0, "文本一条", BASE_TS)
    for i in range(5):
        add_message(db, 10 + i, 0, "sticker", BASE_TS + 60 * (i + 1), message_type=47)
    score, meta = service._calculate_reply_asymmetry(1)
    assert meta.get("other_sticker_rate") == pytest.approx(5 / 6, abs=1e-3)


# ---------- 编排 ----------

def test_sub_weights_are_40_35_25():
    from app.services.analysis.intimacy_signals_service import SUB_WEIGHTS
    assert SUB_WEIGHTS["address_term_evolution"] == 0.40
    assert SUB_WEIGHTS["time_investment"] == 0.35
    assert SUB_WEIGHTS["reply_asymmetry"] == 0.25


def test_overall_intimacy_composes_subs(service, db):
    for i in range(4):
        add_message(db, 1 + i, 0, "老王在吗", BASE_TS + 3600 * i)
    result = service.calculate_overall_intimacy(1, stats_with())
    assert set(result["sub_scores"]) == {
        "address_term_evolution", "time_investment", "reply_asymmetry"
    }
    assert 0 <= result["overall_score"] <= 100
    assert result["interpretation"]
