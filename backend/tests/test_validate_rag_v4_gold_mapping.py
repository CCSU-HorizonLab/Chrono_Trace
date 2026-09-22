"""Tests for content-free gold mapping validation."""

import os
import sqlite3
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.realtime.rag_store import RagStore
from scripts.validate_rag_v4_gold_mapping import validate_mapping


def test_mapping_validator_checks_scope_status_and_duplicates_without_content():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    store = RagStore(conn)
    good_id = store.upsert_fact(
        account_wxid="account-a", conversation_id=1, subject="对方",
        kind="preference_like", content="喜欢咖啡", confidence=0.9,
    )
    cross_id = store.upsert_fact(
        account_wxid="account-b", conversation_id=1, subject="对方",
        kind="preference_like", content="喜欢茶", confidence=0.9,
    )
    result = validate_mapping(
        conn,
        {"fact_good": good_id, "fact_cross": cross_id, "fact_missing": 999, "fact_duplicate": good_id},
        account_wxid="account-a",
        conversation_id=1,
    )
    assert result["valid"] is False
    assert result["release_ready"] is False
    reasons = {item["reason"] for item in result["errors"]}
    assert {"account_scope_mismatch", "runtime_id_missing", "duplicate_runtime_id"} <= reasons
    assert "喜欢咖啡" not in str(result)


def test_mapping_validator_accepts_active_fact_and_reports_unconstrained_scope():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    store = RagStore(conn)
    fact_id = store.upsert_fact(
        account_wxid="account-a", conversation_id=1, subject="对方",
        kind="preference_like", content="喜欢咖啡", confidence=0.9,
    )
    result = validate_mapping(conn, {"fact_preference": fact_id})
    assert result["valid"] is True
    assert result["release_ready"] is False
    assert result["status"] == "pending_scope_or_entries"
    assert result["mapped_entries"] == 1
    assert result["warnings"] == [{"reason": "mapping_scope_not_fully_constrained"}]
