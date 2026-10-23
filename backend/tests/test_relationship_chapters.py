"""关系章节测试：DP 分段正确性、周级大五缺席语义、payload 结构与边界检出。

合成数据确定性锚点：`_week_start` 依赖本地时区，夹具以 `_week_start(固定ts)`
为周 0 基准、按 WEEK_SECONDS 推进，任何时区下都落在同一序列。
"""
import sqlite3
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from app.services.analysis import deep_analysis_service as dasmod
from app.services.analysis import keyword_libraries as klibmod
from app.services.analysis import relationship_chapters as rcmod
from app.services.analysis.relationship_chapters import (
    MIN_TOTAL_TEXTS,
    WEEK_SECONDS,
    RelationshipChapterService,
    _week_start,
    detect_chapters,
)

# 固定种子周基准（时区无关：由 _week_start 本身算出）
BASE_WEEK = _week_start(1700000000)


class TestDetectChapters:
    """纯函数分段：确定性、变点检出、惩罚宁缺毋滥。"""

    @staticmethod
    def _rows(low_weeks, high_weeks, shift=2.0, noise=0.1):
        """volume 两水平 + 微噪声，其余三特征恒定（零方差列被剔除）。"""
        rows = []
        for i in range(low_weeks):
            rows.append([(-shift / 2) + noise * ((i % 3) - 1), 0.5, 1.0, 2.0])
        for i in range(high_weeks):
            rows.append([(shift / 2) + noise * ((i % 3) - 1), 0.5, 1.0, 2.0])
        return rows

    def test_single_changepoint_recovered(self):
        starts = detect_chapters(self._rows(12, 12))
        assert len(starts) == 2
        assert starts[0] == 0
        assert abs(starts[1] - 12) <= 3  # 验收：误差 ≤3 周

    def test_flat_series_single_segment(self):
        rows = [[0.1 * ((i % 3) - 1), 0.5, 1.0, 2.0] for i in range(16)]
        assert detect_chapters(rows) == [0]

    def test_short_input_no_split(self):
        assert detect_chapters([[1.0, 0.5, 1.0, 2.0]] * 3) == [0]
        assert detect_chapters([]) == [0]

    def test_all_constant_columns_no_split(self):
        assert detect_chapters([[3.0, 0.5, 1.0, 2.0]] * 20) == [0]

    def test_deterministic(self):
        rows = self._rows(10, 14)
        assert detect_chapters(rows) == detect_chapters(rows)


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    c.executescript(
        """
        CREATE TABLE conversations(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            account_wxid TEXT NOT NULL, username TEXT NOT NULL,
            display_name TEXT NOT NULL);
        CREATE TABLE messages(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            conversation_id INTEGER NOT NULL, is_sender INTEGER NOT NULL,
            message_type INTEGER NOT NULL, content TEXT,
            timestamp INTEGER NOT NULL, created_at INTEGER NOT NULL);
        CREATE TABLE sentiment_cache(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            message_id INTEGER NOT NULL UNIQUE,
            polarity INTEGER NOT NULL, intensity REAL NOT NULL,
            created_at INTEGER NOT NULL);
        CREATE TABLE sessions(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            conversation_id INTEGER NOT NULL, start_time INTEGER NOT NULL,
            end_time INTEGER NOT NULL, message_count INTEGER NOT NULL,
            initiator TEXT NOT NULL, created_at INTEGER NOT NULL);
        CREATE TABLE response_times(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            conversation_id INTEGER NOT NULL, sent_message_id INTEGER NOT NULL,
            reply_message_id INTEGER NOT NULL, response_time_seconds REAL,
            is_abnormal INTEGER DEFAULT 0, created_at INTEGER NOT NULL);
        """
    )
    yield c
    c.close()


@pytest.fixture
def service(conn, monkeypatch):
    """三处 get_db 全部指向内存库（章节/里程碑/词表）。"""
    monkeypatch.setattr(rcmod, "get_db", lambda: conn)
    monkeypatch.setattr(dasmod, "get_db", lambda: conn)
    monkeypatch.setattr(klibmod, "get_db", lambda: conn)
    return RelationshipChapterService()


def _seed_text(conn, msg_id_seed, conv, is_sender, ts, content="周末出去走走吗"):
    cur = conn.execute(
        "INSERT INTO messages(conversation_id, is_sender, message_type, content,"
        " timestamp, created_at) VALUES (?, ?, 1, ?, ?, ?)",
        (conv, is_sender, content, ts, ts),
    )
    conn.execute(
        "INSERT INTO sentiment_cache(message_id, polarity, intensity, created_at)"
        " VALUES (?, 1, 0.6, ?)",
        (cur.lastrowid, ts),
    )
    return cur.lastrowid


def _seed_weeks(conn, conv, weeks_spec):
    """weeks_spec: [(me_count, other_count), ...]，周 i 内按比例交错铺双方消息。"""
    for wi, (me_n, other_n) in enumerate(weeks_spec):
        week_start = BASE_WEEK + wi * WEEK_SECONDS
        sides, mi, oi = [], 0, 0
        while mi < me_n or oi < other_n:
            if mi * other_n <= oi * me_n:  # 欠额侧先发（按比例交错）
                sides.append(1)
                mi += 1
            else:
                sides.append(0)
                oi += 1
        for k, is_sender in enumerate(sides):
            _seed_text(
                conn, 0, conv, is_sender,
                week_start + 3600 + k * 300,
            )


class TestRelationshipChapterService:

    def test_insufficient_data(self, conn, service):
        conn.execute(
            "INSERT INTO conversations(account_wxid, username, display_name)"
            " VALUES ('wxid_me', 'wxid_ta', 'TA')"
        )
        for i in range(MIN_TOTAL_TEXTS - 1):
            _seed_text(conn, 0, 1, i % 2, BASE_WEEK + i * 600)
        result = service.get_chapters(1)
        assert result["ok"] is False
        assert result["reason"] == "insufficient_data"

    def test_payload_structure_and_boundary(self, conn, service):
        conn.execute(
            "INSERT INTO conversations(account_wxid, username, display_name)"
            " VALUES ('wxid_me', 'wxid_ta', 'TA')"
        )
        # 24 周：前 12 周淡季（每侧 12 条），后 12 周旺季（每侧 40 条）——volume 3 倍跳变
        spec = [(12, 12)] * 12 + [(40, 40)] * 12
        _seed_weeks(conn, 1, spec)

        result = service.get_chapters(1)
        assert result["ok"] is True, result
        assert result["version"] == rcmod.CHAPTERS_VERSION

        span = result["span"]
        assert span["week_count"] == 24
        assert len(result["week_starts"]) == 24
        # 周序列各数组长度对齐
        weekly = result["weekly"]
        for key in ("texts_me", "texts_other", "pos_ratio", "latency_hours"):
            assert len(weekly[key]) == 24
        for side in ("me", "other"):
            for dim in weekly["big5"][side]:
                assert len(weekly["big5"][side][dim]) == 24

        # 章节卡在跳变周附近（±3 周），且报出 volume 上升
        chapters = result["chapters"]
        assert 2 <= len(chapters) <= rcmod.MAX_CHAPTERS
        if len(chapters) >= 2:
            boundary = chapters[1]["week_index"]
            assert abs(boundary - 12) <= 3
            volume_change = [
                c for c in chapters[1]["changes"] if c["key"] == "volume"
            ]
            assert volume_change and volume_change[0]["direction"] == "up"
            assert chapters[0]["stats"]["texts"] < chapters[1]["stats"]["texts"]

    def test_weekly_big5_thin_side_is_none(self, conn, service):
        conn.execute(
            "INSERT INTO conversations(account_wxid, username, display_name)"
            " VALUES ('wxid_me', 'wxid_ta', 'TA')"
        )
        # 3 周：TA 第 0 周只有 3 条（<10 留白），我每周 20 条
        _seed_weeks(conn, 1, [(20, 3), (20, 12), (20, 12)])
        result = service.get_chapters(1)
        assert result["ok"] is True, result

        big5 = result["weekly"]["big5"]
        for dim in big5["other"]:
            assert big5["other"][dim][0] is None  # 薄周诚实留白
            assert big5["other"][dim][1] is not None  # 12 条 ≥ 阈值有分
        me_scores = [big5["me"][d][i] for d in big5["me"] for i in range(3)]
        assert any(s is not None for s in me_scores)

        # 序列太短不切段，但周级序列照常给出
        assert len(result["chapters"]) == 1

    def test_empty_conversation(self, service):
        result = service.get_chapters(999)
        assert result["ok"] is False
        assert result["reason"] == "insufficient_data"

    def test_silence_gap_weeks_filled_and_dated(self, conn, service):
        """中间静默数周：空周补零进周序列；沉默章起于空周时时间戳仍有值。"""
        conn.execute(
            "INSERT INTO conversations(account_wxid, username, display_name)"
            " VALUES ('wxid_me', 'wxid_ta', 'TA')"
        )
        # 周 0-8 有消息，周 9-11 完全静默，周 12 恢复 → 周序列 13 周含 3 个空周
        _seed_weeks(conn, 1, [(20, 20)] * 9)
        for k in range(40):
            _seed_text(conn, 0, 1, k % 2, BASE_WEEK + 12 * WEEK_SECONDS + 3600 + k * 300)
        result = service.get_chapters(1)
        assert result["ok"] is True, result
        assert result["span"]["week_count"] == 13
        assert sum(result["weekly"]["texts_me"]) == 9 * 20 + 20
        # 所有章节时间戳非空（沉默段起点不许是 None）
        for ch in result["chapters"]:
            assert ch["from_ts"] and ch["to_ts"] and ch["from_ts"] <= ch["to_ts"]
