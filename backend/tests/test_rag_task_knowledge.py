"""G5 按任务选择知识测试:邀约重排加权、偏好槽排序。"""

import os
import sqlite3
import sys


sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.realtime.memory_intent import MemoryIntent
from app.services.realtime.rag.context_builder import RagContextBuilder
from app.services.realtime.rag.store import RagStore


def _builder():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    return RagContextBuilder(store=RagStore(conn))


def _fact_item(fact_id: int, content: str, memory_kind: str, score: float = 0.5):
    return {
        "document_id": fact_id,
        "doc": {"id": fact_id, "doc_type": "fact_memory", "content": content},
        "score": score,
        "vector_score": score - 0.1,
        "keyword_score": 0.0,
        "memory_kind": memory_kind,
    }


def test_invitation_rerank_boosts_game_and_shared_facts():
    builder = _builder()
    context = {
        "_task_routing": {
            "task": "invitation_planning",
            "output": "answer_with_speeches",
            "knowledge_needs": ["facts", "contact_profile", "user_style", "relationship_signals"],
        }
    }
    items = [
        _fact_item(1, "对方手机贴膜喜欢去小店", "preference", score=0.60),
        _fact_item(2, "我们一起玩过主机游戏,配合默契", "hobby_or_game", score=0.45),
    ]
    reranked = builder._rerank_candidates_for_task(
        items,
        query="我想约她打游戏",
        context=context,
        memory_intent=MemoryIntent.none(),
        injection_mode="suggestion",
    )
    assert reranked[0]["document_id"] == 2
    assert reranked[0]["rerank_reason"] == "invitation_kind_boost"
    assert reranked[1]["document_id"] == 1


def test_general_qa_dampens_style_samples():
    builder = _builder()
    context = {
        "_task_routing": {
            "task": "general_qa",
            "output": "direct_answer",
            "knowledge_needs": ["facts"],
        }
    }
    items = [
        {
            "document_id": 9,
            "doc": {"id": 9, "doc_type": "self_style_example", "content": "用户常用语气词 hhh"},
            "score": 0.5,
            "vector_score": 0.4,
            "keyword_score": 0.3,
        },
    ]
    reranked = builder._rerank_candidates_for_task(
        items,
        query="你好",
        context=context,
        memory_intent=MemoryIntent.none(),
        injection_mode="reply",
    )
    assert reranked[0]["rerank_reason"] == "style_context_general_qa_dampened"
    assert reranked[0]["task_relevance_score"] < 0.35


def test_invitation_preferences_put_game_slots_first(monkeypatch):
    builder = _builder()
    monkeypatch.setattr(
        "app.services.realtime.rag.context_builder.load_rag_settings",
        lambda: {
            "rag_relationship_policy_injection_enabled": True,
            "rag_relationship_policy_shadow_enabled": True,
        },
    )
    monkeypatch.setattr(
        builder.store,
        "list_contact_preferences",
        lambda account_wxid, conversation_id: [
            {"id": 1, "slot_kind": "preference", "summary": "喜欢手机贴膜", "confidence": 0.8, "support_count": 2, "sensitivity": "normal", "policy_version": "v1"},
            {"id": 2, "slot_kind": "preference", "summary": "喜欢联机开黑打游戏", "confidence": 0.7, "support_count": 3, "sensitivity": "normal", "policy_version": "v1"},
            {"id": 3, "slot_kind": "preference", "summary": "穿衣风格偏简约", "confidence": 0.9, "support_count": 4, "sensitivity": "normal", "policy_version": "v1"},
        ],
    )
    context = {
        "_task_routing": {
            "task": "invitation_planning",
            "output": "answer_with_speeches",
            "knowledge_needs": ["facts", "contact_profile", "user_style", "relationship_signals"],
        }
    }
    ids = builder._inject_contact_preferences(
        context,
        account_wxid="wxid_a",
        conversation_id=1,
        remote_model=False,
        redaction_disabled=False,
    )
    # 返工 2:先排序后截断——游戏类第一,其余按置信度降序
    assert ids == [2, 3, 1]
    assert context["contact_preferences"][0]["summary"].startswith("喜欢联机开黑")
