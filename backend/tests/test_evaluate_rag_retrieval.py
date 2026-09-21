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
    assert report["tracks"]["document_rag"]["summary"]["unmatched_runtime_logs"] == 0
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


def test_symbolic_gold_ids_stay_pending_until_mapped_to_runtime_ids():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    store = RagStore(conn)
    store.insert_retrieval_log(
        account_wxid="a", conversation_id=1, query_text="她有什么偏好？",
        document_ids=[101], fact_ids=[101], rag_enabled=True, rag_retrieved=True,
        rag_gate_decision="inject", rag_gate_reason="fact_memory_match",
        rag_strategy="facts", retrieval_source="fact", query_scope="all",
    )
    report = evaluate(conn, [{
        "id": "preference", "query_text": "她有什么偏好？",
        "gold_fact_ids": ["fact_preference_coffee"], "expected_retrieve": True,
    }])
    summary = report["tracks"]["fact_path"]["summary"]
    assert summary["gold_mapping_status"] == "pending_symbolic_labels"
    assert summary["recall_at_5"] is None
    assert report["release_gate"]["status"] == "pending_runtime_data"


def test_gold_id_mapping_unlocks_numeric_recall():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    store = RagStore(conn)
    store.insert_retrieval_log(
        account_wxid="a", conversation_id=1, query_text="她喜欢什么？",
        document_ids=[101], fact_ids=[101], rag_enabled=True, rag_retrieved=True,
        rag_gate_decision="inject", rag_gate_reason="fact_memory_match",
        rag_strategy="facts", retrieval_source="fact", query_scope="all",
    )
    report = evaluate(
        conn,
        [{"query_text": "她喜欢什么？", "gold_fact_ids": ["fact_pref"]}],
        gold_mapping={"fact_pref": 101},
    )
    assert report["tracks"]["fact_path"]["summary"]["recall_at_5"] == 1.0


def test_evaluator_reports_sensitive_block_and_identity_isolation_metrics():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    store = RagStore(conn)
    store.insert_retrieval_log(
        account_wxid="account-a", conversation_id=7, query_text="她的手机号是多少？",
        document_ids=[], fact_ids=[], rag_enabled=True, rag_retrieved=False,
        rag_gate_decision="no_hit", rag_gate_reason="sensitive_block",
        rag_strategy="facts", retrieval_source="fact", query_scope="all",
    )
    store.insert_retrieval_log(
        account_wxid="account-a", conversation_id=7, query_text="她喜欢什么？",
        document_ids=[], fact_ids=[], rag_enabled=True, rag_retrieved=False,
        rag_gate_decision="no_hit", rag_gate_reason="no_match",
        rag_strategy="facts", retrieval_source="fact", query_scope="all",
    )
    report = evaluate(conn, [
        {
            "id": "sensitive", "query_text": "她的手机号是多少？",
            "gold_fact_ids": ["f-sensitive"], "expected_retrieve": True,
            "sensitive_block": True, "expected_account_wxid": "account-a",
            "expected_conversation_id": 7,
        },
        {
            "id": "ordinary", "query_text": "她喜欢什么？",
            "gold_fact_ids": ["f-preference"], "expected_retrieve": True,
        },
    ], gold_mapping={"f-sensitive": 101, "f-preference": 102})
    summary = report["tracks"]["fact_path"]["summary"]
    assert summary["sensitive_block"]["precision"] == 0.5
    assert summary["sensitive_block"]["recall"] == 1.0
    assert summary["identity_isolation"]["isolation_rate"] == 1.0
    assert report["release_gate"]["safety_and_identity"] == "pending_runtime_data"
