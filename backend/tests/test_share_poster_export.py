"""分享海报导出测试：PNG 校验 / 路径穿越 / 海报 payload 敏感字段标注。

内存真形表 + 真 PNG 字节（PIL 不可用则手工最小 PNG 头）。
"""
import base64
import os
import sqlite3
import sys

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
        "CREATE TABLE contacts (id INTEGER PRIMARY KEY, account_wxid TEXT DEFAULT '',"
        " username TEXT, display_name TEXT, nickname TEXT, avatar_path TEXT)"
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


class TestOpenExportFolder:
    def test_returns_ok(self, tmp_path, monkeypatch):
        monkeypatch.setattr("tempfile.gettempdir", lambda: str(tmp_path))
        monkeypatch.setattr("webbrowser.open", lambda uri: True)
        bridge = DeepAnalysisApiMixin()
        result = bridge.open_export_folder()
        assert result["ok"] is True
        assert (tmp_path / "chrono_trace_export").is_dir()
