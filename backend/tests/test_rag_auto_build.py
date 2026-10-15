"""好感度分析完成后的 RAG 索引自动排队：跳过条件与排队行为。"""

import os
import sqlite3
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.webview.api.affinity import _auto_enqueue_rag_index


@pytest.fixture
def db(monkeypatch):
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE conversations (id INTEGER PRIMARY KEY, account_wxid TEXT)")
    conn.execute("INSERT INTO conversations VALUES (1, 'wxid_me')")
    import app.db.connection as dbmod

    monkeypatch.setattr(dbmod, "get_db", lambda: conn)
    yield conn
    conn.close()


@pytest.fixture
def rag_env(monkeypatch):
    import app.services.realtime.rag.config as ragcfg
    import app.services.realtime.rag.indexer as idxmod
    import app.services.realtime.rag.store as storemod

    state = {
        "settings": {"rag_enabled": True},
        "status": None,       # 无 rag_index_status 行
        "active": {},         # 无构建中/排队中
        "enqueued": [],
    }

    monkeypatch.setattr(ragcfg, "load_rag_settings", lambda: state["settings"])
    monkeypatch.setattr(idxmod, "get_active_and_queued", lambda: dict(state["active"]))
    monkeypatch.setattr(
        idxmod,
        "RagIndexQueue",
        SimpleNamespace(enqueue=lambda a, c: state["enqueued"].append((a, c))),
    )

    class _Store:
        def __init__(self, conn):
            pass

        def get_status(self, account, conv):
            return state["status"]

    monkeypatch.setattr(storemod, "RagStore", _Store)
    return state


def test_enqueue_when_never_indexed(db, rag_env):
    """从未建过索引 → 排队构建。"""
    _auto_enqueue_rag_index(1)
    assert rag_env["enqueued"] == [("wxid_me", 1)]


def test_skip_when_index_ready(db, rag_env):
    """已有 ready 索引 → 不重复重建（增量由监听/建议链路负责）。"""
    rag_env["status"] = {"status": "ready", "enabled": 1}
    _auto_enqueue_rag_index(1)
    assert rag_env["enqueued"] == []


def test_skip_when_contact_disabled(db, rag_env):
    """联系人记忆被显式停用（清空记忆语义）→ 不被分析动作复活。"""
    rag_env["status"] = {"status": "pending", "enabled": 0}
    _auto_enqueue_rag_index(1)
    assert rag_env["enqueued"] == []


def test_skip_when_rag_globally_off(db, rag_env):
    rag_env["settings"] = {"rag_enabled": False}
    _auto_enqueue_rag_index(1)
    assert rag_env["enqueued"] == []


def test_skip_when_already_building(db, rag_env):
    rag_env["active"] = {("wxid_me", 1): "building"}
    _auto_enqueue_rag_index(1)
    assert rag_env["enqueued"] == []


def test_missing_conversation_is_silent(db, rag_env):
    """会话不存在/无账号：静默跳过不抛错。"""
    _auto_enqueue_rag_index(999)
    assert rag_env["enqueued"] == []
