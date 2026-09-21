"""Tests for the v4 three-track retrieval evaluator."""

import json
import os
import sqlite3
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.realtime.rag_store import RagStore
from scripts.evaluate_rag_retrieval import evaluate


def _gold():
    return [{
        "id": "coffee",
        "query_text": "她喜欢什么咖啡？",
        "category": "偏好",
        "gold_fact_ids": ["f1"],
        "gold_document_ids": ["d1"],
        "expected_retrieve": True,
        "expected_scope": "all",
    }]


def test_evaluator_splits_tracks_and_calculates_recall_mrr_ci():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    store = RagStore(conn)
    store.insert_retrieval_log(
        account_wxid="a", conversation_id=1, query_text="她喜欢什么咖啡？",
        document_ids=["d2", "d1"], rag_enabled=True, rag_retrieved=True,
        rag_gate_decision="inject", rag_gate_reason="document_match",
        rag_strategy="documents", retrieval_source="document", query_scope="all",
    )
    store.insert_retrieval_log(
        account_wxid="a", conversation_id=1, query_text="她喜欢什么咖啡？",
        document_ids=[], fact_ids=["f1"], rag_enabled=True, rag_retrieved=True,
        rag_gate_decision="inject", rag_gate_reason="fact_memory_match",
        rag_strategy="facts", retrieval_source="fact", query_scope="all",
    )
    store.insert_retrieval_log(
        account_wxid="a", conversation_id=1, query_text="她喜欢什么咖啡？",
        document_ids=[], rag_enabled=False, rag_retrieved=False,
        rag_gate_decision="no_hit", rag_gate_reason="rag_disabled",
        retrieval_source="none", query_scope="all",
    )
    report = evaluate(conn, _gold(), [
        {"track": "document_rag", "nli_label": "entailed"},
        {"track": "fact_path", "nli_label": "entailed"},
    ])
    assert report["tracks"]["document_rag"]["summary"]["recall_at_5"] == 1.0
    assert report["tracks"]["document_rag"]["summary"]["mrr"] == 0.5
    assert report["tracks"]["fact_path"]["summary"]["recall_at_5"] == 1.0
    assert report["tracks"]["fact_path"]["summary"]["query_scope_accuracy"] == 1.0
    assert report["tracks"]["fact_path"]["faithfulness"]["score"] == 1.0
    assert report["release_gate"]["status"] == "pass"


def test_evaluator_does_not_fabricate_missing_runtime_or_nli_data():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    RagStore(conn)
    report = evaluate(conn, _gold())
    fact = report["tracks"]["fact_path"]
    assert fact["summary"]["recall_at_5"] is None
    assert fact["summary"]["matched_logs"] == 0
    assert fact["faithfulness"]["score"] is None
    assert fact["faithfulness"]["status"] == "pending_runtime_data"
    assert report["release_gate"]["status"] == "pending_runtime_data"
