"""问答真实问法留档（qa_query_log）：三入口成败均落一行，留档失败静默。

评测集「真实问法分布」的原料从 bridge 层留档（唯一前后端边界，CDP
直调同样覆盖）；service 内部不感知——留档绝不阻断问答主链路。
"""

import os
import sqlite3
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import app.services.analysis.history_qa_service as hqmod
from app.webview.bridge import Bridge


def _db_with_log():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE conversations (id INTEGER PRIMARY KEY, conversation_type TEXT);
        INSERT INTO conversations VALUES (1, 'private');
        CREATE TABLE qa_query_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at INTEGER NOT NULL,
            conversation_id INTEGER NOT NULL,
            source TEXT NOT NULL DEFAULT 'qa',
            query_text TEXT NOT NULL,
            ok INTEGER NOT NULL DEFAULT 1,
            note TEXT
        );
        """
    )
    return conn


def _bridge(monkeypatch, conn):
    import app.db.connection as dbconn
    import app.webview.api as apimod

    monkeypatch.setattr(dbconn, "get_db", lambda: conn)
    monkeypatch.setattr(apimod, "conversation_is_group", lambda cid: False)
    bridge = Bridge.__new__(Bridge)
    monkeypatch.setattr(
        Bridge, "_maybe_start_embedding_backfill", lambda self, cid: False
    )
    return bridge


def test_ask_history_logs_success_and_failure(monkeypatch):
    conn = _db_with_log()
    bridge = _bridge(monkeypatch, conn)

    monkeypatch.setattr(
        hqmod.HistoryQAService, "ask", lambda self, *a, **kw: {"answer": "答"}
    )
    assert bridge.ask_history(1, "TA 最近在忙什么？")["ok"] is True

    def _boom(self, *a, **kw):
        raise hqmod.HistoryQAError("已取消")

    monkeypatch.setattr(hqmod.HistoryQAService, "ask", _boom)
    assert bridge.ask_history(1, "再问一次")["ok"] is False

    rows = conn.execute(
        "SELECT source, query_text, ok, note FROM qa_query_log ORDER BY id"
    ).fetchall()
    assert [r["source"] for r in rows] == ["qa", "qa"]
    assert [r["ok"] for r in rows] == [1, 0]
    assert rows[0]["query_text"] == "TA 最近在忙什么？"
    assert rows[1]["note"] == "已取消"


def test_rehearse_and_avatar_logged(monkeypatch):
    conn = _db_with_log()
    bridge = _bridge(monkeypatch, conn)

    monkeypatch.setattr(
        hqmod.HistoryQAService, "rehearse", lambda self, *a, **kw: {"ok": True}
    )
    assert bridge.rehearse_reply(1, "周末有空吗")["ok"] is True

    import app.services.analysis.avatar_chat_service as avmod

    monkeypatch.setattr(
        avmod.AvatarChatService, "chat", lambda self, *a, **kw: {"reply": "嗯"}
    )
    assert bridge.ask_avatar_chat(1, "在吗")["ok"] is True

    rows = conn.execute(
        "SELECT source, query_text FROM qa_query_log ORDER BY id"
    ).fetchall()
    assert [(r["source"], r["query_text"]) for r in rows] == [
        ("rehearse", "周末有空吗"),
        ("avatar", "在吗"),
    ]


def test_logging_failure_never_blocks(monkeypatch):
    """留档写库炸掉：问答照常返回，绝不反向阻断主链路。"""
    import app.db.connection as dbconn
    import app.webview.api as apimod

    def _broken_db():
        raise RuntimeError("db gone")

    monkeypatch.setattr(dbconn, "get_db", _broken_db)
    monkeypatch.setattr(apimod, "conversation_is_group", lambda cid: False)
    monkeypatch.setattr(
        hqmod.HistoryQAService, "ask", lambda self, *a, **kw: {"answer": "答"}
    )
    bridge = Bridge.__new__(Bridge)
    monkeypatch.setattr(
        Bridge, "_maybe_start_embedding_backfill", lambda self, cid: False
    )
    assert bridge.ask_history(1, "留档失败也要能答")["ok"] is True
