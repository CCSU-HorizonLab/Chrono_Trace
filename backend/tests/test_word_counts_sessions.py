"""按会话字数统计（第三轮抽查 W8）。

此前 calculate_word_counts 的按会话行是恒 (NULL, 0, 0, 0) 的占位写入：
session_id 恒 NULL（sessions_data 无 id）污染「NULL=整体统计」哨兵语义，
字数恒 0 令按会话查询（analysis_read WHERE session_id IS NOT NULL）从
数据库层就不可用，整体行读取还受无序多 NULL 行的错读威胁。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from app.db.connection import DatabaseConnection
from app.services.analysis.feature_extraction_service import FeatureExtractionService


@pytest.fixture
def db(tmp_path):
    DatabaseConnection.close()
    DatabaseConnection._db_path = None
    conn = DatabaseConnection.initialize(str(tmp_path / "word_counts.db"))
    yield conn
    DatabaseConnection.close()
    DatabaseConnection._db_path = None


BASE = 1_700_000_000


def _seed(db):
    db.execute(
        "INSERT INTO conversations (id, account_wxid, username, display_name, platform, created_at, updated_at) "
        "VALUES (1, 'wxid_me', 'wxid_x', '对方', 'wechat', 1, 1)"
    )
    db.executemany(
        "INSERT INTO messages (id, conversation_id, talker, is_sender, content, message_type, timestamp, created_at) "
        "VALUES (?, 1, 'wxid_x', ?, ?, 1, ?, 1)",
        [
            # 会话 A（早）：本人 2 条 + 对方 1 条
            (1, 1, "早上好呀今天天气不错", BASE),
            (2, 0, "早呀", BASE + 60),
            (3, 1, "中午一起吃饭吗", BASE + 120),
            # 会话 B（晚，隔 8 小时）：对方 2 条 + 本人 1 条
            (4, 0, "晚上好", BASE + 8 * 3600),
            (5, 1, "在忙吗", BASE + 8 * 3600 + 60),
            (6, 0, "刚下班", BASE + 8 * 3600 + 120),
        ],
    )
    db.commit()


def test_extract_sessions_backfills_real_ids(db):
    """extract_sessions 返回的会话字典必须带数据库真实 id。"""
    _seed(db)
    service = FeatureExtractionService()

    class _FakePair:
        def build_speech_units(self, messages):
            return [{"message_count": len(messages)}]

    class _FakeSessionManager:
        _cancel_event = None

        def split_sessions(self, units, progress_cb=None):
            return [
                {"start_unit_id": 1, "end_unit_id": 1, "start_timestamp": BASE,
                 "end_timestamp": BASE + 120, "initiator_is_sender": 1},
                {"start_unit_id": 2, "end_unit_id": 2, "start_timestamp": BASE + 8 * 3600,
                 "end_timestamp": BASE + 8 * 3600 + 120, "initiator_is_sender": 0},
            ]

    service._pair_service = _FakePair()
    service._session_manager = _FakeSessionManager()
    # extract_features 才会注入取消信号，直测 extract_sessions 先补齐
    service._extract_cancel_event = None

    sessions = service.extract_sessions(1)

    assert len(sessions) == 2
    db_ids = [
        int(r["id"]) for r in db.execute(
            "SELECT id FROM sessions WHERE conversation_id = 1 ORDER BY start_time ASC"
        ).fetchall()
    ]
    assert [s["id"] for s in sessions] == db_ids, "回填 id 必须与库内真实行一一对应"


def test_word_counts_writes_real_per_session_rows(db):
    """按会话行：真实 session_id + 真实字数拆分 + 唯一 NULL 整体行。"""
    _seed(db)
    service = FeatureExtractionService()

    # 连续区间（真实切分是连续分区）：A=[BASE, BASE+3600) 左闭右开，
    # B=[BASE+3600, 末尾] 末段含终点——每条消息恰好归入一段
    db.execute(
        "INSERT INTO sessions (id, conversation_id, start_time, end_time, message_count, initiator, source, created_at) "
        "VALUES (11, 1, ?, ?, 3, 'user', 'long', 1)", (BASE, BASE + 3600)
    )
    db.execute(
        "INSERT INTO sessions (id, conversation_id, start_time, end_time, message_count, initiator, source, created_at) "
        "VALUES (12, 1, ?, ?, 3, 'other', 'long', 1)", (BASE + 3600, BASE + 8 * 3600 + 120)
    )
    db.commit()

    result = service.calculate_word_counts(1, [
        {"id": 11, "start_time": BASE, "end_time": BASE + 3600},
        {"id": 12, "start_time": BASE + 3600, "end_time": BASE + 8 * 3600 + 120},
    ])

    # NULL 哨兵行只有一行（整体统计），不再被占位行污染
    null_rows = db.execute(
        "SELECT user_char_count, other_char_count FROM word_counts "
        "WHERE conversation_id = 1 AND session_id IS NULL"
    ).fetchall()
    assert len(null_rows) == 1
    assert null_rows[0]["user_char_count"] > 0
    assert null_rows[0]["other_char_count"] > 0

    # 按会话行：真实 id + 真实拆分（与整体行的合计一致）
    session_rows = {
        int(r["session_id"]): (int(r["user_char_count"]), int(r["other_char_count"]))
        for r in db.execute(
            "SELECT session_id, user_char_count, other_char_count FROM word_counts "
            "WHERE conversation_id = 1 AND session_id IS NOT NULL"
        ).fetchall()
    }
    assert set(session_rows) == {11, 12}
    assert session_rows[11][0] > 0 and session_rows[11][1] > 0, "早段本人/对方都有消息"
    assert session_rows[12][0] > 0 and session_rows[12][1] > 0, "晚段本人/对方都有消息"
    assert sum(v[0] for v in session_rows.values()) == null_rows[0]["user_char_count"]
    assert sum(v[1] for v in session_rows.values()) == null_rows[0]["other_char_count"]

    # 会话 A 本人 2 条 vs 会话 B 本人 1 条：拆分方向正确
    assert session_rows[11][0] > session_rows[12][0]

    assert result["overall"]["user_char_count"] == null_rows[0]["user_char_count"]


def test_word_counts_boundary_message_belongs_to_later_session(db):
    """相邻会话共享边界时刻：边界消息归后段（左闭右开），不双计。"""
    _seed(db)
    service = FeatureExtractionService()

    # 两段共享边界 BASE+120（消息 3 的时刻）——归后段
    db.execute(
        "INSERT INTO sessions (id, conversation_id, start_time, end_time, message_count, initiator, source, created_at) "
        "VALUES (21, 1, ?, ?, 2, 'user', 'long', 1)", (BASE, BASE + 120)
    )
    db.execute(
        "INSERT INTO sessions (id, conversation_id, start_time, end_time, message_count, initiator, source, created_at) "
        "VALUES (22, 1, ?, ?, 4, 'other', 'long', 1)", (BASE + 120, BASE + 8 * 3600 + 120)
    )
    db.commit()

    service.calculate_word_counts(1, [
        {"id": 21, "start_time": BASE, "end_time": BASE + 120},
        {"id": 22, "start_time": BASE + 120, "end_time": BASE + 8 * 3600 + 120},
    ])

    session_rows = {
        int(r["session_id"]): int(r["user_char_count"])
        for r in db.execute(
            "SELECT session_id, user_char_count FROM word_counts "
            "WHERE conversation_id = 1 AND session_id IS NOT NULL"
        ).fetchall()
    }
    # 消息 3（本人"中午一起吃饭吗"，ts=BASE+120）归后段
    expected_later = service._get_message_char_count({"content": "中午一起吃饭吗"}) + \
        service._get_message_char_count({"content": "在忙吗"})
    assert session_rows[22] == expected_later
    assert session_rows[21] == service._get_message_char_count({"content": "早上好呀今天天气不错"})
