"""P1.2 contact_preference 策略层测试：槽位聚合、版本链、注入护栏、prompt。"""

import json
import os
import sqlite3
import sys


sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.realtime.llm_engine import LLMSuggestionEngine
from app.services.realtime.rag.contact_preference import (
    derive_contact_preferences,
    refresh_contact_preferences_shadow,
)
from app.services.realtime.rag.context_builder import RagContextBuilder
from app.services.realtime.rag.store import RagStore


class _StubEmbedding:
    """可控向量：同 topic 返回同向量（聚槽），不同 topic 正交。

    用递增索引定位维度（str hash 跨进程随机化，不能用）。
    """

    DIM = 16

    def __init__(self):
        self.markers: list[str] = []

    def embed_texts(self, texts):
        out = []
        for text in texts:
            index = None
            for i, marker in enumerate(self.markers):
                if marker in text:
                    index = i
                    break
            if index is None:
                self.markers.append(text[:6])
                index = len(self.markers) - 1
            vec = [0.0] * self.DIM
            vec[index % self.DIM] = 1.0
            out.append(vec)
        return out


def _store():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    return conn, RagStore(conn)


def _fact(store, *, kind, content, subject="对方", confidence=0.7, sensitivity="normal", mid=1):
    return store.upsert_fact(
        account_wxid="wxid_a",
        conversation_id=1,
        subject=subject,
        kind=kind,
        content=content,
        confidence=confidence,
        as_of=1789900000,
        sensitivity=sensitivity,
        evidence_message_ids=[mid],
        summary_method="llm_shadow",
    )


def test_derive_clusters_same_topic_and_excludes_self_subject():
    conn, store = _store()
    # 同主题两个表达（应聚为一槽）+ 一个不同主题 + 我方事实（应排除） + 敏感（应排除）
    _fact(store, kind="preference", content="对方喜欢吃火锅，微辣", confidence=0.8, mid=1)
    _fact(store, kind="preference", content="对方爱吃火锅，每次都要微辣锅底", confidence=0.7, mid=2)
    _fact(store, kind="preference", content="对方在准备考研，每天刷题", confidence=0.75, mid=3)
    _fact(store, kind="preference", content="我喜欢吃日料", subject="我", mid=4)
    _fact(store, kind="preference", content="对方银行卡密码相关", sensitivity="sensitive", mid=5)

    embedding = _StubEmbedding()
    embedding.markers = ["火锅", "考研"]
    drafts = derive_contact_preferences(
        facts=store.list_facts("wxid_a", 1), embedding_service=embedding
    )
    hotpot = [d for d in drafts if "火锅" in d.summary]
    assert len(hotpot) == 1
    assert hotpot[0].support_count == 2  # 同主题聚槽
    assert hotpot[0].slot_kind == "preference"
    assert len(hotpot[0].evidence_fact_ids) == 2
    assert hotpot[0].summary.startswith("对方喜欢吃火锅")  # 最高置信为代表
    assert any("考研" in d.summary for d in drafts)
    assert all("日料" not in d.summary for d in drafts)  # 我方事实排除
    assert all("密码" not in d.summary for d in drafts)  # 敏感排除


def test_derive_avoid_kind_and_no_embedding_fallback():
    conn, store = _store()
    _fact(store, kind="preference_dislike", content="对方不吃香菜，点菜要避开", confidence=0.8)
    _fact(store, kind="preference", content="对方喜欢喝奶茶三分糖", confidence=0.7)

    drafts = derive_contact_preferences(facts=store.list_facts("wxid_a", 1))
    # embedding 不可用退化为每事实一槽，仍可用
    assert len(drafts) == 2
    kinds = {d.slot_kind for d in drafts}
    assert kinds == {"preference", "avoid"}


def test_shadow_refresh_versions_and_dedupes(monkeypatch):
    conn, store = _store()
    monkeypatch.setattr(
        "app.services.realtime.rag.contact_preference.load_rag_settings",
        lambda: {"rag_relationship_policy_shadow_enabled": True},
    )
    embedding = _StubEmbedding()
    embedding.markers = ["虾"]
    _fact(store, kind="preference", content="对方对虾过敏，点菜避开虾", confidence=0.85)
    first = refresh_contact_preferences_shadow(
        store, account_wxid="wxid_a", conversation_id=1, embedding_service=embedding
    )
    assert first["ok"] is True and first["written"] == 1
    # 相同证据重刷：不产生新版本
    second = refresh_contact_preferences_shadow(
        store, account_wxid="wxid_a", conversation_id=1, embedding_service=embedding
    )
    assert second["written"] == 0
    assert store.count_contact_preferences("wxid_a", 1) == 1

    # 证据变化（新增同主题更高置信事实）：代表换人→旧槽退役、新槽开
    _fact(store, kind="preference", content="对方对虾过敏严重，连虾油都不能用", confidence=0.9)
    third = refresh_contact_preferences_shadow(
        store, account_wxid="wxid_a", conversation_id=1, embedding_service=embedding
    )
    assert third["ok"] is True and third["retired"] == 1
    active = store.list_contact_preferences("wxid_a", 1)
    assert len(active) == 1  # 活跃槽不重复
    assert active[0]["support_count"] == 2  # 同主题聚槽，证据并集
    rows = conn.execute(
        "SELECT id, valid_to, supersedes_pref_id FROM rag_contact_preferences ORDER BY id"
    ).fetchall()
    assert len(rows) == 2 and rows[0]["valid_to"] is not None

    # 开关关闭：跳过
    monkeypatch.setattr(
        "app.services.realtime.rag.contact_preference.load_rag_settings",
        lambda: {"rag_relationship_policy_shadow_enabled": False},
    )
    disabled = refresh_contact_preferences_shadow(
        store, account_wxid="wxid_a", conversation_id=1
    )
    assert disabled == {"ok": True, "skipped": "disabled"}


def test_inject_respects_guards_and_budget(monkeypatch):
    conn, store = _store()
    for i in range(8):
        store.upsert_contact_preference(
            account_wxid="wxid_a", conversation_id=1,
            slot_key=f"preference:{i}", slot_kind="preference",
            summary=f"对方偏好事项{i}：内容具体自包含",
            evidence_hash=f"hash-{i}", confidence=0.7 if i < 6 else 0.40,
        )
    # 敏感行深度防御跳过
    conn.execute(
        "UPDATE rag_contact_preferences SET sensitivity='sensitive' WHERE slot_key='preference:0'"
    )
    conn.commit()
    builder = RagContextBuilder(store=store)
    monkeypatch.setattr(
        "app.services.realtime.rag.context_builder.load_rag_settings",
        lambda: {
            "rag_relationship_policy_injection_enabled": True,
            "rag_relationship_policy_shadow_enabled": True,
        },
    )
    context = {}
    ids = builder._inject_contact_preferences(
        context, account_wxid="wxid_a", conversation_id=1,
        remote_model=False, redaction_disabled=False,
    )
    # 8 槽：1 敏感跳过 + 2 低置信跳过 → 5 注入（≤6 上限）
    assert len(ids) == 5
    prefs = context["contact_preferences"]
    assert all(p["confidence"] >= 0.55 for p in prefs)

    # 影子开关关闭 → 不注入（T6 同款护栏）
    monkeypatch.setattr(
        "app.services.realtime.rag.context_builder.load_rag_settings",
        lambda: {
            "rag_relationship_policy_injection_enabled": True,
            "rag_relationship_policy_shadow_enabled": False,
        },
    )
    ctx2 = {}
    assert builder._inject_contact_preferences(
        ctx2, account_wxid="wxid_a", conversation_id=1,
        remote_model=False, redaction_disabled=False,
    ) == []
    assert "contact_preferences" not in ctx2


def test_inject_redacts_for_remote_model(monkeypatch):
    conn, store = _store()
    store.upsert_contact_preference(
        account_wxid="wxid_a", conversation_id=1,
        slot_key="preference:1", slot_kind="avoid",
        summary="对方不吃香菜，点菜避开", evidence_hash="h1", confidence=0.8,
    )
    conn.commit()
    builder = RagContextBuilder(store=store)
    monkeypatch.setattr(
        "app.services.realtime.rag.context_builder.load_rag_settings",
        lambda: {
            "rag_relationship_policy_injection_enabled": True,
            "rag_relationship_policy_shadow_enabled": True,
        },
    )

    class _Redactor:
        def redact(self, text, **kwargs):
            class _R:
                redacted_text = "[已脱敏]" + text
            return _R()

    monkeypatch.setattr(
        "app.services.realtime.rag.context_builder.PrivacyRedactor",
        lambda conn: _Redactor(),
    )
    context = {}
    ids = builder._inject_contact_preferences(
        context, account_wxid="wxid_a", conversation_id=1,
        remote_model=True, redaction_disabled=False,
    )
    assert ids == [1]
    assert context["contact_preferences"][0]["summary"].startswith("[已脱敏]")


def test_prompt_renders_contact_preference_block():
    engine = LLMSuggestionEngine()
    context = {
        "contact_preferences": [
            {"slot_kind": "avoid", "summary": "对方不吃香菜，点菜要避开", "confidence": 0.8},
            {"slot_kind": "preference", "summary": "对方喜欢喝奶茶，三分糖", "confidence": 0.7},
        ],
    }
    prompt = engine._build_prompt("manual_request", "maintain", context)
    assert "【对方偏好与雷点（速查，据此调整建议内容与措辞）】" in prompt
    assert "[雷点] 对方不吃香菜，点菜要避开（置信 80%）" in prompt
    assert "[偏好] 对方喜欢喝奶茶，三分糖（置信 70%）" in prompt
    assert "不要向对方复述或主动提起" in prompt


def test_feedback_refresh_drops_disabled_preference(monkeypatch):
    """用户纠错后偏好槽刷新：证据含禁用事实的槽位重新派生剔除引用。"""
    conn, store = _store()
    fid = _fact(store, kind="preference", content="对方对虾过敏，点菜避开虾", confidence=0.85)
    monkeypatch.setattr(
        "app.services.realtime.rag.contact_preference.load_rag_settings",
        lambda: {"rag_relationship_policy_shadow_enabled": True},
    )
    embedding = _StubEmbedding()
    embedding.markers = ["虾"]
    refresh_contact_preferences_shadow(
        store, account_wxid="wxid_a", conversation_id=1, embedding_service=embedding
    )
    before = store.list_contact_preferences("wxid_a", 1)
    assert len(before) == 1
    assert fid in json.loads(before[0]["evidence_fact_ids_json"])

    # 未被引用的事实触发定向刷新：跳过（防退化拆槽）
    untouched = refresh_contact_preferences_shadow(
        store, account_wxid="wxid_a", conversation_id=1, touched_fact_id=999999
    )
    assert untouched.get("skipped") == "fact_not_referenced"

    # 被引用的事实禁用后定向刷新：唯一证据消失 → 槽位退役（读侧不再注入）
    store.set_fact_user_feedback(fid, "inaccurate")
    touched = refresh_contact_preferences_shadow(
        store, account_wxid="wxid_a", conversation_id=1, touched_fact_id=fid
    )
    assert touched.get("ok") is True
    assert store.list_contact_preferences("wxid_a", 1) == []  # 活跃槽清空
    # 审计行保留（ADD-only 不删行）
    assert store.count_contact_preferences("wxid_a", 1) == 1
