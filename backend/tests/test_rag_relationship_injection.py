"""P1.3 relationship policy injection tests: slot injection, redaction, badge."""

import os
import sqlite3
import sys


sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.realtime.llm_engine import LLMSuggestionEngine
from app.services.realtime.rag_context_builder import RagContextBuilder
from app.services.realtime.rag_store import RagStore


def _builder_with_state(
    monkeypatch,
    *,
    injection_enabled=True,
    shadow_enabled=True,
    sensitive=False,
    confidence=0.72,
):
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    store = RagStore(conn)
    store.upsert_relationship_state(
        account_wxid="wxid_a",
        conversation_id=1,
        stage="高频互动/对方更主动",
        closeness_band="high",
        initiative_pattern="对方更主动",
        boundary_summary="对方不喜欢被追问情绪",
        communication_tips="别讲大道理，接梗就好",
        evidence_hash="hash-1",
        confidence=confidence,
        sensitivity="sensitive" if sensitive else "normal",
    )
    store.conn.commit()
    builder = RagContextBuilder(store=store)
    monkeypatch.setattr(
        "app.services.realtime.rag_context_builder.load_rag_settings",
        lambda: {
            "rag_relationship_policy_injection_enabled": injection_enabled,
            "rag_relationship_policy_shadow_enabled": shadow_enabled,
        },
    )
    return conn, store, builder


def test_inject_builds_policy_from_shadow_state(monkeypatch):
    conn, store, builder = _builder_with_state(monkeypatch)
    context = {}
    state_id = builder._inject_relationship_policy(
        context, account_wxid="wxid_a", conversation_id=1,
        remote_model=False, redaction_disabled=False,
    )
    assert state_id is not None
    policy = context["relationship_policy"]
    assert policy["stage"] == "高频互动/对方更主动"
    assert policy["closeness_band"] == "high"
    assert policy["boundary_summary"] == "对方不喜欢被追问情绪"
    assert policy["confidence"] == 0.72
    assert policy["policy_version"].startswith("rs-v1-")


def test_inject_respects_switch_and_missing_state(monkeypatch):
    conn, store, builder = _builder_with_state(monkeypatch, injection_enabled=False)
    context = {}
    assert builder._inject_relationship_policy(
        context, account_wxid="wxid_a", conversation_id=1,
        remote_model=False, redaction_disabled=False,
    ) is None
    assert "relationship_policy" not in context

    conn2, store2, builder2 = _builder_with_state(monkeypatch)
    context2 = {}
    assert builder2._inject_relationship_policy(
        context2, account_wxid="wxid_a", conversation_id=999,
        remote_model=False, redaction_disabled=False,
    ) is None
    assert "relationship_policy" not in context2


def test_inject_stops_when_shadow_switch_off(monkeypatch):
    """T6：影子开关关闭=停用关系策略链路，历史策略行不再注入。"""
    conn, store, builder = _builder_with_state(monkeypatch, shadow_enabled=False)
    context = {}
    assert builder._inject_relationship_policy(
        context, account_wxid="wxid_a", conversation_id=1,
        remote_model=False, redaction_disabled=False,
    ) is None
    assert "relationship_policy" not in context


def test_inject_skips_low_confidence_state(monkeypatch):
    """T6：低于置信度下限的影子行不注入（留在影子层观察）。"""
    conn, store, builder = _builder_with_state(monkeypatch, confidence=0.40)
    context = {}
    assert builder._inject_relationship_policy(
        context, account_wxid="wxid_a", conversation_id=1,
        remote_model=False, redaction_disabled=False,
    ) is None
    assert "relationship_policy" not in context
    # 下限之上正常注入
    conn2, store2, builder2 = _builder_with_state(monkeypatch, confidence=0.55)
    context2 = {}
    assert builder2._inject_relationship_policy(
        context2, account_wxid="wxid_a", conversation_id=1,
        remote_model=False, redaction_disabled=False,
    ) is not None


def test_inject_skips_sensitive_shadow_row(monkeypatch):
    conn, store, builder = _builder_with_state(monkeypatch, sensitive=True)
    context = {}
    assert builder._inject_relationship_policy(
        context, account_wxid="wxid_a", conversation_id=1,
        remote_model=False, redaction_disabled=False,
    ) is None


def test_inject_redacts_text_fields_for_remote_model(monkeypatch):
    conn, store, builder = _builder_with_state(monkeypatch)

    class _Redactor:
        def redact(self, text, **kwargs):
            class _R:
                redacted_text = "[已脱敏]" + text
            return _R()

    monkeypatch.setattr(
        "app.services.realtime.rag_context_builder.PrivacyRedactor",
        lambda conn: _Redactor(),
    )
    context = {}
    builder._inject_relationship_policy(
        context, account_wxid="wxid_a", conversation_id=1,
        remote_model=True, redaction_disabled=False,
    )
    policy = context["relationship_policy"]
    assert policy["boundary_summary"].startswith("[已脱敏]")
    assert policy["communication_tips"].startswith("[已脱敏]")
    # 结构化枚举不脱敏
    assert policy["stage"] == "高频互动/对方更主动"


def test_inject_redaction_failure_keeps_enums_drops_text(monkeypatch):
    conn, store, builder = _builder_with_state(monkeypatch)

    class _BrokenRedactor:
        def redact(self, text, **kwargs):
            raise RuntimeError("redaction blew up")

    monkeypatch.setattr(
        "app.services.realtime.rag_context_builder.PrivacyRedactor",
        lambda conn: _BrokenRedactor(),
    )
    context = {}
    builder._inject_relationship_policy(
        context, account_wxid="wxid_a", conversation_id=1,
        remote_model=True, redaction_disabled=False,
    )
    policy = context["relationship_policy"]
    assert policy["boundary_summary"] == ""
    assert policy["communication_tips"] == ""
    assert policy["stage"] == "高频互动/对方更主动"


def test_prompt_renders_relationship_policy_block():
    engine = LLMSuggestionEngine()
    context = {
        "relationship_policy": {
            "stage": "高频互动/对方更主动",
            "closeness_band": "high",
            "initiative_pattern": "对方更主动",
            "boundary_summary": "对方不喜欢被追问情绪",
            "communication_tips": "别讲大道理，接梗就好",
            "confidence": 0.72,
            "policy_version": "rs-v1-1",
        },
    }
    prompt = engine._build_prompt("manual_request", "maintain", context)
    assert "【当前关系策略（联系人级背景，供判断分寸）】" in prompt
    assert "关系阶段: 高频互动/对方更主动" in prompt
    assert "亲密度: 高" in prompt
    assert "相处边界: 对方不喜欢被追问情绪" in prompt
    assert "置信度: 72%" in prompt
    assert "不要向对方复述或主动提起" in prompt


def test_badge_shows_relationship_policy_without_fact_items():
    engine = LLMSuggestionEngine()
    summary = engine._build_rag_context_summary(
        {
            "_rag_debug": {
                "rag_enabled": True,
                "rag_retrieved": True,
                "rag_hit_count": 0,
                "relationship_policy_injected": True,
            },
        }
    )
    assert summary["state"] == "relationship_policy"
    assert summary["label"] == "已参考关系画像"

    # fact 命中仍然优先于纯关系策略徽章
    summary2 = engine._build_rag_context_summary(
        {
            "_rag_debug": {
                "rag_enabled": True,
                "rag_hit_count": 3,
                "relationship_policy_injected": True,
            },
            "retrieval_context": {
                "items": [{"document_id": 1, "doc_type": "fact_memory"}]
            },
        }
    )
    assert summary2["state"] == "fact_hit"
