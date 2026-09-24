"""P1.1 relationship state shadow tests: derivation, ADD-only versioning, TTL fix."""

import json
import os
import sqlite3
import sys
import time


sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.realtime.rag_config import load_rag_settings
from app.services.realtime.rag_relationship_policy import (
    derive_relationship_state,
    refresh_relationship_state_shadow,
)
from app.services.realtime.rag_store import RagStore


def _store():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    return conn, RagStore(conn)


def _profile_and_features():
    return (
        {
            "personality_tags": ["活泼健谈"],
            "chat_style": "轻快、爱用梗",
            "communication_tips": "别讲大道理，接梗就好",
            "relationship_note": "熟络的日常朋友",
        },
        {
            "initiative": {
                "total_sessions": 435,
                "other_initiated": 280,
                "self_initiated": 155,
            }
        },
    )


def _seed_boundary_fact(store, *, confidence=0.72, kind="relationship_boundary"):
    return store.upsert_fact(
        account_wxid="wxid_a",
        conversation_id=1,
        subject="contact",
        kind=kind,
        content="对方不喜欢被追问情绪，需要先给空间",
        confidence=confidence,
        as_of=1789900000,
        evidence_message_ids=[11, 12],
    )


def test_derive_maps_initiative_and_band():
    profile, features = _profile_and_features()
    draft = derive_relationship_state(
        profile=profile,
        features_snapshot=features,
        facts=[],
        message_count=3616,
    )
    assert draft.initiative_pattern == "对方更主动"  # 280/435 = 0.644 -> >=0.6
    assert draft.closeness_band == "high"
    assert "高频互动" in draft.stage and "对方更主动" in draft.stage
    assert draft.communication_tips == "别讲大道理，接梗就好"
    assert draft.summary_method == "derived_shadow_profile_only"
    assert draft.confidence == 0.5


def test_derive_aggregates_boundary_facts_with_calibrated_confidence():
    conn, store = _store()
    _seed_boundary_fact(store, confidence=0.70)
    _seed_boundary_fact(store, confidence=0.80, kind="preference_dislike")
    profile, features = _profile_and_features()
    draft = derive_relationship_state(
        profile=profile,
        features_snapshot=features,
        facts=store.list_facts("wxid_a", 1),
        message_count=3616,
    )
    assert "追问情绪" in draft.boundary_summary
    assert len(draft.evidence_fact_ids) == 2
    assert draft.confidence == 0.75  # (0.70 + 0.80) / 2
    assert draft.summary_method == "derived_shadow_profile_and_facts"


def test_derive_returns_none_without_inputs():
    assert derive_relationship_state(profile=None, features_snapshot=None, facts=[], message_count=0) is None


def test_shadow_upsert_versions_and_dedupes_by_evidence_hash():
    conn, store = _store()
    first = store.upsert_relationship_state(
        account_wxid="wxid_a", conversation_id=1,
        stage="高频互动/对方更主动", closeness_band="high",
        initiative_pattern="对方更主动", evidence_hash="hash-1",
        confidence=0.7,
    )
    assert first["changed"] is True

    latest = store.get_latest_relationship_state("wxid_a", 1)
    assert latest is not None and latest["valid_to"] is None

    # 相同 evidence_hash 不产生新版本
    same = store.upsert_relationship_state(
        account_wxid="wxid_a", conversation_id=1,
        stage="高频互动/对方更主动", closeness_band="high",
        initiative_pattern="对方更主动", evidence_hash="hash-1",
        confidence=0.7,
    )
    assert same["changed"] is False
    assert store.count_relationship_states("wxid_a", 1) == 1

    # 新 hash：ADD 新版本，旧版本关闭 valid_to 并保留 supersedes 链
    second = store.upsert_relationship_state(
        account_wxid="wxid_a", conversation_id=1,
        stage="常规往来/双方均衡", closeness_band="medium",
        initiative_pattern="双方均衡", evidence_hash="hash-2",
        confidence=0.8,
    )
    assert second["changed"] is True
    assert store.count_relationship_states("wxid_a", 1) == 2

    new_latest = store.get_latest_relationship_state("wxid_a", 1)
    old = conn.execute(
        "SELECT * FROM rag_relationship_state WHERE id = ?", (first["state_id"],)
    ).fetchone()
    assert old["valid_to"] is not None
    assert new_latest["supersedes_state_id"] == first["state_id"]
    assert new_latest["policy_version"].startswith("rs-v1-")


def test_refresh_respects_disabled_switch(monkeypatch):
    conn, store = _store()
    monkeypatch.setattr(
        "app.services.realtime.rag_relationship_policy.load_rag_settings",
        lambda: {"rag_relationship_policy_shadow_enabled": False},
    )
    result = refresh_relationship_state_shadow(
        store, account_wxid="wxid_a", conversation_id=1, display_name="某人",
    )
    assert result == {"ok": True, "skipped": "disabled"}
    assert store.count_relationship_states("wxid_a", 1) == 0


def test_refresh_skips_when_no_profile_and_no_facts(monkeypatch):
    conn, store = _store()
    monkeypatch.setattr(
        "app.services.realtime.rag_relationship_policy.load_rag_settings",
        lambda: {"rag_relationship_policy_shadow_enabled": True},
    )
    monkeypatch.setattr(
        "app.services.realtime.rag_relationship_policy._load_profile_cache",
        lambda account_wxid, display_name: None,
    )
    result = refresh_relationship_state_shadow(
        store, account_wxid="wxid_a", conversation_id=1, display_name="某人",
    )
    assert result == {"ok": True, "skipped": "no_profile_and_no_facts"}


def test_refresh_writes_shadow_from_profile_and_facts(monkeypatch):
    conn, store = _store()
    _seed_boundary_fact(store, confidence=0.66)
    profile, features = _profile_and_features()
    store.upsert_status("wxid_a", 1, status="ready", document_count=100)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS conversations (id INTEGER PRIMARY KEY, account_wxid TEXT, message_count INTEGER)"
    )
    conn.execute(
        "INSERT INTO conversations (id, account_wxid, message_count) VALUES (1, 'wxid_a', 3616)"
    )

    monkeypatch.setattr(
        "app.services.realtime.rag_relationship_policy.load_rag_settings",
        lambda: {"rag_relationship_policy_shadow_enabled": True},
    )
    monkeypatch.setattr(
        "app.services.realtime.rag_relationship_policy._load_profile_cache",
        lambda account_wxid, display_name: {
            "profile": profile, "features_snapshot": features,
        },
    )
    result = refresh_relationship_state_shadow(
        store, account_wxid="wxid_a", conversation_id=1, display_name="昕",
    )
    assert result["ok"] is True and result["changed"] is True

    latest = store.get_latest_relationship_state("wxid_a", 1)
    assert latest["stage"] == "高频互动/对方更主动"
    assert latest["closeness_band"] == "high"
    assert "追问情绪" in latest["boundary_summary"]
    assert json.loads(latest["evidence_fact_ids_json"])
    assert latest["summary_method"] == "derived_shadow_profile_and_facts"
