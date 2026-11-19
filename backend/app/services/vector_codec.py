"""向量 BLOB 编解码：float16 裸字节 + 魔数前缀，全库唯一格式。

rag_embeddings / rag_fact_embeddings / sentiment_cache 三处向量曾存
pickle（ndarray 或 list）——向量本质是数值数组，pickle.loads 对被替换
的库文件是任意代码执行面，且历史 torch pickle 行还要求消费方装 torch。
统一换裸字节后：魔数不匹配（历史 pickle 行）一律按缺失返回 []，由
消费方走 miss 重建；存量行用 backend/scripts/convert_vector_blob.py
一次性就地转换，免去全量重嵌。
"""
from __future__ import annotations

import numpy as _np

VECTOR_MAGIC = b"CTV1"  # Chrono Trace Vector, float16 little-endian


def pack_vector_f16(values) -> bytes:
    """float 序列 / ndarray → 魔数 + float16 小端裸字节（512 维约 1KB）。

    向量只做余弦排序（无阈值边界翻转问题），f16 精度足够——与 L2
    embedding_cache 的 float32 刻意保守不同（那边要 bit 级一致）。
    """
    return VECTOR_MAGIC + _np.asarray(values, dtype=_np.float16).tobytes()


def unpack_vector_f16(blob) -> list:
    """魔数 + float16 裸字节 → float32 list；非本格式（历史 pickle 行）
    返回 []，消费方按缺失重建。字节数与 f16 不对齐的脏行同样返回 []。
    """
    if isinstance(blob, (bytes, bytearray)) and blob[:4] == VECTOR_MAGIC:
        body = bytes(blob[4:])
        if len(body) % 2 == 0:
            return _np.frombuffer(body, dtype=_np.float16).astype(_np.float32).tolist()
    return []
