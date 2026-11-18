"""P1.5 T2 事实融合协议接通测试：演变链 supersede / MERGE / 安全回退 ADD。

此前生产适配器把融合 payload 当抽取 payload 处理（要求 facts 协议），
decisions 永远解析失败 → 45 次日志回退 ADD，MERGE/UPDATE/INVALIDATE
从未执行。本组测试验证融合决策真正驱动维护循环。攒批版（2026-11）：
同桶新事实合一次调用，decisions 带 fact_index；批内互判 MERGE-only 去重。
"""

import json
import os
import sqlite3
import sys


sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.realtime.rag.fact_extractor import StructuredFactExtractor
from app.services.realtime.rag.indexer import RagIndexer
from app.services.realtime.rag.store import RagStore


class _NoopEmbedding:
    def embed_texts(self, texts):
        return [[0.0] * 768 for _ in texts]


def _segment(now, messages_spec, start_offset=600):
    from app.services.realtime.rag.segmenter import RagSegment

    messages = [
        {
            "id": mid,
            "is_sender": sender,
            "content": content,
            "timestamp": now - start_offset + idx * 60,
            "message_type": 1,
        }
        for idx, (mid, sender, content) in enumerate(messages_spec)
    ]
    return RagSegment(
        segment_id="s1",
        start_ts=messages[0]["timestamp"],
        end_ts=messages[-1]["timestamp"],
        messages=messages,
        message_ids=[m["id"] for m in messages],
        topics=[],
        entities=[],
        time_label="近期",
    )


def _indexer(store, llm):
    return RagIndexer(
        store=store,
        embedding_service=_NoopEmbedding(),
        structured_fact_extractor=StructuredFactExtractor(llm),
    )


def _seed_old_fact(store, *, content="对方不喜欢吃香菜", kind="preference", subject="对方"):
    return store.upsert_fact(
        account_wxid="wxid_a",
        conversation_id=1,
        subject=subject,
        kind=kind,
        content=content,
        confidence=0.7,
        as_of=1789900000,
        evidence_message_ids=[11],
        summary_method="llm_shadow",
    )


def _fusion_aware_llm(new_fact_content, decisions_for, intra_merge=()):
    """抽取返回 new_fact_content；融合按 decisions_for(fact_ids) 出决策。

    intra_merge: 批内互判对列表 [(i, j)]，表示 n_i 判与 n_j 重复（MERGE）。
    """

    def llm(prompt):
        payload = json.loads(prompt)
        if payload.get("task") == "maintain_atomic_contact_facts" or "new_facts" in payload:
            candidates = payload.get("active_candidates") or []
            new_facts = payload.get("new_facts") or []
            decisions = [
                {"fact_index": fi, "fact_id": item["fact_id"], **decisions_for(item)}
                for fi in range(len(new_facts))
                for item in candidates
            ]
            decisions.extend(
                {"fact_index": i, "fact_id": f"n{j}", "action": "MERGE", "reason": "批内重复"}
                for i, j in intra_merge
                if i < len(new_facts) and j < len(new_facts)
            )
            return {"decisions": decisions}
        return {
            "facts": [
                {
                    "subject": "对方",
                    "kind": "preference",
                    "content": new_fact_content,
                    "confidence": 0.85,
                    "sensitivity": "normal",
                    "evidence_message_ids": [1],
                }
            ]
        }

    return llm


def test_evolution_chain_supersedes_old_fact(monkeypatch):
    """验收场景："以前不喜欢X" → "现在因为Y改观了"：旧事实被 UPDATE 取代而非并存。"""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    store = RagStore(conn)
    old_id = _seed_old_fact(store)
    llm = _fusion_aware_llm(
        "对方以前不吃香菜，现在因为一起吃过几次改观了，开始喜欢吃了",
        lambda item: {"action": "UPDATE", "reason": "同一食物偏好的立场演变"},
    )
    indexer = _indexer(store, llm)
    monkeypatch.setattr(
        "app.services.realtime.rag.indexer.load_rag_settings",
        lambda: {"rag_fact_shadow_enabled": False},
    )

    now = 1790000000
    segment = _segment(
        now,
        [
            (1, 0, "其实香菜现在也还行，上次那个汤里的还挺好喝"),
            (2, 1, "咦你以前不是说不吃香菜吗"),
            (3, 0, "吃过几次觉得还行，改观了"),
            (4, 1, "哈哈那下次多点"),
        ],
    )
    indexer._extract_structured_shadow_facts(
        account_wxid="wxid_a", conversation_id=1, segment=segment
    )

    old = conn.execute("SELECT * FROM rag_facts WHERE id = ?", (old_id,)).fetchone()
    new = conn.execute(
        "SELECT * FROM rag_facts WHERE content LIKE '对方以前不吃香菜%'"
    ).fetchone()
    assert old["status"] == "superseded" and old["enabled"] == 0
    assert new is not None and new["status"] == "active"
    assert new["supersedes_fact_id"] == old_id
    # 同一 subject+kind 只剩一条 active（演变链，不是重复行）
    active = conn.execute(
        "SELECT COUNT(*) n FROM rag_facts WHERE subject='对方' AND kind='preference'"
        " AND status='active' AND enabled=1"
    ).fetchone()
    assert active["n"] == 1


def test_merge_decision_augments_old_fact_without_new_row(monkeypatch):
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    store = RagStore(conn)
    old_id = _seed_old_fact(store, content="对方对虾过敏", kind="preference")
    llm = _fusion_aware_llm(
        "对方对虾过敏，外出点菜必须避开虾",
        lambda item: {"action": "MERGE", "reason": "同一事实再次确认"},
    )
    indexer = _indexer(store, llm)
    monkeypatch.setattr(
        "app.services.realtime.rag.indexer.load_rag_settings",
        lambda: {"rag_fact_shadow_enabled": False},
    )

    now = 1790000000
    segment = _segment(
        now,
        [
            (1, 0, "点菜别点虾哈，我过敏"),
            (2, 1, "好，那换别的"),
            (3, 0, "嗯嗯每次都要注意"),
            (4, 1, "记住了"),
        ],
    )
    indexer._extract_structured_shadow_facts(
        account_wxid="wxid_a", conversation_id=1, segment=segment
    )

    rows = conn.execute(
        "SELECT * FROM rag_facts WHERE subject='对方' AND kind='preference'"
    ).fetchall()
    assert len(rows) == 1  # 不新增行
    assert rows[0]["id"] == old_id
    assert rows[0]["confidence"] > 0.7  # 重复确认抬分
    assert json.loads(rows[0]["evidence_message_ids_json"]) == [1, 11]  # 证据合并


def test_fusion_failure_falls_back_to_add_only(monkeypatch):
    """红线：融合判定异常只 ADD，不误推翻旧事实。"""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    store = RagStore(conn)
    old_id = _seed_old_fact(store, content="对方不喜欢吃香菜")

    def broken_fusion_llm(prompt):
        payload = json.loads(prompt)
        if payload.get("task") == "maintain_atomic_contact_facts" or "new_facts" in payload:
            raise ValueError("fusion endpoint down")
        return {
            "facts": [
                {
                    "subject": "对方",
                    "kind": "preference",
                    "content": "对方现在开始喜欢吃苦瓜了",
                    "confidence": 0.8,
                    "evidence_message_ids": [1],
                }
            ]
        }

    indexer = _indexer(store, broken_fusion_llm)
    monkeypatch.setattr(
        "app.services.realtime.rag.indexer.load_rag_settings",
        lambda: {"rag_fact_shadow_enabled": False},
    )
    now = 1790000000
    segment = _segment(
        now,
        [(1, 0, "苦瓜现在觉得还挺好吃的"), (2, 1, "咦"), (3, 0, "改观了"), (4, 1, "不错")],
    )
    indexer._extract_structured_shadow_facts(
        account_wxid="wxid_a", conversation_id=1, segment=segment
    )

    old = conn.execute("SELECT * FROM rag_facts WHERE id = ?", (old_id,)).fetchone()
    assert old["status"] == "active" and old["enabled"] == 1  # 未被推翻
    new = conn.execute(
        "SELECT * FROM rag_facts WHERE content LIKE '对方现在开始喜欢吃苦瓜%'"
    ).fetchone()
    assert new is not None and new["status"] == "active"  # 新事实照常 ADD


def test_superseded_fact_not_resurrected_by_rescan():
    """T8：被 UPDATE 退役的旧事实不得被同内容重扫 upsert 复活。

    真实库证据：融合决策日志 UPDATE 执行 8 次，库里 superseded 却为 0——
    语义路径每轮重建把退役行改回 active，演变链被静默抹掉。
    """
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    store = RagStore(conn)
    old_id = _seed_old_fact(store, content="对方不喜欢吃香菜")
    new_id = store.upsert_fact(
        account_wxid="wxid_a", conversation_id=1, subject="对方", kind="preference",
        content="对方以前不吃香菜，现在改观了开始喜欢", confidence=0.85,
        evidence_message_ids=[1], summary_method="llm_shadow",
    )
    store.supersede_fact(old_id, new_id)
    conn.commit()

    # 语义路径重扫同 content upsert（status=active、enabled=1）
    store.upsert_fact(
        account_wxid="wxid_a", conversation_id=1, subject="对方", kind="preference",
        content="对方不喜欢吃香菜", confidence=0.6,
        evidence_message_ids=[11], summary_method="shadow_semantic_embedding",
    )
    conn.commit()
    row = conn.execute("SELECT * FROM rag_facts WHERE id = ?", (old_id,)).fetchone()
    assert row["status"] == "superseded" and row["enabled"] == 0  # 不复活
    assert row["supersedes_fact_id"] is None  # 退役行的链不被覆盖

    # 演变链新行被重扫时 supersedes_fact_id 不被清空
    store.upsert_fact(
        account_wxid="wxid_a", conversation_id=1, subject="对方", kind="preference",
        content="对方以前不吃香菜，现在改观了开始喜欢", confidence=0.85,
        evidence_message_ids=[1], summary_method="llm_shadow",
    )
    conn.commit()
    new_row = conn.execute("SELECT * FROM rag_facts WHERE id = ?", (new_id,)).fetchone()
    assert new_row["status"] == "active"
    assert new_row["supersedes_fact_id"] == old_id  # COALESCE 保留链

    # 质量隔离行同样不被复活
    qid = store.upsert_fact(
        account_wxid="wxid_a", conversation_id=1, subject="对方", kind="event",
        content="对方提到：嗯嗯就这样吧", confidence=0.5,
        summary_method="shadow_semantic_embedding",
    )
    conn.execute(
        "UPDATE rag_facts SET status='uncertain', enabled=0 WHERE id=?", (qid,)
    )
    store.upsert_fact(
        account_wxid="wxid_a", conversation_id=1, subject="对方", kind="event",
        content="对方提到：嗯嗯就这样吧", confidence=0.5,
        summary_method="shadow_semantic_embedding",
    )
    conn.commit()
    qrow = conn.execute("SELECT status, enabled FROM rag_facts WHERE id=?", (qid,)).fetchone()
    assert qrow["status"] == "uncertain" and qrow["enabled"] == 0


def test_fusion_candidates_capped_by_confidence(monkeypatch):
    """T10：融合候选按置信度截断，防止 decisions 响应过长被截断。"""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    store = RagStore(conn)
    for i in range(15):
        _seed_old_fact(store, content=f"对方的事实编号{i}", kind="preference")

    seen = {}

    def llm(prompt):
        payload = json.loads(prompt)
        if payload.get("task") == "maintain_atomic_contact_facts" or "new_facts" in payload:
            seen["candidates"] = payload.get("active_candidates") or []
            new_facts = payload.get("new_facts") or []
            return {
                "decisions": [
                    {"fact_index": fi, "fact_id": item["fact_id"], "action": "ADD", "reason": "-"}
                    for fi in range(len(new_facts))
                    for item in seen["candidates"]
                ]
            }
        return {
            "facts": [
                {
                    "subject": "对方",
                    "kind": "preference",
                    "content": "对方喜欢徒步",
                    "confidence": 0.8,
                    "evidence_message_ids": [1],
                }
            ]
        }

    indexer = _indexer(store, llm)
    monkeypatch.setattr(
        "app.services.realtime.rag.indexer.load_rag_settings",
        lambda: {"rag_fact_shadow_enabled": False},
    )
    now = 1790000000
    segment = _segment(
        now, [(1, 0, "我喜欢徒步"), (2, 1, "哦"), (3, 0, "周末常去"), (4, 1, "好的")]
    )
    indexer._extract_structured_shadow_facts(
        account_wxid="wxid_a", conversation_id=1, segment=segment
    )
    assert len(seen["candidates"]) == indexer.FACT_FUSION_CANDIDATE_LIMIT


def _multi_fact_llm(facts_out, decisions_for, intra_merge=(), fail_first_batch=False):
    """抽取一次返回多条事实；融合按 fact_index 分组出决策（批协议桩）。"""
    state = {"fusion_calls": 0, "batch_sizes": []}

    def llm(prompt):
        payload = json.loads(prompt)
        if payload.get("task") == "maintain_atomic_contact_facts" or "new_facts" in payload:
            state["fusion_calls"] += 1
            new_facts = payload.get("new_facts") or []
            state["batch_sizes"].append(len(new_facts))
            if fail_first_batch and state["fusion_calls"] == 1:
                raise ValueError("batch endpoint down")
            candidates = payload.get("active_candidates") or []
            decisions = [
                {"fact_index": fi, "fact_id": item["fact_id"], **decisions_for(item, fi)}
                for fi in range(len(new_facts))
                for item in candidates
            ]
            decisions.extend(
                {"fact_index": i, "fact_id": f"n{j}", "action": "MERGE", "reason": "批内重复"}
                for i, j in intra_merge
                if i < len(new_facts) and j < len(new_facts)
            )
            return {"decisions": decisions}
        return {"facts": facts_out}

    llm.state = state
    return llm


def test_intra_batch_merge_dedupes_same_segment_facts(monkeypatch):
    """攒批互判：同段同桶两条换措辞重复 → 只落一条，证据并集置信取 max。"""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    store = RagStore(conn)
    _seed_old_fact(store, content="对方不喜欢吃香菜")  # 无关候选，保融合调用发生
    llm = _multi_fact_llm(
        [
            {"subject": "对方", "kind": "preference", "content": "对方喜欢玩怪物猎人",
             "confidence": 0.8, "evidence_message_ids": [1]},
            {"subject": "对方", "kind": "preference", "content": "对方是怪物猎人系列玩家",
             "confidence": 0.9, "evidence_message_ids": [2]},
        ],
        lambda item, fi: {"action": "ADD", "reason": "-"},
        intra_merge=[(0, 1)],
    )
    indexer = _indexer(store, llm)
    monkeypatch.setattr(
        "app.services.realtime.rag.indexer.load_rag_settings",
        lambda: {"rag_fact_shadow_enabled": False},
    )
    now = 1790000000
    segment = _segment(
        now, [(1, 0, "我一直在玩怪猎"), (2, 0, "出了新作必买"), (3, 1, "老玩家了"), (4, 1, "哈哈")]
    )
    indexer._extract_structured_shadow_facts(
        account_wxid="wxid_a", conversation_id=1, segment=segment
    )

    assert llm.state["fusion_calls"] == 1  # 同桶两条一次调用
    rows = conn.execute(
        "SELECT * FROM rag_facts WHERE status='active' AND content IN"
        " ('对方喜欢玩怪物猎人', '对方是怪物猎人系列玩家')"
    ).fetchall()
    assert len(rows) == 1  # 批内去重只落代表
    rep = rows[0]
    assert rep["content"] == "对方喜欢玩怪物猎人"  # 代表 = 先出现（index 小）
    assert json.loads(rep["evidence_message_ids_json"]) == [1, 2]  # 被吸收者证据并入
    assert rep["confidence"] == 0.9  # 置信取 max


def test_denied_marked_fact_dropped_on_deny(monkeypatch):
    """带 denied 边界带负样本的事实拆单条批后，判 DENY 重述 → 丢弃不落库。
    （拆批后 DENY 只出现在单条批，原「组内任一 DENY 整组丢」自然退化
    为自身丢弃——与旧单事实协议行为一致。）
    """
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    store = RagStore(conn)
    denied_id = store.upsert_fact(
        account_wxid="wxid_a", conversation_id=1, subject="对方", kind="preference",
        content="对方不能吃海鲜", confidence=0.7, evidence_message_ids=[9],
        summary_method="llm_shadow",
    )
    conn.execute("UPDATE rag_facts SET status='inaccurate', enabled=0 WHERE id=?", (denied_id,))
    conn.commit()

    def llm(prompt):
        payload = json.loads(prompt)
        if payload.get("task") == "maintain_atomic_contact_facts" or "new_facts" in payload:
            return {
                "decisions": [
                    {"fact_index": 0, "fact_id": denied_id, "action": "DENY", "reason": "重述"},
                ]
            }
        raise AssertionError("extraction not expected in this test")

    indexer = _indexer(store, llm)
    monkeypatch.setattr(
        indexer, "_filter_denied_facts", lambda facts, **kw: facts
    )
    now = 1790000000
    segment = _segment(now, [(1, 0, "别点海鲜我过敏"), (2, 1, "好")])
    indexer._write_structured_facts(
        account_wxid="wxid_a",
        conversation_id=1,
        segment=segment,
        facts=[
            {"subject": "对方", "kind": "preference", "content": "对方吃海鲜会过敏",
             "confidence": 0.8, "evidence_message_ids": [1],
             "_denied_refs": [{"fact_id": denied_id, "content": "对方不能吃海鲜", "deny_reason": ""}]},
        ],
    )
    n = conn.execute(
        "SELECT COUNT(*) n FROM rag_facts WHERE status='active' AND enabled=1"
    ).fetchone()
    assert n["n"] == 0  # DENY 重述丢弃，无新落库


def test_batch_capped_at_fusion_batch_facts(monkeypatch):
    """批上限：FUSION_BATCH_FACTS=3；同桶 7 条事实切成 3+3+1 三批。"""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    store = RagStore(conn)
    for i in range(12):
        _seed_old_fact(store, content=f"对方的既有事实{i}")
    facts_out = [
        {"subject": "对方", "kind": "preference", "content": f"对方的新事实编号{i}",
         "confidence": 0.8, "evidence_message_ids": [i]}
        for i in range(7)
    ]
    llm = _multi_fact_llm(facts_out, lambda item, fi: {"action": "ADD", "reason": "-"})
    indexer = _indexer(store, llm)
    monkeypatch.setattr(
        "app.services.realtime.rag.indexer.load_rag_settings",
        lambda: {"rag_fact_shadow_enabled": False},
    )
    now = 1790000000
    segment = _segment(now, [(1, 0, f"事实{i}") for i in range(7)] + [(8, 1, "好的")])
    indexer._extract_structured_shadow_facts(
        account_wxid="wxid_a", conversation_id=1, segment=segment
    )
    assert llm.state["batch_sizes"] == [3, 3, 1]
    n = conn.execute(
        "SELECT COUNT(*) n FROM rag_facts WHERE content LIKE '对方的新事实%'"
    ).fetchone()
    assert n["n"] == 7  # 全部落库（对候选全 ADD）


def test_batch_failure_degrades_to_per_fact_retry(monkeypatch):
    """降级梯：整批调用失败 → 拆逐条重试（k=1 也是批形状）→ 全部落库。"""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    store = RagStore(conn)
    _seed_old_fact(store, content="对方不喜欢吃香菜")  # 无关候选，保融合调用发生
    llm = _multi_fact_llm(
        [
            {"subject": "对方", "kind": "preference", "content": "对方喜欢爬山",
             "confidence": 0.8, "evidence_message_ids": [1]},
            {"subject": "对方", "kind": "preference", "content": "对方常去城郊徒步",
             "confidence": 0.7, "evidence_message_ids": [2]},
        ],
        lambda item, fi: {"action": "ADD", "reason": "-"},
        fail_first_batch=True,
    )
    indexer = _indexer(store, llm)
    monkeypatch.setattr(
        "app.services.realtime.rag.indexer.load_rag_settings",
        lambda: {"rag_fact_shadow_enabled": False},
    )
    now = 1790000000
    segment = _segment(now, [(1, 0, "周末爬山去"), (2, 0, "城郊走起"), (3, 1, "好"), (4, 1, "嗯")])
    indexer._extract_structured_shadow_facts(
        account_wxid="wxid_a", conversation_id=1, segment=segment
    )
    # 第一次批调用失败 + 两次逐条重试
    assert llm.state["fusion_calls"] == 3
    assert llm.state["batch_sizes"] == [2, 1, 1]
    n = conn.execute(
        "SELECT COUNT(*) n FROM rag_facts WHERE status='active' AND content IN"
        " ('对方喜欢爬山', '对方常去城郊徒步')"
    ).fetchone()
    assert n["n"] == 2  # 逐条重试成功，两条都落库


def test_decide_fusion_batch_validates_intra_refs():
    """校验层：fact_index 越界/批内 UPDATE/自引用均废批；合法批内 MERGE 放行。"""
    from app.services.realtime.rag.fact_extractor import FactExtractionError
    import pytest

    extractor = StructuredFactExtractor(lambda prompt: prompt)

    def _run(decisions, fact_count=2, candidates={1}, strict=True):
        return extractor.decide_fusion(
            json.dumps({"decisions": decisions}),
            fact_count=fact_count,
            candidate_ids=candidates,
            strict_batch=strict,
        )

    # 合法：候选决策 + 批内 MERGE
    grouped = _run([
        {"fact_index": 0, "fact_id": 1, "action": "UPDATE", "reason": "-"},
        {"fact_index": 0, "fact_id": "n1", "action": "MERGE", "reason": "重复"},
    ])
    assert grouped[0][0]["action"] == "UPDATE"
    assert grouped[0][1]["fact_id"] == "n1"  # 批内引用原样透传给落地侧
    assert grouped[1] == []

    # 批内引用只允许 MERGE/NOOP
    with pytest.raises(FactExtractionError):
        _run([{"fact_index": 0, "fact_id": "n1", "action": "UPDATE", "reason": "-"}])
    # 自引用与越界
    with pytest.raises(FactExtractionError):
        _run([{"fact_index": 0, "fact_id": "n0", "action": "MERGE", "reason": "-"}])
    with pytest.raises(FactExtractionError):
        _run([{"fact_index": 2, "fact_id": 1, "action": "ADD", "reason": "-"}], fact_count=2)
    # 非 strict：非法条目跳过、合法条目幸存（纠错路径语义）
    grouped = _run(
        [{"fact_index": 0, "fact_id": "n1", "action": "UPDATE", "reason": "-"},
         {"fact_index": 1, "fact_id": 1, "action": "ADD", "reason": "-"}],
        strict=False,
    )
    assert grouped == [[], [{"fact_id": 1, "action": "ADD", "reason": "-"}]]


def test_absorbed_member_decisions_inherited_by_representative(monkeypatch):
    """回归（审计）：互判方向任选时全部决策可能挂被吸收者名下——
    其数字目标决策必须并入代表执行，否则 UPDATE 落空新旧并存。"""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    store = RagStore(conn)
    old_id = _seed_old_fact(store, content="对方不喜欢吃香菜")

    state = {"calls": 0}

    def llm(prompt):
        payload = json.loads(prompt)
        if payload.get("task") == "maintain_atomic_contact_facts" or "new_facts" in payload:
            state["calls"] += 1
            # 全部决策挂在 f1 名下：互判 MERGE（f1 与 n0 重复）+ UPDATE 旧事实
            return {
                "decisions": [
                    {"fact_index": 1, "fact_id": "n0", "action": "MERGE", "reason": "批内重复"},
                    {"fact_index": 1, "fact_id": old_id, "action": "UPDATE", "reason": "立场演变"},
                ]
            }
        return {
            "facts": [
                {"subject": "对方", "kind": "preference", "content": "对方喜欢玩怪物猎人",
                 "confidence": 0.8, "evidence_message_ids": [1]},
                {"subject": "对方", "kind": "preference", "content": "对方是怪物猎人系列玩家",
                 "confidence": 0.9, "evidence_message_ids": [2]},
            ]
        }

    indexer = _indexer(store, llm)
    monkeypatch.setattr(
        "app.services.realtime.rag.indexer.load_rag_settings",
        lambda: {"rag_fact_shadow_enabled": False},
    )
    now = 1790000000
    segment = _segment(now, [(1, 0, "我一直在玩怪猎"), (2, 0, "老玩家了"), (3, 1, "好"), (4, 1, "嗯")])
    indexer._extract_structured_shadow_facts(
        account_wxid="wxid_a", conversation_id=1, segment=segment
    )

    old = conn.execute("SELECT * FROM rag_facts WHERE id = ?", (old_id,)).fetchone()
    assert old["status"] == "superseded" and old["enabled"] == 0  # UPDATE 经代表执行
    new_rows = conn.execute(
        "SELECT * FROM rag_facts WHERE status='active' AND content IN"
        " ('对方喜欢玩怪物猎人', '对方是怪物猎人系列玩家')"
    ).fetchall()
    assert len(new_rows) == 1  # 批内去重只落代表
    assert new_rows[0]["supersedes_fact_id"] == old_id


def test_denied_refs_facts_split_out_of_batches(monkeypatch):
    """回归（审计）：带 denied 边界带负样本的事实单独成批——独享
    DENIED_FACT_PROMPT_LIMIT 预算与逐条跳过语义，不混进攒批被并集截断。"""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    store = RagStore(conn)
    _seed_old_fact(store, content="对方不喜欢吃香菜")

    def llm(prompt):
        payload = json.loads(prompt)
        if payload.get("task") == "maintain_atomic_contact_facts" or "new_facts" in payload:
            return {"decisions": []}
        return {
            "facts": [
                {"subject": "对方", "kind": "preference", "content": "对方吃海鲜会过敏",
                 "confidence": 0.8, "evidence_message_ids": [1]},
                {"subject": "对方", "kind": "preference", "content": "对方喜欢爬山",
                 "confidence": 0.7, "evidence_message_ids": [2]},
                {"subject": "对方", "kind": "preference", "content": "对方常去城郊徒步",
                 "confidence": 0.6, "evidence_message_ids": [3]},
            ]
        }

    llm.state = {"batch_sizes": [], "denied_seen": []}
    orig_llm = llm

    def tracking_llm(prompt):
        payload = json.loads(prompt)
        if payload.get("task") == "maintain_atomic_contact_facts" or "new_facts" in payload:
            llm.state["batch_sizes"].append(len(payload.get("new_facts") or []))
            llm.state["denied_seen"].append(bool(payload.get("denied_facts")))
            return {"decisions": []}
        return orig_llm(payload)

    indexer = _indexer(store, tracking_llm)
    monkeypatch.setattr(indexer, "_filter_denied_facts", lambda facts, **kw: facts)
    now = 1790000000
    segment = _segment(now, [(1, 0, "海鲜过敏"), (2, 0, "爬山"), (3, 0, "徒步"), (4, 1, "好")])
    indexer._write_structured_facts(
        account_wxid="wxid_a",
        conversation_id=1,
        segment=segment,
        facts=[
            {"subject": "对方", "kind": "preference", "content": "对方吃海鲜会过敏",
             "confidence": 0.8, "evidence_message_ids": [1],
             "_denied_refs": [{"fact_id": 777, "content": "对方不能吃海鲜", "deny_reason": ""}]},
            {"subject": "对方", "kind": "preference", "content": "对方喜欢爬山",
             "confidence": 0.7, "evidence_message_ids": [2]},
            {"subject": "对方", "kind": "preference", "content": "对方常去城郊徒步",
             "confidence": 0.6, "evidence_message_ids": [3]},
        ],
    )
    # 带 refs 的事实单条批（且载荷带 denied_facts）；干净事实攒成一批
    assert llm.state["batch_sizes"] == [1, 2]
    assert llm.state["denied_seen"] == [True, False]


def test_decide_fusion_rejects_non_int_fact_index():
    """回归（审计）：fact_index 宽松 int() 会把 1.0/true 静默取整错挂——严格拒。"""
    from app.services.realtime.rag.fact_extractor import FactExtractionError
    import pytest

    extractor = StructuredFactExtractor(lambda prompt: prompt)
    for bad in (1.0, True, "0"):
        with pytest.raises(FactExtractionError):
            extractor.decide_fusion(
                json.dumps({"decisions": [{"fact_index": bad, "fact_id": 1, "action": "ADD"}]}),
                fact_count=2,
                candidate_ids={1},
            )
