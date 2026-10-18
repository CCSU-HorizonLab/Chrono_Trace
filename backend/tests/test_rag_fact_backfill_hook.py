"""事实向量欠账自愈挂点测试。

欠账场景：事实抽取与向量写入是两条异步链，抽取出的事实可能落在
ONNX 故障窗口或旧版本时期而无向量。ensure 的 ready 分支早有检查，
但静默联系人（无监听无建议，ensure 从未被调）只能靠 rebuild 的
完成路径与增量跳过路径自愈——本文件覆盖后两个挂点。
"""

import os
import sqlite3
import sys
import time


sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


from app.services.realtime.rag.indexer import RagIndexer, RagIndexQueue
from app.services.realtime.rag.store import RagStore


MODEL = "test/embed-model"
DIM = 8


def _conn():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    return conn


def _seed_conversation(conn):
    """最小会话环境（conversations/messages/sessions 三表 + 两条消息）。"""
    conn.executescript(
        """
        CREATE TABLE conversations (
            id INTEGER PRIMARY KEY,
            account_wxid TEXT NOT NULL,
            username TEXT NOT NULL,
            display_name TEXT,
            message_count INTEGER DEFAULT 0,
            updated_at INTEGER DEFAULT 0,
            is_deleted INTEGER DEFAULT 0
        );
        CREATE TABLE messages (
            id INTEGER PRIMARY KEY,
            conversation_id INTEGER NOT NULL,
            is_sender INTEGER NOT NULL,
            content TEXT,
            message_type INTEGER NOT NULL,
            timestamp INTEGER NOT NULL
        );
        CREATE TABLE sessions (
            id INTEGER PRIMARY KEY,
            conversation_id INTEGER NOT NULL,
            start_time INTEGER,
            end_time INTEGER,
            message_count INTEGER,
            initiator TEXT
        );
        """
    )
    now = int(time.time())
    conn.execute(
        """
        INSERT INTO conversations
        (id, account_wxid, username, display_name, message_count, updated_at)
        VALUES (1, 'wxid_a', 'alice', 'Alice', 2, ?)
        """,
        (now,),
    )
    conn.executemany(
        """
        INSERT INTO messages (id, conversation_id, is_sender, content, message_type, timestamp)
        VALUES (?, 1, ?, ?, 1, ?)
        """,
        [
            (1, 0, "我最近天天在玩某款游戏", now - 600),
            (2, 1, "哪个流派呀", now - 540),
        ],
    )
    conn.commit()


def _seed_active_fact(store):
    """一条活跃事实（无向量）——联系人B实况的最小复现。"""
    now = int(time.time())
    store.conn.execute(
        """
        INSERT INTO rag_facts
        (account_wxid, conversation_id, subject, kind, content, status, enabled,
         confidence, created_at, updated_at)
        VALUES ('wxid_a', 1, 'alice', 'hobby', '对方喜欢玩卡牌游戏', 'active', 1, 0.9, ?, ?)
        """,
        (now, now),
    )
    store.conn.commit()


def _settings(fact_read=True):
    return {
        "rag_embedding_model": MODEL,
        "rag_embedding_dim": DIM,
        "rag_privacy_mode": "balanced",
        "rag_fact_read_enabled": fact_read,
    }


class FakeEmbedding:
    def embed_texts(self, texts):
        return [[0.1] * DIM for _ in texts]


def _instrument(monkeypatch):
    """替换队列投递为记录器（不起真 worker 线程）。"""
    calls = []
    monkeypatch.setattr(
        RagIndexQueue,
        "enqueue_fact_backfill",
        lambda account_wxid, conversation_id: calls.append((account_wxid, int(conversation_id))),
    )
    return calls


class TestCompletionPath:
    def test_enqueues_when_fact_vectors_missing(self, monkeypatch):
        conn = _conn()
        store = RagStore(conn)
        _seed_conversation(conn)
        _seed_active_fact(store)
        monkeypatch.setattr(
            "app.services.realtime.rag.indexer.load_rag_settings",
            lambda: _settings(),
        )
        calls = _instrument(monkeypatch)

        status = RagIndexer(store=store, embedding_service=FakeEmbedding()).rebuild_contact_index(
            account_wxid="wxid_a",
            conversation_id=1,
        )

        assert status["status"] == "ready"
        assert calls == [("wxid_a", 1)]

    def test_no_enqueue_when_vectors_complete(self, monkeypatch):
        conn = _conn()
        store = RagStore(conn)
        _seed_conversation(conn)
        _seed_active_fact(store)
        store.upsert_fact_embedding(
            fact_id=1,
            account_wxid="wxid_a",
            conversation_id=1,
            embedding_model=MODEL,
            embedding_dim=DIM,
            vector=[0.1] * DIM,
        )
        monkeypatch.setattr(
            "app.services.realtime.rag.indexer.load_rag_settings",
            lambda: _settings(),
        )
        calls = _instrument(monkeypatch)

        status = RagIndexer(store=store, embedding_service=FakeEmbedding()).rebuild_contact_index(
            account_wxid="wxid_a",
            conversation_id=1,
        )

        assert status["status"] == "ready"
        assert calls == []

    def test_no_enqueue_when_fact_read_disabled(self, monkeypatch):
        conn = _conn()
        store = RagStore(conn)
        _seed_conversation(conn)
        _seed_active_fact(store)
        monkeypatch.setattr(
            "app.services.realtime.rag.indexer.load_rag_settings",
            lambda: _settings(fact_read=False),
        )
        calls = _instrument(monkeypatch)

        RagIndexer(store=store, embedding_service=FakeEmbedding()).rebuild_contact_index(
            account_wxid="wxid_a",
            conversation_id=1,
        )

        assert calls == []

    def test_no_enqueue_when_no_facts(self, monkeypatch):
        conn = _conn()
        store = RagStore(conn)
        _seed_conversation(conn)
        monkeypatch.setattr(
            "app.services.realtime.rag.indexer.load_rag_settings",
            lambda: _settings(),
        )
        calls = _instrument(monkeypatch)

        RagIndexer(store=store, embedding_service=FakeEmbedding()).rebuild_contact_index(
            account_wxid="wxid_a",
            conversation_id=1,
        )

        assert calls == []


class TestIncrementalSkipPath:
    def test_enqueues_on_silent_skip(self, monkeypatch):
        """增量跳过路径：无新消息直接标 ready，事实欠账也要补投。

        预置与配置指纹完全匹配的 ready 状态 + 水位覆盖全部消息 →
        rebuild 走「无新消息」分支（此前该分支只查 llm_behind）。
        """
        conn = _conn()
        store = RagStore(conn)
        _seed_conversation(conn)
        _seed_active_fact(store)
        store.upsert_status(
            "wxid_a",
            1,
            status="ready",
            embedding_model=MODEL,
            embedding_dim=DIM,
            privacy_mode="balanced",
            document_count=1,
            vector_count=1,
            dirty_since=None,
            index_version=RagIndexer.INDEX_VERSION,
        )
        store.conn.execute(
            """
            UPDATE rag_index_status
            SET message_watermark_ts = ?, last_message_id = 99
            WHERE account_wxid = 'wxid_a' AND conversation_id = 1
            """,
            (int(time.time()),),
        )
        store.conn.commit()
        monkeypatch.setattr(
            "app.services.realtime.rag.indexer.load_rag_settings",
            lambda: _settings(),
        )
        calls = _instrument(monkeypatch)

        status = RagIndexer(store=store, embedding_service=FakeEmbedding()).rebuild_contact_index(
            account_wxid="wxid_a",
            conversation_id=1,
        )

        assert status["status"] == "ready"
        assert calls == [("wxid_a", 1)]
