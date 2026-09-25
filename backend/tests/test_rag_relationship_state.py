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
    refresh_after_fact_feedback,
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
        lambda account_wxid, display_name, conn=None: None,
    )
    result = refresh_relationship_state_shadow(
        store, account_wxid="wxid_a", conversation_id=1, display_name="某人",
    )
    assert result == {"ok": True, "skipped": "no_profile_and_no_facts"}


def test_derive_accepts_llm_short_kind_facts():
    """T3：LLM 归一化短名（boundary/preference/personal_fact/relation_state）
    必须进入关系派生证据——此前 73 条 LLM 事实全部不在证据范围。"""
    conn, store = _store()
    fact_ids = [
        store.upsert_fact(
            account_wxid="wxid_a",
            conversation_id=1,
            subject="对方",
            kind=kind,
            content=content,
            confidence=0.8,
            as_of=1789900000,
            evidence_message_ids=[21],
            summary_method="llm_shadow",
        )
        for kind, content in [
            ("boundary", "对方不喜欢我让她自己查百度，希望直接解释"),
            ("preference", "对方喜欢喝奶茶，三分糖"),
            ("personal_fact", "对方在深圳一家中小公司做后端开发"),
            ("relation_state", "两人处于暧昧试探阶段"),
            # 长名旧事实仍应被认出
            ("relationship_boundary", "对方介意拿她和别人比较"),
        ]
    ]
    profile, features = _profile_and_features()
    draft = derive_relationship_state(
        profile=profile,
        features_snapshot=features,
        facts=store.list_facts("wxid_a", 1),
        message_count=3616,
    )
    for fact_id in fact_ids:
        assert fact_id in draft.evidence_fact_ids
    assert "百度" in draft.boundary_summary  # 短名 boundary 事实进入边界摘要
    assert draft.confidence == 0.8


def test_boundary_summary_separates_subjects():
    """T3：边界聚合区分"对方的边界"与"我的边界"（subject 字段）。"""
    conn, store = _store()
    store.upsert_fact(
        account_wxid="wxid_a", conversation_id=1, subject="对方", kind="boundary",
        content="对方介意被已读不回", confidence=0.8, as_of=1789900000,
        evidence_message_ids=[21], summary_method="llm_shadow",
    )
    store.upsert_fact(
        account_wxid="wxid_a", conversation_id=1, subject="我", kind="boundary",
        content="我介意被拿和别人比较", confidence=0.75, as_of=1789900000,
        evidence_message_ids=[22], summary_method="llm_shadow",
    )
    draft = derive_relationship_state(
        profile=None,
        features_snapshot=None,
        facts=store.list_facts("wxid_a", 1),
        message_count=3616,
    )
    assert draft is not None
    assert "对方的边界：" in draft.boundary_summary and "已读不回" in draft.boundary_summary
    assert "我的边界：" in draft.boundary_summary and "拿和别人比较" in draft.boundary_summary
    assert draft.boundary_summary.index("对方的边界") < draft.boundary_summary.index("我的边界")


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
        lambda account_wxid, display_name, conn=None: {
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


def test_refresh_after_fact_feedback_drops_disabled_evidence(monkeypatch):
    """T9：用户标注「不准确」后关系策略刷新，evidence 剔除禁用事实。

    真实库场景：5385 被用户标 inaccurate 后，01:30 生成的 state 仍引用
    它——反馈只禁用单条，影子层不刷新。
    """
    conn, store = _store()
    fact_id = _seed_boundary_fact(store, confidence=0.7)
    profile, features = _profile_and_features()
    store.upsert_status("wxid_a", 1, status="ready", document_count=100)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS conversations (id INTEGER PRIMARY KEY, account_wxid TEXT, display_name TEXT, message_count INTEGER)"
    )
    conn.execute(
        "INSERT INTO conversations (id, account_wxid, display_name, message_count) VALUES (1, 'wxid_a', '昕', 3616)"
    )
    monkeypatch.setattr(
        "app.services.realtime.rag_relationship_policy.load_rag_settings",
        lambda: {"rag_relationship_policy_shadow_enabled": True},
    )
    monkeypatch.setattr(
        "app.services.realtime.rag_relationship_policy._load_profile_cache",
        lambda account_wxid, display_name, conn=None: {
            "profile": profile, "features_snapshot": features,
        },
    )
    # 初始影子行引用该事实
    first = refresh_relationship_state_shadow(
        store, account_wxid="wxid_a", conversation_id=1, display_name="昕",
    )
    assert first["changed"] is True
    assert fact_id in json.loads(
        store.get_latest_relationship_state("wxid_a", 1)["evidence_fact_ids_json"]
    )

    # 用户标注不准确 → 禁用 → 反馈后刷新
    store.set_fact_user_feedback(fact_id, "inaccurate")
    result = refresh_after_fact_feedback(store, fact_id)
    assert result.get("ok") is True
    latest = store.get_latest_relationship_state("wxid_a", 1)
    eids = json.loads(latest["evidence_fact_ids_json"])
    assert fact_id not in eids  # 禁用事实不再被引用
    assert "追问情绪" not in (latest["boundary_summary"] or "")

    # 事实不存在时不抛异常
    assert refresh_after_fact_feedback(store, 999999).get("skipped") == "fact_not_found"
