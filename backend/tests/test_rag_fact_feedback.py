"""P0.6 memory correction tests: tombstone, user feedback, restore, bridge APIs."""

import os
import sqlite3
import sys


sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.realtime.rag.store import RagStore
from app.webview.bridge import Bridge


def _store():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            content TEXT,
            created_at INTEGER
        )
        """
    )
    conn.execute("INSERT INTO messages (content, created_at) VALUES ('她说她对虾过敏', 1)")
    return conn, RagStore(conn)


def _upsert_fact(store, **overrides):
    payload = dict(
        account_wxid="wxid_a",
        conversation_id=1,
        subject="contact",
        kind="health",
        content="对方对虾过敏",
        confidence=0.62,
        as_of=1789900000,
        evidence_message_ids=[1],
    )
    payload.update(overrides)
    return store.upsert_fact(**payload)


def test_forget_tombstone_survives_reindex_upsert():
    conn, store = _store()
    fact_id = _upsert_fact(store)
    assert store.count_active_facts("wxid_a", 1) == 1

    result = store.set_fact_user_feedback(fact_id, "forget")
    assert result["ok"] is True
    assert store.count_active_facts("wxid_a", 1) == 0

    # 增量索引重扫同一事实：ON CONFLICT 会尝试复位 enabled，墓碑必须压制
    same_id = _upsert_fact(store)
    assert same_id == fact_id
    row = conn.execute("SELECT enabled FROM rag_facts WHERE id = ?", (fact_id,)).fetchone()
    assert row["enabled"] == 0
    assert store.count_active_facts("wxid_a", 1) == 0

    tombstone = conn.execute(
        "SELECT action FROM rag_fact_user_feedback WHERE fact_id = ?", (fact_id,)
    ).fetchone()
    assert tombstone["action"] == "forget"


def test_inaccurate_feedback_marks_and_disables():
    conn, store = _store()
    fact_id = _upsert_fact(store)

    result = store.set_fact_user_feedback(fact_id, "inaccurate", reason="记错了，是蟹过敏")
    assert result["ok"] is True

    row = conn.execute(
        "SELECT enabled FROM rag_facts WHERE id = ?", (fact_id,)
    ).fetchone()
    assert row["enabled"] == 0
    fb = conn.execute(
        "SELECT action, reason FROM rag_fact_user_feedback WHERE fact_id = ?", (fact_id,)
    ).fetchone()
    assert fb["action"] == "inaccurate"
    assert "蟹" in fb["reason"]


def test_restore_removes_tombstone_and_reenables():
    conn, store = _store()
    fact_id = _upsert_fact(store)
    store.set_fact_user_feedback(fact_id, "inaccurate")

    result = store.restore_fact(fact_id)
    assert result["ok"] is True

    row = conn.execute("SELECT enabled FROM rag_facts WHERE id = ?", (fact_id,)).fetchone()
    assert row["enabled"] == 1
    assert (
        conn.execute(
            "SELECT COUNT(*) FROM rag_fact_user_feedback WHERE fact_id = ?", (fact_id,)
        ).fetchone()[0]
        == 0
    )
    # 恢复后重扫不再被压制
    _upsert_fact(store)
    row = conn.execute("SELECT enabled FROM rag_facts WHERE id = ?", (fact_id,)).fetchone()
    assert row["enabled"] == 1


def test_invalid_action_and_missing_fact_rejected():
    conn, store = _store()
    fact_id = _upsert_fact(store)

    assert store.set_fact_user_feedback(fact_id, "delete")["ok"] is False
    assert store.set_fact_user_feedback(99999, "forget")["error"] == "fact_not_found"
    assert store.restore_fact(99999)["error"] == "fact_not_found"


def test_bridge_contact_facts_and_feedback_flow(monkeypatch):
    conn, store = _store()
    fact_id = _upsert_fact(store)
    _upsert_fact(
        store,
        kind="hobby_or_game",
        content="对方最近在玩杀戮尖塔",
        evidence_message_ids=[1],
    )
    monkeypatch.setattr("app.db.connection.get_db", lambda: conn)
    bridge = Bridge.__new__(Bridge)

    listing = bridge.get_contact_facts(1, account_wxid="wxid_a")
    assert listing["ok"] is True
    assert listing["total"] == 2
    assert listing["disabled_count"] == 0
    first = next(f for f in listing["facts"] if f["id"] == fact_id)
    assert first["content"] == "对方对虾过敏"
    assert first["enabled"] is True
    assert first["evidence_excerpts"] == ["她说她对虾过敏"]

    forget_result = bridge.set_fact_feedback(fact_id, "forget")
    assert forget_result["ok"] is True

    listing = bridge.get_contact_facts(1, account_wxid="wxid_a")
    assert listing["disabled_count"] == 1
    forgotten = next(f for f in listing["facts"] if f["id"] == fact_id)
    assert forgotten["enabled"] is False
    assert forgotten["user_action"] == "forget"
    active = next(f for f in listing["facts"] if f["id"] != fact_id)
    assert active["enabled"] is True

    restore_result = bridge.set_fact_feedback(fact_id, "restore")
    assert restore_result["ok"] is True
    listing = bridge.get_contact_facts(1, account_wxid="wxid_a")
    assert listing["disabled_count"] == 0


def test_bridge_contact_facts_pagination_has_stable_order(monkeypatch):
    conn, store = _store()
    ids = [
        _upsert_fact(store, content=f"第 {i} 条记忆", evidence_message_ids=[])
        for i in range(5)
    ]
    monkeypatch.setattr("app.db.connection.get_db", lambda: conn)
    bridge = Bridge.__new__(Bridge)

    pages = [
        bridge.get_contact_facts(1, account_wxid="wxid_a", limit=2, offset=offset)
        for offset in (0, 2, 4)
    ]
    assert all(page["ok"] for page in pages)
    assert [page["total"] for page in pages] == [2, 2, 1]
    assert all(page["fact_count"] == 5 for page in pages)
    assert all(page["enabled_fact_count"] == 5 for page in pages)
    assert [fact["id"] for page in pages for fact in page["facts"]] == ids[::-1]
