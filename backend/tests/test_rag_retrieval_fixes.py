"""RAG 检索修复的专项测试：单字回退字符命中、脏证据 ID、list_facts 去重、均值向量空向量守卫。"""

import os
import sqlite3
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import app.services.realtime.rag.retriever as retriever_mod
from app.services.realtime.rag.retriever import RagRetriever
from app.services.realtime.rag.semantic_memory import SemanticFactExtractor
from app.services.realtime.rag.store import RagStore


@pytest.fixture
def rag_settings(monkeypatch):
    monkeypatch.setattr(
        retriever_mod,
        "load_rag_settings",
        lambda: {
            "rag_fact_read_enabled": True,
            "rag_embedding_model": "test",
            "rag_embedding_dim": 2,
        },
    )


def _make_store(*evidence_rows):
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE messages (id INTEGER PRIMARY KEY, content TEXT)")
    for mid, text in evidence_rows:
        conn.execute("INSERT INTO messages(id, content) VALUES (?, ?)", (mid, text))
    return RagStore(conn)


def test_short_query_char_fallback_recovers_paraphrase(rag_settings):
    """查询「玩过吗」与事实「天天玩」无 token 交集：短查询单字命中应可召回。"""
    store = _make_store()
    fact_id = store.upsert_fact(
        account_wxid="acc", conversation_id=1, subject="对方",
        kind="hobby_or_game", content="对方天天玩", confidence=0.8,
    )
    result = RagRetriever(store=store).retrieve(
        account_wxid="acc", conversation_id=1, query="玩过吗", limit=5,
    )
    ids = [item["document_id"] for item in result["items"]]
    assert fact_id in ids


def test_long_query_single_common_char_not_recalled(rag_settings):
    """长查询只撞一个常用字（我）不足以证明相关，不得召回无关事实。"""
    store = _make_store()
    store.upsert_fact(
        account_wxid="acc", conversation_id=1, subject="对方",
        kind="purchase_or_price", content="对方说后天到", confidence=0.9,
    )
    result = RagRetriever(store=store).retrieve(
        account_wxid="acc", conversation_id=1,
        query="我们一起玩过什么游戏", limit=5,
    )
    assert result["items"] == []


def test_char_fallback_ranks_below_token_match(rag_settings):
    """同为可召回时，token 级命中的事实应排在单字回退命中之前。"""
    store = _make_store()
    token_fact = store.upsert_fact(
        account_wxid="acc", conversation_id=1, subject="对方",
        kind="hobby_or_game", content="对方喜欢爬山", confidence=0.8,
    )
    # 与查询共享「山/玩」两个非相邻字（无 token 交集），走单字回退通道
    char_fact = store.upsert_fact(
        account_wxid="acc", conversation_id=1, subject="对方",
        kind="hobby_or_game", content="对方常去山里玩", confidence=0.8,
    )
    result = RagRetriever(store=store).retrieve(
        account_wxid="acc", conversation_id=1,
        query="喜欢爬山吗，还是玩", limit=5,
    )
    ids = [item["document_id"] for item in result["items"]]
    assert set(ids) == {token_fact, char_fact}
    assert ids.index(token_fact) < ids.index(char_fact)


def test_dirty_evidence_ids_do_not_crash(rag_settings, monkeypatch):
    """evidence_message_ids 混入非整数（浮点/字符串）：跳过脏 ID，检索不炸。"""
    store = _make_store((7, "正常证据文本"))
    fact_id = store.upsert_fact(
        account_wxid="acc", conversation_id=1, subject="对方",
        kind="hobby_or_game", content="对方喜欢爬山", confidence=0.8,
        evidence_message_ids=[7],
    )
    # 直接写入脏 JSON 模拟历史数据
    conn = store.conn
    conn.execute(
        "UPDATE rag_facts SET evidence_message_ids_json = ? WHERE id = ?",
        ('[7, "8.5", "abc", null]', fact_id),
    )
    result = RagRetriever(store=store).retrieve(
        account_wxid="acc", conversation_id=1, query="爬山", limit=5,
    )
    assert [item["document_id"] for item in result["items"]] == [fact_id]


def test_list_facts_fetched_once_per_retrieval(rag_settings, monkeypatch):
    """评分循环与证据预取共用一次 list_facts，不再全表扫两遍。"""
    store = _make_store((7, "证据"))
    store.upsert_fact(
        account_wxid="acc", conversation_id=1, subject="对方",
        kind="hobby_or_game", content="对方喜欢爬山", confidence=0.8,
        evidence_message_ids=[7],
    )
    retriever = RagRetriever(store=store)
    calls = {"n": 0}
    real_list_facts = store.list_facts

    def counting(*args, **kw):
        calls["n"] += 1
        return real_list_facts(*args, **kw)

    monkeypatch.setattr(store, "list_facts", counting)
    retriever.retrieve(account_wxid="acc", conversation_id=1, query="爬山", limit=5)
    assert calls["n"] == 1


def test_mean_vector_tolerates_empty_members():
    """簇内混入空向量：不炸（IndexError/ValueError），按非空成员求均值。"""
    service = SemanticFactExtractor(embedding_service=None)
    assert service._mean_vector([]) == []
    assert service._mean_vector([[], []]) == []
    mean = service._mean_vector([[1.0, 2.0, 3.0], [], [3.0, 4.0, 5.0]])
    assert mean == [2.0, 3.0, 4.0]
