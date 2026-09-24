"""P1.5 T2 事实融合协议接通测试：演变链 supersede / MERGE / 安全回退 ADD。

此前生产适配器把融合 payload 当抽取 payload 处理（要求 facts 协议），
decisions 永远解析失败 → 45 次日志回退 ADD，MERGE/UPDATE/INVALIDATE
从未执行。本组测试验证融合决策真正驱动维护循环。
"""

import json
import os
import sqlite3
import sys


sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.realtime.rag_fact_extractor import StructuredFactExtractor
from app.services.realtime.rag_indexer import RagIndexer
from app.services.realtime.rag_store import RagStore


class _NoopEmbedding:
    def embed_texts(self, texts):
        return [[0.0] * 768 for _ in texts]


def _segment(now, messages_spec, start_offset=600):
    from app.services.realtime.rag_segmenter import RagSegment

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


def _fusion_aware_llm(new_fact_content, decisions_for):
    """抽取返回 new_fact_content；融合按 decisions_for(fact_ids) 出决策。"""

    def llm(prompt):
        payload = json.loads(prompt)
        if payload.get("task") == "maintain_atomic_contact_facts" or "new_fact" in payload:
            candidates = payload.get("active_candidates") or []
            return {
                "decisions": [
                    {"fact_id": item["fact_id"], **decisions_for(item)}
                    for item in candidates
                ]
            }
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
        "app.services.realtime.rag_indexer.load_rag_settings",
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
        "app.services.realtime.rag_indexer.load_rag_settings",
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
        if payload.get("task") == "maintain_atomic_contact_facts" or "new_fact" in payload:
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
        "app.services.realtime.rag_indexer.load_rag_settings",
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
