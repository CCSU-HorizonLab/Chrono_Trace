"""分享海报导出测试：PNG 校验 / 路径穿越 / 海报 payload 敏感字段标注。

内存真形表 + 真 PNG 字节（PIL 不可用则手工最小 PNG 头）。
"""
import base64
import os
import sqlite3
import sys
from datetime import datetime

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import app.services.analysis.deep_analysis_service as deepmod
from app.services.analysis.deep_analysis_service import DeepAnalysisService
from app.webview.api.deep_analysis import DeepAnalysisApiMixin


@pytest.fixture
def db(monkeypatch):
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
        # 列名与 schema.sql 真形一致（nickname/remark，无 display_name）——
        # 曾因自建列掩蔽生产 SQL 的 no such column 错误
        "CREATE TABLE contacts (id INTEGER PRIMARY KEY, account_wxid TEXT DEFAULT '',"
        " username TEXT, nickname TEXT, remark TEXT, avatar_path TEXT)"
    )
    conn.execute(
        "CREATE TABLE messages (id INTEGER PRIMARY KEY, conversation_id INT, "
        "is_sender INT, message_type INT DEFAULT 1, content TEXT, timestamp INT)"
    )
    conn.execute(
        "CREATE TABLE sentiment_cache (message_id INTEGER UNIQUE, polarity INT, "
        "intensity REAL, created_at INT)"
    )
    conn.execute(
        "CREATE TABLE message_preprocessed (message_id INTEGER PRIMARY KEY, cleaned_content TEXT)"
    )
    conn.execute(
        "CREATE TABLE affinity_scores (id INTEGER PRIMARY KEY, conversation_id INT,"
        " overall_score REAL, analysis_version INT, created_at INT)"
    )
    # 默契统计依赖的两张预处理产物表（真形见 schema.sql）
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
    monkeypatch.setattr(deepmod, "get_db", lambda: conn)
    yield conn
    conn.close()


def seed(db, conversation_id=1, n_each=40, start_ts=1_700_000_000):
    me_first = None
    for i in range(n_each):
        for side in (1, 0):
            cur = db.execute(
                "INSERT INTO messages (conversation_id, is_sender, message_type, content, timestamp)"
                " VALUES (?, ?, 1, ?, ?)",
                (conversation_id, side, f"聊聊天内容{i}", start_ts + i * 7200 + side * 300),
            )
            if me_first is None and side == 1:
                me_first = cur.lastrowid
    db.execute(
        "INSERT INTO messages (conversation_id, is_sender, message_type, content, timestamp)"
        " VALUES (?, 1, 1, ?, ?)",
        (conversation_id, "今天这一段对话真的让人感到非常开心和放松呀",
         start_ts + 200 * 3600),
    )
    quote_id = db.execute("SELECT MAX(id) FROM messages").fetchone()[0]
    db.execute(
        "INSERT INTO sentiment_cache (message_id, polarity, intensity, created_at)"
        " VALUES (?, 1, 0.6, 1)", (quote_id,),
    )
    db.commit()
    return me_first, quote_id


# 最小合法 PNG：8 字节签名（save 只验签名）
PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


class TestSaveShareImage:
    def test_save_png_ok(self, tmp_path, monkeypatch):
        bridge = DeepAnalysisApiMixin()
        monkeypatch.setattr("tempfile.gettempdir", lambda: str(tmp_path))
        data_url = "data:image/png;base64," + base64.b64encode(PNG_BYTES).decode()
        result = bridge.save_share_image(data_url, "我们的时光.png")
        assert result["ok"] is True
        assert result["file_name"].endswith(".png")
        assert "chrono_trace_export" in result["file_path"]

    def test_reject_non_png(self):
        bridge = DeepAnalysisApiMixin()
        jpeg = "data:image/jpeg;base64," + base64.b64encode(b"\xff\xd8\xff" + b"x" * 32).decode()
        result = bridge.save_share_image(jpeg, "a.png")
        assert result["ok"] is False
        assert "PNG" in result["error"]

    def test_reject_path_traversal(self, tmp_path, monkeypatch):
        """../../evil.png 被白名单化，落盘文件不逃出导出目录。"""
        bridge = DeepAnalysisApiMixin()
        monkeypatch.setattr("tempfile.gettempdir", lambda: str(tmp_path))
        data_url = base64.b64encode(PNG_BYTES).decode()
        result = bridge.save_share_image(data_url, "../../evil.png")
        assert result["ok"] is True
        out_dir = tmp_path / "chrono_trace_export"
        saved = list(out_dir.iterdir())
        assert all(f.parent == out_dir for f in saved)
        assert not (tmp_path / "evil.png").exists()

    def test_reject_oversize(self):
        bridge = DeepAnalysisApiMixin()
        blob = b"\x89PNG" + b"\x00" * (20 * 1024 * 1024 + 1)
        result = bridge.save_share_image(base64.b64encode(blob).decode(), "big.png")
        assert result["ok"] is False
        assert "20MB" in result["error"]


class TestPosterPayload:
    def test_sensitive_fields_marked(self, db):
        db.execute(
            "INSERT INTO conversations (id, account_wxid, username, display_name) VALUES (1, '', 'wxid_a', '小明')"
        )
        seed(db)
        payload = DeepAnalysisService().build_poster_payload(1, 1_699_000_000, 1_701_000_000)
        assert payload["ok"] is True
        assert payload["contact"]["sensitive"] is True
        assert payload["contact"]["display_name"] == "小明"
        assert payload["quotes"]["sensitive"] is True
        assert payload["quotes"]["items"], "正向长消息应命中金句"

    def test_avatar_missing_is_none(self, db):
        """无头像路径 → avatar None 不抛。"""
        db.execute(
            "INSERT INTO conversations (id, account_wxid, username, display_name) VALUES (1, '', 'wxid_a', '小明')"
        )
        seed(db)
        payload = DeepAnalysisService().build_poster_payload(1, 1_699_000_000, 1_701_000_000)
        assert payload["contact"]["avatar"] is None

    def test_contact_name_prefers_remark(self, db):
        """名称链：contacts.remark > nickname > conversations.display_name。"""
        db.execute(
            "INSERT INTO conversations (id, account_wxid, username, display_name)"
            " VALUES (1, 'acc', 'wxid_a', '原始名')"
        )
        db.execute(
            "INSERT INTO contacts (account_wxid, username, remark, nickname)"
            " VALUES ('acc', 'wxid_a', '备注名', '昵称')"
        )
        seed(db)
        payload = DeepAnalysisService().build_poster_payload(1, 1_699_000_000, 1_701_000_000)
        assert payload["contact"]["display_name"] == "备注名"

    def test_big5_missing_not_blocking(self, db):
        """大五未生成 → big5.me/other 为 None，海报其余字段完整。"""
        db.execute(
            "INSERT INTO conversations (id, account_wxid, username, display_name) VALUES (1, '', 'wxid_a', '小明')"
        )
        seed(db)
        payload = DeepAnalysisService().build_poster_payload(1, 1_699_000_000, 1_701_000_000)
        assert payload["big5"]["me"] is None
        assert payload["big5"]["other"] is None
        assert payload["stats"]["total"] > 0
        assert payload["emotion_curve"]["bucket"] == "week"
        assert isinstance(payload["top_words"]["all"], list)

    def test_stats_split(self, db):
        db.execute(
            "INSERT INTO conversations (id, account_wxid, username, display_name) VALUES (1, '', 'wxid_a', '小明')"
        )
        seed(db, n_each=10)
        payload = DeepAnalysisService().build_poster_payload(1, 1_699_000_000, 1_701_000_000)
        stats = payload["stats"]
        assert stats["self_count"] + stats["other_count"] == stats["total"]
        assert stats["total"] >= 21  # 10×2 + 1 金句候选


class TestPosterStory:
    """story 字段：里程碑复用 + 默契统计直查（逐字段独立降级 None）。"""

    def _seed_conversation(self, db):
        db.execute(
            "INSERT INTO conversations (id, account_wxid, username, display_name)"
            " VALUES (1, '', 'wxid_a', '小明')"
        )
        seed(db)

    def test_story_fields_values(self, db):
        self._seed_conversation(db)
        # 深夜消息：本地 02:30（不依赖测试机时区构造本地时间戳）
        late_ts = int(datetime(2023, 11, 16, 2, 30, 0).timestamp())
        db.execute(
            "INSERT INTO messages (conversation_id, is_sender, message_type, content, timestamp)"
            " VALUES (1, 1, 1, '睡不着', ?)",
            (late_ts,),
        )
        # 回复链：TA→我 120s、我→TA 180s、一条异常被剔除、一条窗外的被剔除
        ids = {}
        for key, is_sender, ts in (
            ("a_sent", 0, 1_700_500_000), ("a_reply", 1, 1_700_500_120),
            ("b_sent", 1, 1_700_501_000), ("b_reply", 0, 1_700_501_180),
            ("out_sent", 0, 1_698_000_000), ("out_reply", 1, 1_698_000_060),
        ):
            ids[key] = db.execute(
                "INSERT INTO messages (conversation_id, is_sender, message_type,"
                " content, timestamp) VALUES (1, ?, 1, '回复链', ?)",
                (is_sender, ts),
            ).lastrowid
        rt_rows = (
            (ids["a_sent"], ids["a_reply"], 120.0, 0),
            (ids["b_sent"], ids["b_reply"], 180.0, 0),
            (ids["a_reply"], ids["b_sent"], 999.0, 1),          # 异常剔除
            (ids["out_sent"], ids["out_reply"], 60.0, 0),       # 窗外剔除
        )
        db.executemany(
            "INSERT INTO response_times (conversation_id, sent_message_id,"
            " reply_message_id, response_time_seconds, is_abnormal, created_at)"
            " VALUES (1, ?, ?, ?, ?, 1)",
            rt_rows,
        )
        # 会话发起：窗内 user×2 + other×1，窗外一条不计
        sess_rows = (
            (1_700_100_000, 1_700_100_600, 3, "user"),
            (1_700_200_000, 1_700_200_600, 3, "other"),
            (1_700_300_000, 1_700_300_600, 3, "user"),
            (1_698_500_000, 1_698_500_600, 3, "user"),
        )
        db.executemany(
            "INSERT INTO sessions (conversation_id, start_time, end_time,"
            " message_count, initiator, created_at) VALUES (1, ?, ?, ?, ?, 1)",
            sess_rows,
        )
        db.commit()

        payload = DeepAnalysisService().build_poster_payload(1, 1_699_000_000, 1_701_000_000)
        story = payload["story"]
        assert any(ev["kind"] == "first_message" for ev in story["milestones"])

        chem = story["chemistry"]
        late = chem["late_night"]
        assert late is not None and late["count"] >= 1
        assert late["self_count"] + late["other_count"] == late["count"]

        peak = chem["peak_day"]
        assert peak is not None and peak["count"] > 0
        assert peak["self_count"] + peak["other_count"] == peak["count"]
        assert len(peak["date"]) == 10  # YYYY-MM-DD

        rs = chem["reply_stats"]
        assert rs["count"] == 2
        assert rs["avg"] == 150.0 and rs["median"] == 150.0
        assert rs["self_avg"] == 120.0 and rs["other_avg"] == 180.0

        init = chem["initiator"]
        assert init["user_sessions"] == 2 and init["other_sessions"] == 1
        assert init["user_ratio"] == pytest.approx(2 / 3)

    def test_story_degrades_without_analysis(self, db):
        """未跑分析的库：reply_stats/initiator 为 None，核心分镜照常出数。"""
        self._seed_conversation(db)
        payload = DeepAnalysisService().build_poster_payload(1, 1_699_000_000, 1_701_000_000)
        chem = payload["story"]["chemistry"]
        assert chem["reply_stats"] is None
        assert chem["initiator"] is None
        assert chem["peak_day"] is not None  # 零依赖分析产物
        assert payload["story"]["milestones"]  # 里程碑纯统计，同样零依赖

    def test_story_empty_conversation(self, db):
        """无任何消息：chemistry 全 None、里程碑为空列表，payload 仍 ok。"""
        db.execute(
            "INSERT INTO conversations (id, account_wxid, username, display_name)"
            " VALUES (1, '', 'wxid_a', '小明')"
        )
        payload = DeepAnalysisService().build_poster_payload(1, 1_699_000_000, 1_701_000_000)
        assert payload["ok"] is True
        assert payload["story"]["milestones"] == []
        assert payload["story"]["chemistry"] == {
            "late_night": None, "peak_day": None,
            "reply_stats": None, "initiator": None,
        }

    def test_story_additive_sensitive_unchanged(self, db):
        """story 为纯加性字段：敏感标注仍集中在 contact/quotes。"""
        self._seed_conversation(db)
        payload = DeepAnalysisService().build_poster_payload(1, 1_699_000_000, 1_701_000_000)
        assert payload["quotes"]["sensitive"] is True
        assert payload["contact"]["sensitive"] is True
        assert "sensitive" not in payload["story"]


class TestOpenExportFolder:
    def test_returns_ok(self, tmp_path, monkeypatch):
        monkeypatch.setattr("tempfile.gettempdir", lambda: str(tmp_path))
        monkeypatch.setattr("webbrowser.open", lambda uri: True)
        bridge = DeepAnalysisApiMixin()
        result = bridge.open_export_folder()
        assert result["ok"] is True
        assert (tmp_path / "chrono_trace_export").is_dir()
