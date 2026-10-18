"""RAG 向量 float16 紧凑存储测试（写侧换新 + 读侧双 dtype 兼容）。

rag_embeddings/rag_fact_embeddings 原存 pickle float64 list（512 维
4624B/条），只做余弦排序无阈值边界翻转问题，f16 缩一半。存量 float64
行不迁移，读侧 coerce 继续可读；用户手动重建索引即全量换新。
"""

import math
import os
import pickle
import sqlite3
import sys


sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


from app.services.realtime.rag.store import RagStore, pack_rag_vector, unpack_rag_vector


MODEL = "test/embed-model"
DIM = 512
NOW = 1_700_000_000


def _conn():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    return conn


def _seed_document(store, doc_id=None):
    return store.upsert_document(
        account_wxid="wxid_a",
        conversation_id=1,
        doc_type="topic_segment",
        source_table="messages",
        source_id=str(doc_id or 1),
        source_ts=NOW,
        content="对方喜欢玩卡牌游戏",
        redacted_content="对方喜欢玩卡牌游戏",
        index_version="rag_v3",
        source_kind="historical",
    )


def _seed_fact(store):
    store.conn.execute(
        """
        INSERT INTO rag_facts
        (account_wxid, conversation_id, subject, kind, content, status, enabled,
         confidence, created_at, updated_at)
        VALUES ('wxid_a', 1, 'alice', 'hobby', '对方喜欢玩卡牌游戏', 'active', 1, 0.9, ?, ?)
        """,
        (NOW, NOW),
    )
    store.conn.commit()
    return 1


class TestPackUnpack:
    def test_pack_writes_f16_ndarray_half_size(self):
        vector = [0.0123 + i * 1e-5 for i in range(DIM)]
        blob = pack_rag_vector(vector)

        import numpy as np

        loaded = pickle.loads(blob)
        assert isinstance(loaded, np.ndarray)
        assert loaded.dtype == np.float16
        # float64 list pickle 4624B → f16 ndarray 应缩一半以上
        assert len(blob) < len(pickle.dumps([float(v) for v in vector])) * 0.6

    def test_unpack_returns_list_for_both_formats(self):
        import numpy as np

        new_blob = pack_rag_vector([0.1] * DIM)
        old_blob = pickle.dumps([0.1] * DIM)  # 存量 float64 list

        assert isinstance(unpack_rag_vector(new_blob), list)
        assert isinstance(unpack_rag_vector(old_blob), list)
        assert len(unpack_rag_vector(new_blob)) == DIM

    def test_roundtrip_cosine_preserved(self):
        """余弦排序保真：f16 相对误差 ~1e-3，相似度损失远小于排序间隔。"""

        def cosine(a, b):
            dot = sum(x * y for x, y in zip(a, b))
            na = math.sqrt(sum(x * x for x in a))
            nb = math.sqrt(sum(y * y for y in b))
            return dot / (na * nb)

        vec_a = [0.5 if i % 2 == 0 else -0.1 for i in range(DIM)]
        vec_b = [0.5 if i % 2 == 0 else 0.2 for i in range(DIM)]  # 与 a 高度相似
        vec_c = [(-1) ** i * 0.3 for i in range(DIM)]  # 与 a 近正交
        original = cosine(vec_a, vec_b) - cosine(vec_a, vec_c)
        after = cosine(unpack_rag_vector(pack_rag_vector(vec_a)), unpack_rag_vector(pack_rag_vector(vec_b))) - cosine(
            unpack_rag_vector(pack_rag_vector(vec_a)), unpack_rag_vector(pack_rag_vector(vec_c))
        )
        assert abs(original - after) < 1e-3
        # 排序结论不变：b 比 c 更接近 a
        assert after > 0


class TestDocumentVectors:
    def test_upsert_and_read_roundtrip(self):
        conn = _conn()
        store = RagStore(conn)
        doc_id = _seed_document(store)
        store.upsert_embedding(
            document_id=doc_id,
            account_wxid="wxid_a",
            conversation_id=1,
            embedding_model=MODEL,
            embedding_dim=DIM,
            vector=[0.0123] * DIM,
            embedding_provider="local",
        )
        store.conn.commit()

        # 底层落的是 f16 ndarray
        blob = conn.execute(
            "SELECT vector_blob FROM rag_embeddings WHERE document_id = ?", (doc_id,)
        ).fetchone()["vector_blob"]

        import numpy as np

        assert isinstance(pickle.loads(blob), np.ndarray)

        # 读出口是 list，数值在 f16 精度内
        docs = store.list_documents_with_vectors(
            "wxid_a", 1, embedding_model=MODEL, embedding_dim=DIM
        )
        assert len(docs) == 1
        vector = docs[0]["vector"]
        assert isinstance(vector, list) and len(vector) == DIM
        assert all(abs(v - 0.0123) < 1e-4 for v in vector)

    def test_legacy_float64_rows_still_readable(self):
        """存量行（float64 list pickle）不迁移，读侧原样返回。"""
        conn = _conn()
        store = RagStore(conn)
        doc_id = _seed_document(store)
        store.conn.execute(
            """
            INSERT INTO rag_embeddings
            (document_id, account_wxid, conversation_id, embedding_model, embedding_dim,
             embedding_provider, vector_blob, created_at)
            VALUES (?, 'wxid_a', 1, ?, ?, 'local', ?, ?)
            """,
            (doc_id, MODEL, DIM, pickle.dumps([0.0123] * DIM), NOW),
        )
        store.conn.commit()

        docs = store.list_documents_with_vectors(
            "wxid_a", 1, embedding_model=MODEL, embedding_dim=DIM
        )
        assert len(docs) == 1
        vector = docs[0]["vector"]
        assert isinstance(vector, list) and len(vector) == DIM
        assert all(v == 0.0123 for v in vector)  # 老行 bit 级不变


class TestFactVectors:
    def test_upsert_and_read_roundtrip(self):
        conn = _conn()
        store = RagStore(conn)
        fact_id = _seed_fact(store)
        store.upsert_fact_embedding(
            fact_id=fact_id,
            account_wxid="wxid_a",
            conversation_id=1,
            embedding_model=MODEL,
            embedding_dim=DIM,
            vector=[0.0456] * DIM,
        )
        store.conn.commit()

        facts = store.list_facts_with_vectors(
            "wxid_a", 1, embedding_model=MODEL, embedding_dim=DIM
        )
        assert len(facts) == 1
        vector = facts[0]["vector"]
        assert isinstance(vector, list) and len(vector) == DIM
        # backfill 的零向量判定按 float 迭代，f16 往返后非零事实不应误判
        assert any(float(x) != 0.0 for x in vector)

    def test_legacy_float64_rows_still_readable(self):
        conn = _conn()
        store = RagStore(conn)
        fact_id = _seed_fact(store)
        store.conn.execute(
            """
            INSERT INTO rag_fact_embeddings
            (fact_id, account_wxid, conversation_id, embedding_model, embedding_dim,
             embedding_provider, vector_blob, created_at)
            VALUES (?, 'wxid_a', 1, ?, ?, 'local', ?, ?)
            """,
            (fact_id, MODEL, DIM, pickle.dumps([0.0456] * DIM), NOW),
        )
        store.conn.commit()

        facts = store.list_facts_with_vectors(
            "wxid_a", 1, embedding_model=MODEL, embedding_dim=DIM
        )
        assert len(facts) == 1
        assert all(v == 0.0456 for v in facts[0]["vector"])
