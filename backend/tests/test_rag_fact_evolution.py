"""演变链可视化（P2.2）：store 链回溯 + bridge get_fact_evolution + 归属/敏感防御。"""

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


def _make_chain(store, contents):
    """按时间序落库并逐环 supersede，返回 id 列表（旧→新）。"""
    ids = [
        _upsert_fact(store, content=content, as_of=1789900000 + i * 100)
        for i, content in enumerate(contents)
    ]
    for old_id, new_id in zip(ids, ids[1:]):
        store.supersede_fact(old_id, new_id)
    return ids


def test_chain_returns_oldest_first_with_statuses():
    conn, store = _store()
    old_id, mid_id, new_id = _make_chain(
        store, ["对方对虾过敏", "对方对海鲜过敏", "对方对虾不过敏了"]
    )

    chain = store.get_fact_chain(new_id)
    assert [node["id"] for node in chain] == [old_id, mid_id, new_id]
    # 旧版本退役、链尾存活
    assert [node["status"] for node in chain] == ["superseded", "superseded", "active"]
    # 单节事实链就是自己
    single = _upsert_fact(store, content="对方喜欢爬山")
    assert [node["id"] for node in store.get_fact_chain(single)] == [single]


def test_chain_cycle_and_depth_guards():
    conn, store = _store()
    first, second = _make_chain(store, ["旧说法", "新说法"])
    # 数据异常：手工把首节指回尾节形成环，回溯必须止步而非死循环
    conn.execute(
        "UPDATE rag_facts SET supersedes_fact_id=? WHERE id=?", (second, first)
    )
    chain = store.get_fact_chain(second)
    assert len(chain) == 2
    assert {node["id"] for node in chain} == {first, second}

    # 深度上限：25 节长链 + max_depth=20 → 至多 21 节，截断丢的是最旧段
    ids = _make_chain(store, [f"说法 {i}" for i in range(25)])
    long_chain = store.get_fact_chain(ids[-1], max_depth=20)
    assert len(long_chain) == 21
    assert long_chain[0]["id"] == ids[4]
    assert long_chain[-1]["id"] == ids[-1]


def test_chain_missing_fact_returns_none():
    _, store = _store()
    assert store.get_fact_chain(99999) is None


def test_bridge_fact_evolution_flow(monkeypatch):
    conn, store = _store()
    old_id, new_id = _make_chain(store, ["对方对虾过敏", "对方对海鲜过敏"])
    _upsert_fact(
        store,
        kind="hobby_or_game",
        content="对方最近在玩某款游戏",
        sensitivity="sensitive",
    )
    monkeypatch.setattr("app.db.connection.get_db", lambda: conn)
    bridge = Bridge.__new__(Bridge)
    monkeypatch.setattr(bridge, "_resolve_account_wxid", lambda account_wxid="": "wxid_a")

    result = bridge.get_fact_evolution(new_id)
    assert result["ok"] is True
    assert [node["id"] for node in result["nodes"]] == [old_id, new_id]
    assert [node["is_current"] for node in result["nodes"]] == [False, True]
    assert result["nodes"][0]["content"] == "对方对虾过敏"

    # 列表接口透出链入口徽标字段：链尾有值、无历史事实为 None
    listing = bridge.get_contact_facts(1, account_wxid="wxid_a")
    assert listing["ok"] is True
    by_content = {fact["content"]: fact for fact in listing["facts"]}
    assert by_content["对方对海鲜过敏"]["supersedes_fact_id"] == old_id
    # 无历史事实该字段为 None（徽标不显示）
    assert by_content["对方最近在玩某款游戏"]["supersedes_fact_id"] is None


def test_bridge_fact_evolution_masks_sensitive_and_rejects_foreign_account(
    monkeypatch,
):
    conn, store = _store()
    old_id, new_id = _make_chain(
        store, ["对方对虾过敏", "对方对海鲜过敏"]
    )
    conn.execute(
        "UPDATE rag_facts SET sensitivity='sensitive' WHERE id=?", (old_id,)
    )
    monkeypatch.setattr("app.db.connection.get_db", lambda: conn)
    bridge = Bridge.__new__(Bridge)
    monkeypatch.setattr(bridge, "_resolve_account_wxid", lambda account_wxid="": "wxid_a")

    result = bridge.get_fact_evolution(new_id)
    assert result["ok"] is True
    # 敏感旧版：只回标记不回原文（深度防御，与 get_rag_log_detail 同口径）
    sensitive_node = next(n for n in result["nodes"] if n["id"] == old_id)
    assert sensitive_node["sensitive"] is True
    assert sensitive_node["content"] == ""

    # 跨账号：按不存在处理，不泄露链内容
    monkeypatch.setattr(bridge, "_resolve_account_wxid", lambda account_wxid="": "wxid_b")
    assert bridge.get_fact_evolution(new_id) == {"ok": False, "error": "fact_not_found"}
    assert bridge.get_fact_evolution(99999)["error"] == "fact_not_found"
