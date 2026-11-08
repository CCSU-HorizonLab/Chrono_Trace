"""年度报告/纪念册数据服务测试（docs/product-redesign-2026-11.md §6.2）。

窗口口径聚合 / 专属梗两段式挖掘 / 早安晚安节奏 / 好感温度封皮降级。
夹具与 test_share_poster_export 同款（真形表 + get_db 打桩）。
"""

import os
import sqlite3
import sys
from datetime import datetime

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import app.services.analysis.deep_analysis_service as deepmod
import app.services.analysis.report_service as rmod
from app.services.analysis.report_service import ReportService
from app.webview.api.deep_analysis import DeepAnalysisApiMixin

_DAY = 86400


def _make_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        "CREATE TABLE conversations (id INTEGER PRIMARY KEY, account_wxid TEXT DEFAULT '',"
        " username TEXT, display_name TEXT, nickname TEXT, avatar_path TEXT,"
        " conversation_type TEXT DEFAULT 'single', message_count INT DEFAULT 0,"
        " updated_at INT DEFAULT 0, is_deleted INT DEFAULT 0, analysis_stale INT DEFAULT 0,"
        " analysis_message_count INT DEFAULT 0)"
    )
    conn.execute(
        "CREATE TABLE contacts (id INTEGER PRIMARY KEY, account_wxid TEXT DEFAULT '',"
        " username TEXT, nickname TEXT, remark TEXT, avatar_path TEXT)"
    )
    conn.execute(
        "CREATE TABLE messages (id INTEGER PRIMARY KEY, conversation_id INT,"
        " is_sender INT, message_type INT DEFAULT 1, content TEXT, timestamp INT)"
    )
    conn.execute(
        "CREATE TABLE sentiment_cache (message_id INTEGER UNIQUE, polarity INT,"
        " intensity REAL, created_at INT)"
    )
    conn.execute(
        "CREATE TABLE sessions (id INTEGER PRIMARY KEY AUTOINCREMENT,"
        " conversation_id INT, start_time INT, end_time INT, message_count INT,"
        " initiator TEXT, created_at INT)"
    )
    conn.execute(
        "CREATE TABLE response_times (id INTEGER PRIMARY KEY AUTOINCREMENT,"
        " conversation_id INT, sent_message_id INT, reply_message_id INT,"
        " response_time_seconds REAL, is_abnormal INT DEFAULT 0, created_at INT)"
    )
    conn.execute(
        "CREATE TABLE affinity_scores (id INTEGER PRIMARY KEY, conversation_id INT,"
        " overall_score REAL, analysis_version INT, created_at INT)"
    )
    return conn


@pytest.fixture
def db(monkeypatch):
    conn = _make_db()
    # deep 聚合器走模块级 get_db；report/pulse/emoji 走 app.db.connection.get_db
    monkeypatch.setattr(deepmod, "get_db", lambda: conn)
    monkeypatch.setattr("app.db.connection.get_db", lambda: conn)
    yield conn
    conn.close()


def _local_noon(date_str: str) -> int:
    return int(datetime.strptime(date_str, "%Y-%m-%d %H:%M:%S").timestamp())


def _msg(conn, is_sender: int, content: str, ts: int, mtype: int = 1):
    conn.execute(
        "INSERT INTO messages (conversation_id, is_sender, message_type, content, timestamp)"
        " VALUES (1, ?, ?, ?, ?)",
        (is_sender, mtype, content, ts),
    )


class TestBuildReportPayload:
    def test_round_trip_shape(self, db):
        base = _local_noon("2026-03-01 12:00:00")
        for i in range(6):
            _msg(db, i % 2, f"今天天气不错{i}", base + i * 3600)
        db.commit()

        out = ReportService().build_report_payload(1, base - _DAY, base + 2 * _DAY)
        assert out["ok"] is True
        assert out["kind"] == "report"
        assert out["version"] == rmod.REPORT_VERSION
        assert out["contact"]["sensitive"] is True
        assert out["stats"]["total"] == 6
        assert out["report"]["chars"] == sum(len(f"今天天气不错{i}") for i in range(6))
        assert "milestones" in out["story"] and "chemistry" in out["story"]

    def test_empty_window_rejected(self, db):
        base = _local_noon("2026-03-01 12:00:00")
        _msg(db, 1, "窗外的消息", base)
        db.commit()
        out = ReportService().build_report_payload(1, base + 10 * _DAY, base + 11 * _DAY)
        assert out["ok"] is False

    def test_window_excludes_outside(self, db):
        base = _local_noon("2026-03-01 12:00:00")
        _msg(db, 1, "窗内", base)
        _msg(db, 1, "窗外", base + 30 * _DAY)
        db.commit()
        out = ReportService().build_report_payload(1, base - _DAY, base + _DAY)
        assert out["stats"]["total"] == 1
        assert out["report"]["chars"] == len("窗内")

    def test_temperature_latest_row(self, db):
        base = _local_noon("2026-03-01 12:00:00")
        _msg(db, 1, "聊一句", base)
        db.execute(
            "INSERT INTO affinity_scores (conversation_id, overall_score,"
            " analysis_version, created_at) VALUES (1, 66.0, 1, 100), (1, 82.0, 1, 200)"
        )
        db.commit()
        out = ReportService().build_report_payload(1, base - _DAY, base + _DAY)
        assert out["report"]["temperature"] == {"score": 82, "label": "炽热"}

    def test_temperature_none_without_analysis(self, db):
        base = _local_noon("2026-03-01 12:00:00")
        _msg(db, 1, "聊一句", base)
        db.commit()
        out = ReportService().build_report_payload(1, base - _DAY, base + _DAY)
        assert out["report"]["temperature"] is None


class TestMemeMining:
    def test_recurring_phrase_ranked_with_exact_counts(self, db):
        base = _local_noon("2026-03-01 08:00:00")
        # 「干饭大王」连续实词组合高频复现（双方都说）——梗页要挖的形态
        for i in range(10):
            _msg(db, 1, f"干饭大王又赢了{i}", base + i * 120)
            _msg(db, 0, f"认输吧干饭大王{i}", base + i * 120 + 60)
        db.commit()
        service = ReportService()
        memes = service._mine_memes(1, base - _DAY, base + _DAY)
        assert memes, "高频复现短语应入榜"
        hit = next(m for m in memes if m["text"] == "干饭大王")
        # 精确计数 = 含该短语的消息条数（10+10 条都含），分侧各 10
        assert hit["count"] == 20
        assert hit["me"] == 10 and hit["ta"] == 10
        # 母串（认输干饭大王）与子串（认输干饭）不重复入榜
        texts = [m["text"] for m in memes]
        assert not ("认输干饭" in texts and "认输干饭大王" in texts)
        # 等距抽样 + LIKE 计数确定性：两次挖掘结果一致
        assert service._mine_memes(1, base - _DAY, base + _DAY) == memes

    def test_rare_phrase_not_listed(self, db):
        base = _local_noon("2026-03-01 08:00:00")
        # 每条内容独有（数字打断相邻性），无任何复现短语
        for i in range(30):
            _msg(db, i % 2, f"独白{i}碎语{chr(0x4E00 + i)}", base + i * 120)
        db.commit()
        memes = ReportService()._mine_memes(1, base - _DAY, base + _DAY)
        # 无任何短语达到样本/全窗门槛 → 空榜（页面跳分镜）
        assert memes == []

    def test_like_wildcard_escaped(self, db):
        # 短语含 LIKE 通配符时精确计数不得放大（% 会匹配一切）
        assert rmod._like_escape("100%确信") == "100\\%确信"
        base = _local_noon("2026-03-01 08:00:00")
        for i in range(9):
            _msg(db, 1, "进度100%完成", base + i * 120)
        db.commit()
        count, me = ReportService()._count_phrase(1, base - _DAY, base + _DAY, "100%完成")
        assert count == 9 and me == 9

    def test_min_total_gate(self, db):
        # 样本内高频但全窗仅 6 条 < 8 门槛 → 不入榜
        base = _local_noon("2026-03-01 08:00:00")
        for i in range(6):
            _msg(db, 1, f"晚安宝贝做个好梦{i}", base + i * 120)
        db.commit()
        memes = ReportService()._mine_memes(1, base - _DAY, base + _DAY)
        assert all(m["count"] >= rmod.REPORT_MEME_MIN_TOTAL for m in memes)


class TestRhythmAndEmoji:
    def test_greeting_rhythm_day_boundaries(self, db):
        # 一天：首条 8 点（我）→ 早安天；末条 23 点（TA）→ 晚安天
        d1 = _local_noon("2026-03-01 08:00:00")
        _msg(db, 1, "早安", d1)
        _msg(db, 0, "晚安", _local_noon("2026-03-01 23:00:00"))
        # 一天：首条 12 点（非早安）末条 21 点（非晚安）
        _msg(db, 1, "午间", _local_noon("2026-03-02 12:00:00"))
        _msg(db, 0, "傍晚", _local_noon("2026-03-02 21:00:00"))
        db.commit()
        rhythm = ReportService()._rhythm(1, _local_noon("2026-03-01 00:00:00"),
                                         _local_noon("2026-03-03 00:00:00"))
        assert rhythm["morning_days"] == 1
        assert rhythm["morning_by_me"] == 1
        assert rhythm["night_days"] == 1
        assert rhythm["night_by_me"] == 0

    def test_emoji_window_top(self, db):
        base = _local_noon("2026-03-01 12:00:00")
        _msg(db, 1, "开心😂😂", base)
        _msg(db, 1, "再发😂", base + 60)
        _msg(db, 0, "对方[呲牙]", base + 120)
        _msg(db, 0, "窗外不计😂", base + 30 * _DAY)
        db.commit()
        emoji = ReportService()._window_emoji(1, base - _DAY, base + _DAY)
        assert emoji is not None
        keys_me = {(i["key"], i["count"]) for i in emoji["top_me"]}
        assert ("😂", 3) in keys_me  # 窗外那条不计
        assert any(i["key"] == "呲牙" and i["kind"] == "builtin" for i in emoji["top_ta"])

    def test_emoji_none_when_silent(self, db):
        base = _local_noon("2026-03-01 12:00:00")
        _msg(db, 1, "纯文字没有任何表情", base)
        db.commit()
        assert ReportService()._window_emoji(1, base - _DAY, base + _DAY) is None


class TestBridge:
    def test_bridge_date_parsing_and_pass_through(self, db, monkeypatch):
        base = _local_noon("2026-03-01 12:00:00")
        _msg(db, 1, "窗内消息", base)
        db.commit()
        captured = {}

        class _Fake:
            def build_report_payload(self, cid, from_ts, to_ts, wxid=""):
                captured["args"] = (cid, from_ts, to_ts, wxid)
                return {"ok": True}

        monkeypatch.setattr(
            "app.services.analysis.report_service.ReportService", _Fake
        )
        bridge = DeepAnalysisApiMixin()
        out = bridge.get_report_payload(1, "2026-03-01", "2026-03-02", "wxid_x")
        assert out["ok"] is True
        cid, from_ts, to_ts, wxid = captured["args"]
        assert cid == 1 and wxid == "wxid_x"
        assert datetime.fromtimestamp(from_ts).strftime("%Y-%m-%d") == "2026-03-01"
        # to_date 收口到当日 23:59:59
        assert datetime.fromtimestamp(to_ts).strftime("%H:%M:%S") == "23:59:59"

    def test_bridge_requires_dates(self):
        bridge = DeepAnalysisApiMixin()
        assert bridge.get_report_payload(1, "", "")["ok"] is False
