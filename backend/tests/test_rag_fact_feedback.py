"""P0.6 memory correction tests: tombstone, user feedback, restore, bridge APIs."""

import json
import os
import sqlite3
import sys


sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.realtime.rag.store import RagStore
from app.services.realtime.rag.fact_extractor import StructuredFactExtractor
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
        content="对方最近在玩某款游戏",
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


# ===== 用户纠错下渗抽取回路（语义级拦截守卫） =====


class _StubEmbed:
    def __init__(self, vectors):
        self._vectors = vectors
        self.calls = 0

    def embed_texts(self, texts):
        self.calls += 1
        if isinstance(self._vectors, Exception):
            raise self._vectors
        return self._vectors


def _indexer_with(store, embed):
    import app.services.realtime.rag.indexer as indexer_mod

    indexer = indexer_mod.RagIndexer.__new__(indexer_mod.RagIndexer)
    indexer.store = store
    indexer.embedding_service = embed
    return indexer, indexer_mod


def _deny_with_vector(store, content, vector, reason=None):
    fact_id = _upsert_fact(store, content=content, evidence_message_ids=[])
    store.set_fact_user_feedback(fact_id, "inaccurate", reason=reason)
    store.upsert_fact_embedding(
        fact_id=fact_id,
        account_wxid="wxid_a",
        conversation_id=1,
        embedding_model="test-m",
        embedding_dim=4,
        vector=vector,
    )
    return fact_id


def _patch_settings(monkeypatch, indexer_mod):
    monkeypatch.setattr(
        indexer_mod,
        "load_rag_settings",
        lambda: {"rag_embedding_model": "test-m", "rag_embedding_dim": 4},
    )


def test_denied_guard_blocks_semantically_similar_extraction(monkeypatch):
    """换措辞的语义重复被拦在融合前（同文本复活由 UNIQUE+墓碑负责）。"""
    conn, store = _store()
    _deny_with_vector(store, "对方提到：对虾过敏", [1.0, 0.0, 0.0, 0.0])
    embed = _StubEmbed([[0.99, 0.02, 0.0, 0.0]])
    indexer, indexer_mod = _indexer_with(store, embed)
    _patch_settings(monkeypatch, indexer_mod)

    facts = [{"content": "对方提到：吃虾会过敏", "kind": "health"}]
    kept = indexer._filter_denied_facts(facts, account_wxid="wxid_a", conversation_id=1)

    assert kept == []
    assert embed.calls == 1


def test_denied_guard_passes_unrelated_extraction(monkeypatch):
    conn, store = _store()
    _deny_with_vector(store, "对方提到：对虾过敏", [1.0, 0.0, 0.0, 0.0])
    embed = _StubEmbed([[0.0, 1.0, 0.0, 0.0]])
    indexer, indexer_mod = _indexer_with(store, embed)
    _patch_settings(monkeypatch, indexer_mod)

    facts = [{"content": "对方提到：喜欢爬山", "kind": "hobby_or_game"}]
    kept = indexer._filter_denied_facts(facts, account_wxid="wxid_a", conversation_id=1)

    assert kept == facts


def test_denied_guard_inactive_without_denials(monkeypatch):
    """无否认事实时不触发嵌入（零成本快路径）。"""
    conn, store = _store()
    embed = _StubEmbed([[1.0, 0.0, 0.0, 0.0]])
    indexer, indexer_mod = _indexer_with(store, embed)
    _patch_settings(monkeypatch, indexer_mod)

    facts = [{"content": "对方提到：喜欢爬山"}]
    kept = indexer._filter_denied_facts(facts, account_wxid="wxid_a", conversation_id=1)

    assert kept == facts
    assert embed.calls == 0


def test_denied_guard_never_blocks_on_embedding_failure(monkeypatch):
    """嵌入不可用一律放行：守卫降级而非阻断抽取主链路。"""
    conn, store = _store()
    _deny_with_vector(store, "对方提到：对虾过敏", [1.0, 0.0, 0.0, 0.0])
    embed = _StubEmbed(RuntimeError("model not loaded"))
    indexer, indexer_mod = _indexer_with(store, embed)
    _patch_settings(monkeypatch, indexer_mod)

    facts = [{"content": "对方提到：吃虾会过敏"}]
    kept = indexer._filter_denied_facts(facts, account_wxid="wxid_a", conversation_id=1)

    assert kept == facts


def test_denied_guard_ignores_forget_action(monkeypatch):
    """「忘记」不参与语义拦截：它表达「不想留」而非「说法错了」，
    语义相似的新事实仍可入库（口径与 inaccurate 分离）。"""
    conn, store = _store()
    fact_id = _upsert_fact(store, content="对方提到：对虾过敏", evidence_message_ids=[])
    store.set_fact_user_feedback(fact_id, "forget")
    store.upsert_fact_embedding(
        fact_id=fact_id,
        account_wxid="wxid_a",
        conversation_id=1,
        embedding_model="test-m",
        embedding_dim=4,
        vector=[1.0, 0.0, 0.0, 0.0],
    )
    embed = _StubEmbed([[0.99, 0.02, 0.0, 0.0]])
    indexer, indexer_mod = _indexer_with(store, embed)
    _patch_settings(monkeypatch, indexer_mod)

    facts = [{"content": "对方提到：吃虾会过敏"}]
    kept = indexer._filter_denied_facts(facts, account_wxid="wxid_a", conversation_id=1)

    assert kept == facts
    assert embed.calls == 0


# ===== 两级漏斗第二级：融合 prompt 负样本注入（LLM 边界带判定） =====


def test_boundary_band_attaches_denied_refs_for_fusion(monkeypatch):
    """0.70~0.85 边界带不本地拦截：fact 幸存并附 _denied_refs（含用户
    纠错 reason），交给融合决策注入 prompt。"""
    conn, store = _store()
    denied_id = _deny_with_vector(
        store, "对方对虾过敏", [1.0, 0.0, 0.0, 0.0], reason="记错了，是蟹过敏"
    )
    # cosine ≈ 0.75，落在 [0.70, 0.85) 边界带
    embed = _StubEmbed([[0.75, 0.66, 0.0, 0.0]])
    indexer, indexer_mod = _indexer_with(store, embed)
    _patch_settings(monkeypatch, indexer_mod)

    facts = [{"content": "对方不能吃海鲜", "kind": "preference"}]
    kept = indexer._filter_denied_facts(facts, account_wxid="wxid_a", conversation_id=1)

    assert len(kept) == 1
    refs = kept[0]["_denied_refs"]
    assert refs[0]["fact_id"] == denied_id
    assert refs[0]["content"] == "对方对虾过敏"
    assert refs[0]["deny_reason"] == "记错了，是蟹过敏"


def test_denied_guard_high_similarity_with_reason_defers_to_fusion(monkeypatch):
    """带否认理由的否认不再硬拦高相似抽取：纠正句与新事实天然高相似
    （「记错了，是蟹过敏」→「对方对蟹过敏」），第一级无理由可辨方向，
    须附 refs 交第二级带理由判定（硬拦会让纠错永远写不进记忆库）。"""
    conn, store = _store()
    denied_id = _deny_with_vector(
        store, "对方对虾过敏", [1.0, 0.0, 0.0, 0.0], reason="记错了，是蟹过敏"
    )
    # cosine ≈ 0.999，远超 0.85 硬拦线
    embed = _StubEmbed([[0.999, 0.04, 0.0, 0.0]])
    indexer, indexer_mod = _indexer_with(store, embed)
    _patch_settings(monkeypatch, indexer_mod)

    facts = [{"content": "对方对蟹过敏", "kind": "health"}]
    kept = indexer._filter_denied_facts(facts, account_wxid="wxid_a", conversation_id=1)

    assert len(kept) == 1  # 不硬拦：幸存并附负样本交第二级
    refs = kept[0]["_denied_refs"]
    assert refs[0]["fact_id"] == denied_id
    assert refs[0]["deny_reason"] == "记错了，是蟹过敏"


def test_below_recall_band_keeps_fact_without_refs(monkeypatch):
    """低于 0.70 召回线的抽取与否认事实无关：原样放行不附加 refs。"""
    conn, store = _store()
    _deny_with_vector(store, "对方对虾过敏", [1.0, 0.0, 0.0, 0.0])
    # cosine = 0.5，低于召回线
    embed = _StubEmbed([[0.5, 0.866, 0.0, 0.0]])
    indexer, indexer_mod = _indexer_with(store, embed)
    _patch_settings(monkeypatch, indexer_mod)

    facts = [{"content": "对方喜欢爬山"}]
    kept = indexer._filter_denied_facts(facts, account_wxid="wxid_a", conversation_id=1)

    assert kept == facts
    assert "_denied_refs" not in kept[0]


class _StubFusionExtractor:
    """decide_fusion 桩：记录 prompt/入参，回放固定决策。"""

    def __init__(self, decisions):
        self._decisions = decisions
        self.prompts = []
        self.last_denied_ids = None
        self.last_strict_batch = None

    def decide_fusion(
        self, prompt, *, candidate_ids, denied_ids=frozenset(), strict_batch=True
    ):
        self.prompts.append(prompt)
        self.last_denied_ids = set(denied_ids)
        self.last_strict_batch = strict_batch
        return [dict(item) for item in self._decisions]


def _fusion_segment():
    from types import SimpleNamespace

    return SimpleNamespace(start_ts=100, end_ts=200)


def _fusion_fact(content="对方不能吃海鲜"):
    return {
        "subject": "contact",
        "kind": "preference",
        "content": content,
        "status": "active",
        "confidence": 0.8,
        "sensitivity": "normal",
        "evidence_message_ids": [9],
        "as_of": 150,
        "valid_from": 100,
        "valid_to": 200,
    }


def test_fusion_deny_decision_drops_new_fact():
    """融合决策输出 DENY：新事实不落库不嵌向量（换措辞不得复活否认说法）。"""
    conn, store = _store()
    seed_id = _upsert_fact(store, content="对方爱吃虾", kind="preference")  # active 候选
    embed = _StubEmbed([])
    indexer, _ = _indexer_with(store, embed)
    indexer.structured_fact_extractor = _StubFusionExtractor(
        [{"fact_id": seed_id + 100, "action": "DENY", "reason": "restates denied fact"}]
    )

    indexer._write_structured_facts(
        account_wxid="wxid_a",
        conversation_id=1,
        segment=_fusion_segment(),
        facts=[_fusion_fact()],
    )

    assert store.count_active_facts("wxid_a", 1) == 1  # 只剩种子事实


def test_fusion_without_deny_still_adds():
    """对照：无 DENY 决策时同一链路正常落库（丢弃确由 DENY 触发）。"""
    conn, store = _store()
    _upsert_fact(store, content="对方爱吃虾", kind="preference")
    indexer, _ = _indexer_with(store, _StubEmbed([]))
    indexer.structured_fact_extractor = _StubFusionExtractor([])

    indexer._write_structured_facts(
        account_wxid="wxid_a",
        conversation_id=1,
        segment=_fusion_segment(),
        facts=[_fusion_fact()],
    )

    assert store.count_active_facts("wxid_a", 1) == 2


def test_deny_refs_injected_into_fusion_prompt():
    """命中边界带的融合调用：prompt 带 denied_facts 块（含 user_reason），
    denied_ids 一并下发供校验；动作协议全在系统提示词，payload 不再有
    contract 键。纠错路径逐条跳过（strict_batch=False）保同批合法 DENY。"""
    conn, store = _store()
    _upsert_fact(store, content="对方爱吃虾", kind="preference")
    indexer, _ = _indexer_with(store, _StubEmbed([]))
    extractor = _StubFusionExtractor([])
    indexer.structured_fact_extractor = extractor
    candidates = store.list_active_facts_by_subject_kind("wxid_a", 1, "contact", "preference")
    denied_refs = [
        {"fact_id": 777, "content": "对方对虾过敏", "deny_reason": "记错了，是蟹过敏"}
    ]

    indexer._decide_fact_fusion(_fusion_fact(), candidates, denied_refs)

    assert len(extractor.prompts) == 1
    payload = json.loads(extractor.prompts[0])
    assert payload["denied_facts"][0]["user_reason"] == "记错了，是蟹过敏"
    assert "contract" not in payload  # 协议死重量已删：适配器不读它
    assert extractor.last_denied_ids == {777}
    assert extractor.last_strict_batch is False
    # 无负样本时不注入 denied_facts，且走整批作废的严格校验（防幻觉护栏）
    indexer._decide_fact_fusion(_fusion_fact(), candidates, [])
    payload_plain = json.loads(extractor.prompts[-1])
    assert "denied_facts" not in payload_plain
    assert extractor.last_denied_ids == set()
    assert extractor.last_strict_batch is True


def test_fusion_contract_deny_validation():
    """DENY 动作校验：只指向否认事实。纠错路径（strict_batch=False）对
    active 候选输出 DENY、对否认事实输出其他动作的单条剔除不废整批
    （同批合法 DENY 必须存活，否则换措辞的否认重述趁虚复活）。"""
    extractor = StructuredFactExtractor(
        lambda _prompt: {"decisions": [{"fact_id": 9, "action": "DENY"}]}
    )
    decisions = extractor.decide_fusion("{}", candidate_ids={1, 2}, denied_ids={9})
    assert decisions == [{"fact_id": 9, "action": "DENY", "reason": ""}]

    # DENY 指向 active 候选（混淆）与否认事实输出 UPDATE（非维护对象）：
    # 剔除这两条，同批合法 DENY/UPDATE 保留
    mixed = StructuredFactExtractor(
        lambda _prompt: {
            "decisions": [
                {"fact_id": 1, "action": "DENY", "reason": "混淆"},
                {"fact_id": 9, "action": "UPDATE", "reason": "混淆"},
                {"fact_id": 9, "action": "DENY", "reason": "重述"},
                {"fact_id": 2, "action": "UPDATE", "reason": "演进"},
                {"fact_id": 77, "action": "ADD", "reason": "未知候选"},
                {"action": "NOOP", "reason": "缺 fact_id"},
            ]
        }
    )
    decisions = mixed.decide_fusion(
        "{}", candidate_ids={1, 2}, denied_ids={9}, strict_batch=False
    )
    assert decisions == [
        {"fact_id": 9, "action": "DENY", "reason": "重述"},
        {"fact_id": 2, "action": "UPDATE", "reason": "演进"},
    ]


def test_fusion_strict_batch_invalidates_whole_batch():
    """普通融合路径（无 denied_refs）任一条目非法即废整批：id 脱靶/
    动作越界说明模型在瞎编，同批幸存的 UPDATE 同样不可信——调用方
    整批回退 ADD，不让幻觉 UPDATE 打错靶。"""
    import pytest

    from app.services.realtime.rag.fact_extractor import FactExtractionError

    for garbage in (
        [{"fact_id": 77, "action": "ADD", "reason": "id 脱靶"}],  # 未知候选
        [{"fact_id": 1, "action": "DENY", "reason": "无否认却 DENY"}],  # 越界动作
        [{"fact_id": 1, "action": "REPLACE", "reason": "动作不存在"}],
        [{"action": "NOOP", "reason": "缺 fact_id"}],
        [
            {"fact_id": 1, "action": "NOOP", "reason": "先到"},
            {"fact_id": 1, "action": "ADD", "reason": "重复 id"},
        ],
    ):
        extractor = StructuredFactExtractor(
            lambda _prompt, g=garbage: {"decisions": g}
        )
        with pytest.raises(FactExtractionError):
            extractor.decide_fusion("{}", candidate_ids={1, 2})
