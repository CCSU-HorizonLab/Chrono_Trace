"""会话投入特征统计测试（内存 sqlite 真形表，monkeypatch get_db）。"""

import os
import sqlite3
import sys
from datetime import datetime

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import app.services.analysis.engagement_metrics as emod
from app.services.analysis.engagement_metrics import (
    EngagementMetricsService,
    gap_spans_deep_night,
)


def ts(month=6, day=1, hour=10, minute=0):
    return int(datetime(2026, month, day, hour, minute).timestamp())


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
        "CREATE TABLE sentiment_cache (id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "message_id INT UNIQUE, polarity INT, intensity REAL, embedding_vector BLOB)"
    )
    yield conn
    conn.close()


@pytest.fixture(autouse=True)
def patch_db(db, monkeypatch):
    monkeypatch.setattr(emod, "get_db", lambda: db)


def add(db, conv, is_sender, content, timestamp, message_type=1):
    cur = db.execute(
        "INSERT INTO messages (conversation_id, is_sender, message_type, content, timestamp) "
        "VALUES (?, ?, ?, ?, ?)",
        (conv, is_sender, message_type, content, timestamp),
    )
    db.commit()
    return cur.lastrowid


def compute(conv):
    return EngagementMetricsService().compute(conv)


# ===== 连发未回 =====


def test_burst_unanswered_counts_runs_of_three_plus(db):
    # 对方连发 3 条后我方才回：连发未回（对方）
    add(db, 1, 0, "在吗", ts(hour=10))
    add(db, 1, 0, "想问你个事", ts(hour=10, minute=1))
    add(db, 1, 0, "看到回我一下", ts(hour=10, minute=2))
    add(db, 1, 1, "刚看到，你说", ts(hour=10, minute=5))
    add(db, 1, 0, "嗯嗯你问", ts(hour=10, minute=6))
    # 我方连发 2 条后对方回：不足 3 条不计
    add(db, 1, 1, "明天有空吗", ts(hour=11))
    add(db, 1, 1, "一起吃饭", ts(hour=11, minute=1))
    add(db, 1, 0, "可以呀", ts(hour=11, minute=3))
    metrics = compute(1)
    assert metrics.burst_unanswered_other == 1
    assert metrics.burst_unanswered_self == 0


def test_burst_unanswered_settles_tail_run(db):
    # 对话以我方 3 连发收尾且无回应：尾部结算
    add(db, 1, 0, "晚安", ts(hour=21))
    add(db, 1, 1, "晚安啦", ts(hour=21, minute=1))
    add(db, 1, 1, "明天记得带伞", ts(hour=21, minute=2))
    add(db, 1, 1, "我看天气要下雨", ts(hour=21, minute=3))
    add(db, 1, 1, "就这些啦", ts(hour=21, minute=4))
    metrics = compute(1)
    assert metrics.burst_unanswered_self == 1


# ===== 长时未回应与深夜豁免 =====


def test_long_unanswered_daytime_gap_counts(db):
    # 我方 09:00 发言，对方 12:30 才回（3.5h 白天间隔）：对方长时未回应
    add(db, 1, 1, "上午的方案你看看", ts(hour=9))
    add(db, 1, 0, "看完了，没问题", ts(hour=12, minute=30))
    metrics = compute(1)
    assert metrics.long_unanswered_other == 1
    assert metrics.long_unanswered_self == 0


def test_long_unanswered_sleep_gap_exempt(db):
    # 对方 23:00 发言，我方次日 08:30 回（跨深夜）：不计长时未回应
    add(db, 1, 0, "还没睡呀", ts(hour=23))
    add(db, 1, 1, "刚起，昨晚睡得早", ts(day=2, hour=8, minute=30))
    metrics = compute(1)
    assert metrics.long_unanswered_self == 0
    assert metrics.long_unanswered_other == 0


def test_gap_spans_deep_night_boundary():
    assert gap_spans_deep_night(ts(hour=23), ts(day=2, hour=8)) is True
    assert gap_spans_deep_night(ts(hour=9), ts(hour=12, minute=30)) is False
    # 长间隔直接豁免
    assert gap_spans_deep_night(ts(), ts(month=7, day=15)) is True


# ===== 主动破冰 =====


def test_icebreak_attributed_to_resumer(db):
    # 我方发言后 30h 沉默，对方先开口：对方破冰，且不重复计长时未回应
    add(db, 1, 1, "先忙了", ts(hour=10))
    add(db, 1, 0, "在吗，昨天说的那个事", ts(day=2, hour=16))
    metrics = compute(1)
    assert metrics.icebreak_total == 1
    assert metrics.icebreak_other == 1
    assert metrics.icebreak_self == 0
    assert metrics.long_unanswered_self == 0


# ===== 早晚安发起 =====


def test_greetings_dedup_per_day_per_kind(db):
    add(db, 1, 0, "早安", ts(hour=8))
    add(db, 1, 0, "早上好呀", ts(hour=8, minute=5))  # 同日同类型去重
    add(db, 1, 0, "早知道你会来", ts(hour=9))  # 非问候（锚定不命中）
    add(db, 1, 0, "晚安", ts(hour=22))
    add(db, 1, 1, "晚安啦，好梦", ts(hour=22, minute=1))
    add(db, 1, 1, "早安", ts(day=2, hour=8))  # 次日重新计数
    metrics = compute(1)
    assert metrics.morning_greeting_other == 1
    assert metrics.night_greeting_other == 1
    assert metrics.night_greeting_self == 1
    assert metrics.morning_greeting_self == 1


# ===== 共同体表达 =====


def test_community_ratio_first_person(db):
    add(db, 1, 0, "我们下周去哪儿玩", ts(hour=10))
    add(db, 1, 0, "我想想", ts(hour=10, minute=2))
    add(db, 1, 0, "我妈说明天家里有事", ts(hour=10, minute=4))
    add(db, 1, 1, "我们仨一起吧", ts(hour=10, minute=6))
    metrics = compute(1)
    # 对方：我们×1 + 我×2（「我妈」计入第一人称单数）→ 1/3
    assert metrics.community_ratio_other == pytest.approx(1 / 3, abs=1e-3)
    # 我方：我们×1 + 我×0 → 1.0
    assert metrics.community_ratio_self == 1.0


def test_community_ratio_absent_without_pronouns(db):
    add(db, 1, 0, "今天天气不错", ts(hour=10))
    metrics = compute(1)
    assert metrics.community_ratio_other is None


# ===== 敷衍回复 =====


def test_perfunctory_counts_and_rate(db):
    add(db, 1, 0, "嗯", ts(hour=10))
    add(db, 1, 0, "好的明天见", ts(hour=10, minute=1))  # >2 字且不在词表
    add(db, 1, 0, "哦", ts(hour=10, minute=2))
    add(db, 1, 0, "可以", ts(hour=10, minute=3))
    add(db, 1, 1, "那明天上午碰头", ts(hour=10, minute=4))
    metrics = compute(1)
    assert metrics.perfunctory_other == 3  # 嗯/哦/可以（词表 + ≤2 字）
    assert metrics.perfunctory_rate_other == pytest.approx(3 / 4, abs=1e-3)
    assert metrics.perfunctory_self == 0


# ===== 撤回频次 =====


def test_revoke_parsed_from_system_messages(db):
    mid1 = add(db, 1, 1, "文本", ts(hour=10), message_type=10000)  # 占位无匹配
    assert mid1
    add(db, 1, 0, "你撤回了一条消息", ts(hour=10, minute=1), message_type=10000)
    add(db, 1, 0, "张三 撤回了一条消息", ts(hour=10, minute=2), message_type=10000)
    add(db, 1, 0, "「李四」撤回了一条新消息", ts(hour=10, minute=3), message_type=10000)
    metrics = compute(1)
    assert metrics.revoke_self == 1
    assert metrics.revoke_other == 2
    # 系统消息不进文本指标
    assert metrics.text_message_count == 0


# ===== 日消息量波动 =====


def test_daily_cv_active_days(db):
    for i in range(4):
        add(db, 1, 0, f"消息{i}", ts(hour=10 + i))
    for i in range(2):
        add(db, 1, 1, f"回复{i}", ts(day=2, hour=10 + i))
    metrics = compute(1)
    assert metrics.daily_counts["2026-06-01"] == 4
    assert metrics.daily_counts["2026-06-02"] == 2
    # [4,2]：均值 3、总体标准差 1 → CV = 1/3
    assert metrics.daily_cv_active == pytest.approx(1 / 3, abs=1e-3)


def test_daily_cv_none_single_day(db):
    add(db, 1, 0, "只有一条", ts(hour=10))
    metrics = compute(1)
    assert metrics.daily_cv_active is None


# ===== 情绪极性（sentiment_cache 关联） =====


def test_polarity_counts_join_sentiment_cache(db):
    m1 = add(db, 1, 0, "今天真开心", ts(hour=10))
    m2 = add(db, 1, 0, "烦死了", ts(hour=10, minute=1))
    m3 = add(db, 1, 1, "哈哈是啊", ts(hour=10, minute=2))
    db.executemany(
        "INSERT INTO sentiment_cache (message_id, polarity, intensity) VALUES (?, ?, 0.5)",
        [(m1, 1), (m2, -1), (m3, 1)],
    )
    db.commit()
    metrics = compute(1)
    assert metrics.positive_other == 1
    assert metrics.negative_other == 1
    assert metrics.positive_self == 1


def test_empty_conversation_returns_zeroed_metrics(db):
    metrics = compute(99)
    assert metrics.text_message_count == 0
    assert metrics.span_days == 0.0
    assert metrics.daily_cv_active is None
    dumped = metrics.to_dict()
    assert dumped["burst_unanswered"] == {"self": 0, "other": 0}
