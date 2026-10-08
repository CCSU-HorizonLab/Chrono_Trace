"""嵌入向量持久缓存（L2）：text→vector 是模型的纯函数，跨进程复用。

背景：历史分析 99% 耗时在嵌入（会话切分相似度 + 情感批次）。内存 L1
（SentimentService._embedding_cache，4000 FIFO）进程重启即失——本模块
把向量按 (content_sha1, model, device) 落 SQLite，重复分析只嵌新文本。

关键不变量：
- 键含 model + device：换模型 repo id / 切换 cpu-cuda 自动隔离（GPU 与
  CPU 浮点噪声 ~1e-3，足以在相似度阈值边界翻转会话切分结果）；
- 向量存 float32 原始字节（非 pickle 非 fp16）：往返与冷跑 bit 级一致，
  等价性测试可做强断言；
- 模型未加载时的零向量兜底**禁止写入**（防毒化缓存）；
- ALGO_VERSION bump 不需要清本表——text→vector 与算法版本无关。
"""
from __future__ import annotations

import hashlib
import logging
import os
import time
from typing import Iterable, List, Optional, Sequence

from ...db.connection import get_db
from ...config import SETTINGS_PATH

logger = logging.getLogger(__name__)

_BATCH_IN_SIZE = 500  # SQLite IN 参数上限防御（与 sentiment_cache 批查同款）


def _cache_enabled_from_settings() -> bool:
    """读 settings.json feature_extraction.embedding_persistent_cache（默认开）。"""
    if os.environ.get("CHRONO_DISABLE_EMBEDDING_CACHE"):
        return False
    try:
        import json
        from pathlib import Path

        path = Path(SETTINGS_PATH)
        if not path.exists():
            return True
        with open(path, "r", encoding="utf-8") as handle:
            settings = json.load(handle)
        value = settings.get("feature_extraction", {}).get("embedding_persistent_cache", True)
        return bool(value)
    except Exception:
        return True


def content_sha1(text: str) -> str:
    """文本内容指纹（与 rag/providers/models.py 的 message hash 约定一致用 sha1）。"""
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


class EmbeddingCacheStore:
    """embedding_cache 表的读写收口（线程本地连接经 get_db()）。"""

    def __init__(self, model: str, device: str, dim: int):
        if not model or not device or dim <= 0:
            raise ValueError(f"embedding cache identity 非法: model={model!r} device={device!r} dim={dim}")
        self._model = str(model)
        self._device = str(device)
        self._dim = int(dim)
        self._enabled = _cache_enabled_from_settings()

    @property
    def enabled(self) -> bool:
        return self._enabled

    def batch_lookup(self, texts: Sequence[str]) -> dict[str, List[float]]:
        """批量查缓存：返回 {text: vector}；未命中/维度不符的文本不在结果里。

        维度校验防御：库里可能残留旧宽度向量（模型切换但 sha1 撞库等极端
        情况），对齐 sentiment_cache 的 miss-then-recompute 语义。
        """
        if not self._enabled or not texts:
            return {}

        wanted = {}
        for text in texts:
            if text and text.strip():
                wanted[content_sha1(text)] = text
        if not wanted:
            return {}

        found: dict[str, List[float]] = {}
        conn = get_db()
        keys = list(wanted.keys())
        for start in range(0, len(keys), _BATCH_IN_SIZE):
            chunk = keys[start:start + _BATCH_IN_SIZE]
            placeholders = ",".join(["?"] * len(chunk))
            rows = conn.execute(
                f"""
                SELECT content_sha1, dim, vector
                FROM embedding_cache
                WHERE content_sha1 IN ({placeholders})
                  AND model = ? AND device = ?
                """,
                (*chunk, self._model, self._device),
            ).fetchall()
            import struct

            import numpy as np

            for row in rows:
                if int(row["dim"] or 0) != self._dim:
                    continue
                blob = row["vector"]
                try:
                    # np.frombuffer 零拷贝视图 + 一次 tolist：比 struct.unpack
                    # 逐元素装箱快 2-3×（暖跑主路径的固定税）。
                    # dtype 显式小端 '<f4' 与写入侧 struct.pack("<Nf") 对齐，
                    # 不依赖平台字节序
                    vector = np.frombuffer(blob, dtype="<f4").tolist()
                except Exception:
                    continue
                if len(vector) == self._dim:
                    found[wanted[row["content_sha1"]]] = vector
        return found

    def batch_store(self, texts: Sequence[str], vectors: Sequence[Sequence[float]]) -> int:
        """批量写入（INSERT OR IGNORE 幂等）。返回实际尝试写入条数。"""
        if not self._enabled:
            return 0
        rows = []
        now = int(time.time())
        import struct

        for text, vector in zip(texts, vectors):
            if not text or not text.strip() or not vector:
                continue  # 空文本不落库
            if len(vector) != self._dim:
                continue
            if not any(vector):
                continue  # 全零向量是模型缺失时的兜底产物，禁止毒化缓存
            try:
                blob = struct.pack(f"<{len(vector)}f", *vector)
            except Exception:
                continue
            rows.append((content_sha1(text), self._model, self._device, self._dim, blob, now))

        if not rows:
            return 0
        try:
            conn = get_db()
            conn.executemany(
                """
                INSERT OR IGNORE INTO embedding_cache
                    (content_sha1, model, device, dim, vector, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                rows,
            )
            conn.commit()
            return len(rows)
        except Exception as exc:
            logger.warning("[嵌入缓存] 写入失败（不影响分析流程）: %s", exc)
            return 0

    @staticmethod
    def purge(model: Optional[str] = None) -> int:
        """清空缓存（可按 model 过滤），返回删除行数。维护脚本用。"""
        conn = get_db()
        if model:
            cursor = conn.execute("DELETE FROM embedding_cache WHERE model = ?", (model,))
        else:
            cursor = conn.execute("DELETE FROM embedding_cache")
        conn.commit()
        return cursor.rowcount or 0

    @staticmethod
    def stats() -> dict:
        """容量报告（行数/字节数/按 model 分布）。"""
        conn = get_db()
        try:
            total = conn.execute(
                "SELECT COUNT(*) AS n, COALESCE(SUM(LENGTH(vector)), 0) AS bytes FROM embedding_cache"
            ).fetchone()
            by_model = conn.execute(
                "SELECT model, device, COUNT(*) AS n FROM embedding_cache GROUP BY model, device"
            ).fetchall()
            return {
                "rows": int(total["n"] or 0),
                "bytes": int(total["bytes"] or 0),
                "by_model": [
                    {"model": r["model"], "device": r["device"], "rows": int(r["n"] or 0)}
                    for r in by_model
                ],
            }
        except Exception:
            return {"rows": 0, "bytes": 0, "by_model": []}


def iter_unique_texts(texts: Iterable[str]) -> List[str]:
    """去重保序（同批重复文本只查/存一次）。"""
    seen = set()
    ordered = []
    for text in texts:
        if text and text not in seen:
            seen.add(text)
            ordered.append(text)
    return ordered
