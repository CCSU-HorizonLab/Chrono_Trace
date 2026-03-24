"""情感分析服务。

功能：
- `analyze_sentiment()`：分析单条消息情感
- `analyze_batch()`：批量分析消息
- `cache_sentiment_result()`：缓存分析结果
- `get_sentiment_from_cache()`：读取缓存
- `batch_cache_sentiments()`：批量写入缓存
"""

import logging
import os
import pickle
import threading
import time
from typing import Any, Dict, List, Optional

from ...db.connection import get_db


def _safe_disable_dynamo(fn):
    """安全禁用 PyTorch 2.x 的图编译能力，避免部分环境下的 meta 错误。"""
    try:
        import torch._dynamo

        if hasattr(torch._dynamo, "disable"):
            return torch._dynamo.disable(fn)
    except Exception:
        pass
    return fn


def singleton(cls):
    instances = {}
    lock = threading.Lock()

    def get_instance(*args, **kwargs):
        with lock:
            if cls not in instances:
                instances[cls] = cls(*args, **kwargs)
        return instances[cls]

    return get_instance


logger = logging.getLogger(__name__)


@singleton
class SentimentService:
    """情感分析服务。

    使用实时情感分析服务完成极性和强度判断，
    并使用 sentence-transformers 生成 384 维语义向量。
    """

    def __init__(self):
        self._realtime_service = None
        self._embedding_model = None
        self._embedding_load_failed = False
        self._embedding_cache: Dict[str, List[float]] = {}
        self._lock = threading.Lock()

        # 提前加载实时分析服务，避免后续批量处理中首次初始化带来额外开销。
        try:
            self._load_realtime_service()
        except Exception as e:
            logger.error(f"[情感服务] 实时分析服务预加载失败: {e}")

    # ========== 模型加载 ==========

    def has_local_embedding_model(self) -> bool:
        """检查 embedding 模型是否已存在于本地缓存。"""
        if self._embedding_model is not None:
            return True

        try:
            from huggingface_hub import snapshot_download

            snapshot_download(
                "shibing624/text2vec-base-chinese",
                local_files_only=True,
            )
            return True
        except Exception:
            return False

    def _load_realtime_service(self):
        """按需加载实时情感分析服务。"""
        if self._realtime_service is None:
            from ..realtime.realtime_sentiment_service import RealtimeSentimentService

            self._realtime_service = RealtimeSentimentService(skip_db_init=True)
            logger.debug("[情感服务] 实时情感分析服务加载成功")

    def _load_embedding_model(self):
        """按需加载本地缓存中的 embedding 模型。"""
        if self._embedding_load_failed:
            return

        if self._embedding_model is None and not self.has_local_embedding_model():
            logger.error("[情感服务] 本地未找到 embedding 模型缓存，跳过运行时联网加载")
            self._embedding_load_failed = True
            return

        if self._embedding_model is not None:
            return

        with self._lock:
            if self._embedding_model is not None:
                return

            try:
                from sentence_transformers import SentenceTransformer
                import torch

                if torch.cuda.is_available():
                    device = "cuda"
                    gpu_name = torch.cuda.get_device_name(0)
                    logger.debug(f"[情感服务] 检测到 GPU: {gpu_name}")
                else:
                    device = "cpu"
                    logger.debug("[情感服务] 未检测到 GPU，使用 CPU 模式")

                model_name = "shibing624/text2vec-base-chinese"
                old_hf_hub_offline = os.environ.get("HF_HUB_OFFLINE")
                old_transformers_offline = os.environ.get("TRANSFORMERS_OFFLINE")
                os.environ["HF_HUB_OFFLINE"] = "1"
                os.environ["TRANSFORMERS_OFFLINE"] = "1"

                try:
                    self._embedding_model = SentenceTransformer(
                        model_name,
                        device=device,
                        local_files_only=True,
                        model_kwargs={
                            "low_cpu_mem_usage": False,
                            "use_safetensors": False,
                            "torch_dtype": torch.float32,
                        },
                    )
                finally:
                    if old_hf_hub_offline is None:
                        os.environ.pop("HF_HUB_OFFLINE", None)
                    else:
                        os.environ["HF_HUB_OFFLINE"] = old_hf_hub_offline

                    if old_transformers_offline is None:
                        os.environ.pop("TRANSFORMERS_OFFLINE", None)
                    else:
                        os.environ["TRANSFORMERS_OFFLINE"] = old_transformers_offline

                logger.info(f"[情感服务] 本地缓存向量模型加载成功: {model_name} (设备: {device})")
            except ImportError:
                logger.warning("[情感服务] sentence-transformers 未安装")
                logger.debug("请运行: pip install sentence-transformers")
                self._embedding_load_failed = True
            except Exception as e:
                logger.error(f"[情感服务] 向量模型加载失败: {e}")
                logger.debug("[情感服务] 将使用零向量替代，不影响核心分析流程")
                self._embedding_load_failed = True

    # ========== 情感分析 ==========

    def analyze_sentiment(self, text) -> Dict[str, Any]:
        """分析单条文本的情感。"""
        if isinstance(text, bytes):
            try:
                text = text.decode("utf-8", errors="replace")
            except Exception:
                text = ""
        elif not isinstance(text, str):
            text = str(text) if text is not None else ""

        if not text or not text.strip():
            return {
                "polarity": 0,
                "intensity": 0.0,
                "embedding": [0.0] * 384,
            }

        try:
            self._load_realtime_service()
            rt_result = self._realtime_service.analyze(text)
            embedding = self._get_embedding(text)

            return {
                "polarity": rt_result["polarity"],
                "intensity": round(rt_result["intensity"], 4),
                "embedding": embedding,
            }
        except Exception as e:
            logger.error(f"[情感服务] 分析失败: {e}, 文本: '{text[:50]}...'")
            return {
                "polarity": 0,
                "intensity": 0.0,
                "embedding": [0.0] * 384,
            }

    def analyze_batch(self, texts: List[str]) -> List[Dict[str, Any]]:
        """批量分析多条文本。"""
        if not texts:
            return []

        safe_texts: List[str] = []
        for text in texts:
            if isinstance(text, bytes):
                try:
                    text = text.decode("utf-8", errors="replace")
                except Exception:
                    text = ""
            elif not isinstance(text, str):
                text = str(text) if text is not None else ""
            safe_texts.append(text)

        self._load_realtime_service()
        sentiment_results = self._realtime_service.analyze_batch(safe_texts)
        embeddings = self._get_embeddings_batch(safe_texts)

        results: List[Dict[str, Any]] = []
        for i, text in enumerate(safe_texts):
            if not text or not text.strip():
                results.append({
                    "polarity": 0,
                    "intensity": 0.0,
                    "embedding": [0.0] * 384,
                })
                continue

            sr = sentiment_results[i] if i < len(sentiment_results) else {}
            results.append({
                "polarity": sr.get("polarity", 0),
                "intensity": round(sr.get("intensity", 0.0), 4),
                "embedding": embeddings[i] if i < len(embeddings) else [0.0] * 384,
            })

        return results

    # ========== 向量生成 ==========

    @_safe_disable_dynamo
    def _get_embedding(self, text: str) -> List[float]:
        """生成单条文本的 384 维 embedding。"""
        if text in self._embedding_cache:
            return self._embedding_cache[text]

        try:
            self._load_embedding_model()
            if self._embedding_model is None:
                return [0.0] * 384

            with self._lock:
                embedding = self._embedding_model.encode(
                    text,
                    normalize_embeddings=True,
                    show_progress_bar=False,
                )

            embedding_list = embedding.tolist()
            if len(embedding_list) > 384:
                embedding_list = embedding_list[:384]
            elif len(embedding_list) < 384:
                embedding_list = embedding_list + ([0.0] * (384 - len(embedding_list)))

            if len(self._embedding_cache) >= 10000:
                oldest_key = next(iter(self._embedding_cache))
                del self._embedding_cache[oldest_key]

            self._embedding_cache[text] = embedding_list
            return embedding_list
        except Exception as e:
            logger.error(f"[情感服务] 向量生成失败: {e}")
            return [0.0] * 384

    @_safe_disable_dynamo
    def _get_embeddings_batch(self, texts: List[str], batch_size: int = 64) -> List[List[float]]:
        """批量生成 embedding，优先复用内存缓存。"""
        if not texts:
            return []

        results: List[Optional[List[float]]] = [None] * len(texts)
        uncached_indices: List[int] = []
        uncached_texts: List[str] = []

        for i, text in enumerate(texts):
            if not text or not text.strip():
                results[i] = [0.0] * 384
            elif text in self._embedding_cache:
                results[i] = self._embedding_cache[text]
            else:
                uncached_indices.append(i)
                uncached_texts.append(text)

        if uncached_texts:
            try:
                self._load_embedding_model()

                if self._embedding_model is None:
                    for idx in uncached_indices:
                        results[idx] = [0.0] * 384
                else:
                    with self._lock:
                        embeddings = self._embedding_model.encode(
                            uncached_texts,
                            normalize_embeddings=True,
                            show_progress_bar=False,
                            batch_size=batch_size,
                        )

                    for i, idx in enumerate(uncached_indices):
                        emb_list = embeddings[i].tolist()
                        if len(emb_list) > 384:
                            emb_list = emb_list[:384]
                        elif len(emb_list) < 384:
                            emb_list = emb_list + ([0.0] * (384 - len(emb_list)))

                        results[idx] = emb_list

                        if len(self._embedding_cache) >= 10000:
                            oldest_key = next(iter(self._embedding_cache))
                            del self._embedding_cache[oldest_key]
                        self._embedding_cache[uncached_texts[i]] = emb_list
            except Exception as e:
                logger.error(f"[情感服务] 批量向量生成失败: {e}")
                for idx in uncached_indices:
                    if results[idx] is None:
                        results[idx] = [0.0] * 384

        return [embedding if embedding is not None else [0.0] * 384 for embedding in results]

    # ========== 缓存操作 ==========

    def cache_sentiment_result(
        self,
        message_id: int,
        conversation_id: int,
        polarity: int,
        intensity: float,
        embedding: List[float],
    ):
        """缓存单条情感分析结果。"""
        try:
            embedding_bytes = pickle.dumps(embedding)

            db = get_db()
            db.execute(
                """
                INSERT OR REPLACE INTO sentiment_cache
                (message_id, polarity, intensity, embedding_vector, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    message_id,
                    polarity,
                    intensity,
                    embedding_bytes,
                    int(time.time()),
                ),
            )
            db.commit()
        except Exception as e:
            logger.error(f"[情感服务] 缓存写入失败 (message_id={message_id}): {e}")

    def get_sentiment_from_cache(self, message_id: int) -> Optional[Dict[str, Any]]:
        """从缓存读取情感分析结果。"""
        try:
            db = get_db()
            cursor = db.execute(
                """
                SELECT polarity, intensity, embedding_vector
                FROM sentiment_cache
                WHERE message_id = ?
                """,
                (message_id,),
            )

            row = cursor.fetchone()
            if not row:
                return None

            embedding_data = row[2]
            if embedding_data is None:
                embedding = [0.0] * 384
            else:
                try:
                    embedding = pickle.loads(embedding_data)
                except Exception:
                    embedding = [0.0] * 384

            return {
                "polarity": row[0],
                "intensity": row[1],
                "embedding": embedding,
            }
        except Exception as e:
            logger.error(f"[情感服务] 缓存读取失败 (message_id={message_id}): {e}")
            return None

    def batch_get_sentiment_from_cache(self, message_ids: List[int]) -> Dict[int, Dict[str, Any]]:
        """批量读取情感分析缓存。"""
        if not message_ids:
            return {}

        results: Dict[int, Dict[str, Any]] = {}

        try:
            db = get_db()
            batch_size = 500

            for i in range(0, len(message_ids), batch_size):
                batch_ids = message_ids[i:i + batch_size]
                placeholders = ",".join("?" * len(batch_ids))
                cursor = db.execute(
                    f"""
                    SELECT message_id, polarity, intensity, embedding_vector
                    FROM sentiment_cache
                    WHERE message_id IN ({placeholders})
                    """,
                    batch_ids,
                )

                for row in cursor.fetchall():
                    embedding_data = row[3]
                    if embedding_data is None:
                        embedding = [0.0] * 384
                    else:
                        try:
                            embedding = pickle.loads(embedding_data)
                        except Exception:
                            embedding = [0.0] * 384

                    results[row[0]] = {
                        "polarity": row[1],
                        "intensity": row[2],
                        "embedding": embedding,
                    }
        except Exception as e:
            logger.error(f"[情感服务] 批量缓存读取失败: {e}")

        return results

    def batch_cache_sentiments(self, results: List[Dict[str, Any]]):
        """批量写入情感分析缓存。"""
        if not results:
            return

        try:
            db = get_db()
            now = int(time.time())
            batch_data = []

            for result in results:
                batch_data.append(
                    (
                        result["message_id"],
                        result["polarity"],
                        result["intensity"],
                        pickle.dumps(result["embedding"]),
                        now,
                    )
                )

            db.executemany(
                """
                INSERT OR REPLACE INTO sentiment_cache
                (message_id, polarity, intensity, embedding_vector, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                batch_data,
            )
            db.commit()
            logger.info(f"[情感服务] 批量缓存写入成功: {len(results)} 条")
        except Exception as e:
            logger.error(f"[情感服务] 批量缓存写入失败: {e}")

    # ========== 缓存统计 ==========

    def get_cache_stats(self) -> Dict[str, Any]:
        """获取缓存统计信息。"""
        try:
            db = get_db()
            cursor = db.execute(
                """
                SELECT
                    COUNT(*) as total,
                    SUM(CASE WHEN polarity = 1 THEN 1 ELSE 0 END) as positive,
                    SUM(CASE WHEN polarity = -1 THEN 1 ELSE 0 END) as negative,
                    SUM(CASE WHEN polarity = 0 THEN 1 ELSE 0 END) as neutral
                FROM sentiment_cache
                """
            )

            row = cursor.fetchone()
            return {
                "total_cached": row[0],
                "memory_cache_size": len(self._embedding_cache),
                "positive_count": row[1],
                "negative_count": row[2],
                "neutral_count": row[3],
            }
        except Exception as e:
            logger.error(f"[情感服务] 缓存统计失败: {e}")
            return {
                "total_cached": 0,
                "memory_cache_size": 0,
                "positive_count": 0,
                "negative_count": 0,
                "neutral_count": 0,
            }

    def clear_memory_cache(self):
        """清空内存缓存。"""
        self._embedding_cache.clear()
        logger.debug("[情感服务] 内存缓存已清空")
