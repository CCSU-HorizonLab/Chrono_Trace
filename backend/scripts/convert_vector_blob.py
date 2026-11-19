"""一次性：把向量 BLOB 从 pickle 格式就地转换为 vector_codec 裸字节（CTV1）。

背景：rag_embeddings / rag_fact_embeddings / sentiment_cache 三表向量曾存
pickle（ndarray 或 list），代码已切 vector_codec 统一格式（pickle.loads
对被替换的库文件是任意代码执行面）。历史 pickle 行新代码按缺失处理
（返回 []）——本脚本就地转换免去全量重嵌（rag 两表约 10 万行）。可重复
执行：已是新格式的行自动跳过；解不开的行（如需 torch 的旧 768 维行）
跳过并计数，留给消费方 miss 重建。
"""
from __future__ import annotations

import pickle
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "backend") not in sys.path:
    sys.path.insert(0, str(ROOT / "backend"))

from app.db.connection import get_db, write_transaction
from app.services.vector_codec import VECTOR_MAGIC, pack_vector_f16

TABLES = [
    ("rag_embeddings", "vector_blob", "id"),
    ("rag_fact_embeddings", "vector_blob", "id"),
    ("sentiment_cache", "embedding_vector", "id"),
]


def main() -> int:
    db = get_db()
    for table, column, pk in TABLES:
        rows = db.execute(
            f"SELECT {pk}, {column} FROM {table} WHERE {column} IS NOT NULL"
        ).fetchall()
        converted = skipped = 0
        with write_transaction(db):
            for row_id, blob in rows:
                if isinstance(blob, (bytes, bytearray)) and blob[:4] == VECTOR_MAGIC:
                    continue
                try:
                    value = pickle.loads(blob)
                except Exception:
                    skipped += 1
                    continue
                db.execute(
                    f"UPDATE {table} SET {column} = ? WHERE {pk} = ?",
                    (pack_vector_f16(value), row_id),
                )
                converted += 1
        print(f"{table}: 转换 {converted} 行，跳过 {skipped} 行（解不开，留待 miss 重建）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
