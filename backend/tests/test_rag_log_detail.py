"""P0.2b badge drill-down API tests: get_rag_log_detail."""

import json
import os
import sqlite3
import sys
import time


sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.realtime.rag_store import RagStore
from app.webview.bridge import Bridge


def _conn():
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
    now = int(time.time())
    conn.executemany(
        "INSERT INTO messages (content, created_at) VALUES (?, ?)",
        [("她说她对虾过敏，上次吃完进了医院", now), ("那家店在五道口", now)],
    )
    conn.commit()
    return conn


def _seed_log(conn, *, with_sensitive=False):
    store = RagStore(conn)
    normal_fact_id = store.upsert_fact(
        account_wxid="wxid_a",
        conversation_id=1,
        subject="contact",
        kind="health",
        content="对方对虾过敏",
        confidence=0.62,
        as_of=1789900000,
        evidence_message_ids=[1],
    )
    doc_id = store.upsert_document(
        account_wxid="wxid_a",
        conversation_id=1,
        doc_type="shared_memory",
        source_table="test",
        source_id="t1",
        source_ts=1789800000,
        content="双方曾聊过五道口的那家店",
    )
    sensitive_fact_id = None
    if with_sensitive:
        sensitive_fact_id = store.upsert_fact(
            account_wxid="wxid_a",
            conversation_id=1,
            subject="contact",
            kind="family",
            content="对方母亲住院",
            confidence=0.8,
            sensitivity="sensitive",
        )
    injected_ids = [normal_fact_id, doc_id] + (
        [sensitive_fact_id] if with_sensitive else []
    )
    injected_types = ["fact_memory", "shared_memory"] + (
        ["fact_memory"] if with_sensitive else []
    )
    candidate_ids = injected_ids + [99999]
    log_id = store.insert_retrieval_log(
        account_wxid="wxid_a",
        conversation_id=1,
        query_text="吃什么",
        document_ids=injected_ids,
        selected_doc_types=injected_types,
        fact_ids=[normal_fact_id] + ([sensitive_fact_id] if with_sensitive else []),
        evidence_ids=[1],
        rag_gate_decision="inject",
        rag_strategy="facts",
        rag_injection_mode="reply",
        rag_latency_ms=120,
        rag_hit_count=len(candidate_ids),
        candidate_ids=candidate_ids,
        injected_item_ids=injected_ids,
    )
    store.conn.commit()
    return log_id, normal_fact_id, doc_id, sensitive_fact_id


def _bridge(conn):
    bridge = Bridge.__new__(Bridge)
    import app.db.connection as db_conn

    db_conn.get_db = lambda: conn
    return bridge


def test_get_rag_log_detail_returns_injected_facts_documents_and_evidence(monkeypatch):
    conn = _conn()
    log_id, fact_id, doc_id, _ = _seed_log(conn)
    monkeypatch.setattr("app.db.connection.get_db", lambda: conn)
    bridge = Bridge.__new__(Bridge)

    detail = bridge.get_rag_log_detail(log_id)

    assert detail["ok"] is True
    log = detail["log"]
    assert log["id"] == log_id
    assert log["gate_decision"] == "inject"
    assert log["strategy"] == "facts"
    assert log["run_provenance"] == "production"

    injected = detail["injected"]
    assert len(injected) == 2
    fact_item = next(i for i in injected if i["source"] == "fact")
    assert fact_item["id"] == fact_id
    assert fact_item["content"] == "对方对虾过敏"
    assert fact_item["subject"] == "contact"
    assert fact_item["kind"] == "health"
    assert fact_item["confidence"] == 0.62
    assert fact_item["evidence_excerpts"] == ["她说她对虾过敏，上次吃完进了医院"]

    doc_item = next(i for i in injected if i["source"] == "document")
    assert doc_item["id"] == doc_id
    assert doc_item["doc_type"] == "shared_memory"
    assert "五道口" in doc_item["content"]

    assert detail["candidates"]["count"] == 3
    assert detail["candidates"]["injected_count"] == 2
    assert detail["candidates"]["not_injected_ids"] == [99999]


def test_get_rag_log_detail_filters_sensitive_rows_defensively(monkeypatch):
    conn = _conn()
    log_id, fact_id, doc_id, sensitive_id = _seed_log(conn, with_sensitive=True)
    monkeypatch.setattr("app.db.connection.get_db", lambda: conn)
    bridge = Bridge.__new__(Bridge)

    detail = bridge.get_rag_log_detail(log_id)

    assert detail["ok"] is True
    contents = [i["content"] for i in detail["injected"]]
    assert "对方对虾过敏" in contents
    assert all("住院" not in c for c in contents)


def test_get_rag_log_detail_missing_log_returns_error(monkeypatch):
    conn = _conn()
    monkeypatch.setattr("app.db.connection.get_db", lambda: conn)
    bridge = Bridge.__new__(Bridge)

    detail = bridge.get_rag_log_detail(424242)

    assert detail["ok"] is False
    assert detail["error"] == "log_not_found"
