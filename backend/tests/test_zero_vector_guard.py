"""零向量防护回归:ONNX 故障窗口期写入的零向量曾使检索静默失效。"""

import os
import pickle
import sqlite3
import sys
from types import SimpleNamespace


sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.realtime.rag.embedding import (
    RagEmbeddingService,
    RagEmbeddingUnavailable,
)
from app.services.realtime.rag.indexer import RagIndexer
from app.services.realtime.rag.store import RagStore


def _store():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    return RagStore(conn)


def test_embedding_service_rejects_zero_vectors():
    """源头守卫:模型输出零向量按不可用处理,不进入落库链路。"""
    import pytest

    def _service(embedding):
        return RagEmbeddingService(
            sentiment_service=SimpleNamespace(
                analyze_batch=lambda texts, include_embeddings=False: [{"embedding": embedding} for _ in texts],
                has_local_embedding_model=lambda: True,
            )
        )

    with pytest.raises(RagEmbeddingUnavailable):
        _service([0.0, 0.0, 0.0]).embed_texts(["任意文本"])
    with pytest.raises(RagEmbeddingUnavailable):
        _service([]).embed_texts(["任意文本"])
    assert _service([0.1, 0.2, 0.3]).embed_texts(["任意文本"]) == [[0.1, 0.2, 0.3]]


class _FakeEmbedding:
    def __init__(self):
        self.calls = 0

    def embed_texts(self, texts):
        self.calls += 1
        return [[0.1, 0.2, 0.3] for _ in texts]


def test_backfill_rewrites_zero_norm_vectors(monkeypatch):
    """零范数向量视为缺失:回填必须重写而不是跳过。"""
    store = _store()
    store.upsert_fact(
        account_wxid="a", conversation_id=1, subject="共同",
        kind="hobby_or_game", content="我们一起玩过杀戮尖塔",
    )
    # 直接落一条零向量(绕过守卫模拟历史脏数据)
    store.conn.execute(
        "INSERT INTO rag_fact_embeddings (fact_id, account_wxid, conversation_id, "
        "embedding_model, embedding_dim, embedding_provider, vector_blob, created_at) "
        "SELECT id, 'a', 1, 'm', 3, 'local', ?, 0 FROM rag_facts LIMIT 1",
        (pickle.dumps([0.0, 0.0, 0.0]),),
    )
    store.conn.commit()

    monkeypatch.setattr(
        "app.services.realtime.rag.indexer.load_rag_settings",
        lambda *a, **kw: {"rag_embedding_model": "m", "rag_embedding_dim": 3},
    )
    fake = _FakeEmbedding()
    indexer = RagIndexer(store=store, embedding_service=fake)
    result = indexer.backfill_fact_embeddings(account_wxid="a", conversation_id=1)
    assert result["written"] == 1
    assert fake.calls >= 1

    row = store.conn.execute("SELECT vector_blob FROM rag_fact_embeddings").fetchone()
    vec = pickle.loads(row["vector_blob"])
    assert any(x != 0 for x in vec)
