"""Historical sentiment analysis service."""

import logging
import os
import pickle
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from ...db.connection import get_db
from .feature_extraction_config import (
    ANALYSIS_DEVICE_MODE_AUTO,
    ANALYSIS_DEVICE_MODE_CPU,
    ANALYSIS_DEVICE_MODE_GPU,
    FeatureExtractionConfig,
    normalize_analysis_device_mode,
)


def _safe_disable_dynamo(fn):
    """Best-effort guard against PyTorch dynamo issues."""
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
    """Batch sentiment + embedding service used by historical analysis."""

    def __init__(self):
        self._realtime_service = None
        self._embedding_model = None
        self._embedding_load_failed = False
        self._embedding_device = "cpu"
        self._embedding_model_path: Optional[str] = None
        self._device_mode = FeatureExtractionConfig.from_settings().analysis_device_mode
        self._embedding_cache: Dict[str, List[float]] = {}
        self._lock = threading.Lock()

        try:
            self._load_realtime_service()
        except Exception as exc:
            logger.error(f"[情感服务] 实时情感分析服务预加载失败: {exc}")

    def has_local_embedding_model(self) -> bool:
        """Return whether the embedding model is available locally."""
        if self._embedding_model is not None:
            return True
        if self._embedding_model_path and Path(self._embedding_model_path).exists():
            return True

        return self._resolve_local_embedding_model_path() is not None

    def _resolve_local_embedding_model_path(self) -> Optional[str]:
        """Resolve a usable local embedding model path without any network access."""
        if self._embedding_model_path and Path(self._embedding_model_path).exists():
            return self._embedding_model_path

        try:
            from huggingface_hub import snapshot_download

            local_path = snapshot_download(
                "shibing624/text2vec-base-chinese",
                local_files_only=True,
            )
            if local_path and Path(local_path).exists():
                self._embedding_model_path = str(local_path)
                return self._embedding_model_path
        except Exception:
            return None

        return None

    def configure_device_mode(self, device_mode: Optional[str]) -> str:
        """Change requested device mode and rebuild cached models if needed."""
        normalized_mode = normalize_analysis_device_mode(device_mode)
        if normalized_mode == self._device_mode:
            if self._realtime_service is not None:
                self._realtime_service.configure_device_mode(normalized_mode)
            return self._device_mode

        self._device_mode = normalized_mode
        self._embedding_model = None
        self._embedding_load_failed = False
        self._embedding_device = "cpu"
        self._embedding_model_path = None
        if self._realtime_service is not None:
            self._realtime_service.configure_device_mode(normalized_mode)

        logger.info(f"[情感服务] 切换分析设备模式: {normalized_mode}")
        return self._device_mode

    def _resolve_embedding_device(self) -> str:
        import torch

        if self._device_mode == ANALYSIS_DEVICE_MODE_CPU:
            return "cpu"
        if self._device_mode == ANALYSIS_DEVICE_MODE_GPU:
            if torch.cuda.is_available():
                return "cuda"
            logger.warning("[情感服务] 已选择 GPU 模式，但当前 CUDA 不可用，回退到 CPU")
            return "cpu"
        return "cuda" if torch.cuda.is_available() else "cpu"

    def _load_realtime_service(self):
        """Load realtime sentiment service lazily and keep device mode in sync."""
        if self._realtime_service is None:
            from ..realtime.realtime_sentiment_service import RealtimeSentimentService

            self._realtime_service = RealtimeSentimentService(skip_db_init=True)

        self._realtime_service.configure_device_mode(self._device_mode)
        logger.debug("[情感服务] 实时情感分析服务加载成功")

    def _load_embedding_model(self):
        """Load the embedding model using the configured device mode."""
        if self._embedding_load_failed:
            return

        local_model_path = self._resolve_local_embedding_model_path()
        if self._embedding_model is None and not local_model_path:
            logger.error(
                "[情感服务] 本地未找到 embedding 模型 "
                "(shibing624/text2vec-base-chinese) 的缓存。"
                "请先通过“历史记录分析”页面的自动下载功能获取模型，"
                "或手动运行: python -c \"from huggingface_hub import snapshot_download; "
                "snapshot_download('shibing624/text2vec-base-chinese')\""
            )
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

                device = self._resolve_embedding_device()
                if device == "cuda":
                    logger.debug(f"[情感服务] 检测到 GPU: {torch.cuda.get_device_name(0)}")
                else:
                    logger.debug("[情感服务] 使用 CPU 模式加载 embedding 模型")

                model_path = local_model_path or self._resolve_local_embedding_model_path()
                if not model_path:
                    logger.error("[鎯呮劅鏈嶅姟] embedding 妯″瀷鏈湴璺緞瑙ｆ瀽澶辫触")
                    self._embedding_load_failed = True
                    return
                old_hf_hub_offline = os.environ.get("HF_HUB_OFFLINE")
                old_transformers_offline = os.environ.get("TRANSFORMERS_OFFLINE")
                os.environ["HF_HUB_OFFLINE"] = "1"
                os.environ["TRANSFORMERS_OFFLINE"] = "1"

                try:
                    self._embedding_model = SentenceTransformer(
                        model_path,
                        device=device,
                        local_files_only=True,
                    )
                    self._embedding_device = device
                finally:
                    if old_hf_hub_offline is None:
                        os.environ.pop("HF_HUB_OFFLINE", None)
                    else:
                        os.environ["HF_HUB_OFFLINE"] = old_hf_hub_offline

                    if old_transformers_offline is None:
                        os.environ.pop("TRANSFORMERS_OFFLINE", None)
                    else:
                        os.environ["TRANSFORMERS_OFFLINE"] = old_transformers_offline

                logger.info(
                    f"[情感服务] 本地缓存向量模型加载成功: {model_path} (设备: {self._embedding_device})"
                )
            except ImportError:
                logger.warning("[情感服务] sentence-transformers 未安装")
                self._embedding_load_failed = True
            except Exception as exc:
                logger.error(f"[情感服务] 向量模型加载失败: {exc}")
                logger.debug("[情感服务] 将使用零向量替代，不影响核心分析流程")
                self._embedding_load_failed = True

    def analyze_sentiment(self, text) -> Dict[str, Any]:
        """Analyze one text and produce sentiment plus embedding."""
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
        except Exception as exc:
            logger.error(f"[情感服务] 分析失败: {exc}, 文本: '{text[:50]}...'")
            return {
                "polarity": 0,
                "intensity": 0.0,
                "embedding": [0.0] * 384,
            }

    def analyze_batch(self, texts: List[str]) -> List[Dict[str, Any]]:
        """Analyze a batch of texts."""
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
        for index, text in enumerate(safe_texts):
            if not text or not text.strip():
                results.append({
                    "polarity": 0,
                    "intensity": 0.0,
                    "embedding": [0.0] * 384,
                })
                continue

            result = sentiment_results[index] if index < len(sentiment_results) else {}
            results.append({
                "polarity": result.get("polarity", 0),
                "intensity": round(result.get("intensity", 0.0), 4),
                "embedding": embeddings[index] if index < len(embeddings) else [0.0] * 384,
            })

        return results

    @_safe_disable_dynamo
    def _get_embedding(self, text: str) -> List[float]:
        """Encode one text to a 384-d embedding."""
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
        except Exception as exc:
            logger.error(f"[情感服务] 向量生成失败: {exc}")
            return [0.0] * 384

    @_safe_disable_dynamo
    def _get_embeddings_batch(self, texts: List[str], batch_size: int = 64) -> List[List[float]]:
        """Encode a batch of texts to 384-d embeddings."""
        if not texts:
            return []

        results: List[Optional[List[float]]] = [None] * len(texts)
        uncached_indices: List[int] = []
        uncached_texts: List[str] = []

        for index, text in enumerate(texts):
            if not text or not text.strip():
                results[index] = [0.0] * 384
            elif text in self._embedding_cache:
                results[index] = self._embedding_cache[text]
            else:
                uncached_indices.append(index)
                uncached_texts.append(text)

        if uncached_texts:
            try:
                self._load_embedding_model()
                if self._embedding_model is None:
                    for index in uncached_indices:
                        results[index] = [0.0] * 384
                else:
                    with self._lock:
                        embeddings = self._embedding_model.encode(
                            uncached_texts,
                            normalize_embeddings=True,
                            show_progress_bar=False,
                            batch_size=batch_size,
                        )

                    for local_index, original_index in enumerate(uncached_indices):
                        embedding_list = embeddings[local_index].tolist()
                        if len(embedding_list) > 384:
                            embedding_list = embedding_list[:384]
                        elif len(embedding_list) < 384:
                            embedding_list = embedding_list + ([0.0] * (384 - len(embedding_list)))

                        results[original_index] = embedding_list

                        if len(self._embedding_cache) >= 10000:
                            oldest_key = next(iter(self._embedding_cache))
                            del self._embedding_cache[oldest_key]
                        self._embedding_cache[uncached_texts[local_index]] = embedding_list
            except Exception as exc:
                logger.error(f"[情感服务] 批量向量生成失败: {exc}")
                for index in uncached_indices:
                    if results[index] is None:
                        results[index] = [0.0] * 384

        return [item if item is not None else [0.0] * 384 for item in results]

    def cache_sentiment_result(
        self,
        message_id: int,
        conversation_id: int,
        polarity: int,
        intensity: float,
        embedding: List[float],
    ):
        """Cache one sentiment result."""
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
        except Exception as exc:
            logger.error(f"[情感服务] 缓存写入失败 (message_id={message_id}): {exc}")

    def get_sentiment_from_cache(self, message_id: int) -> Optional[Dict[str, Any]]:
        """Read one sentiment result from cache."""
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
        except Exception as exc:
            logger.error(f"[情感服务] 缓存读取失败 (message_id={message_id}): {exc}")
            return None

    def batch_get_sentiment_from_cache(self, message_ids: List[int]) -> Dict[int, Dict[str, Any]]:
        """Read many sentiment results from cache with WHERE IN batching."""
        if not message_ids:
            return {}

        results: Dict[int, Dict[str, Any]] = {}
        try:
            db = get_db()
            batch_size = 500

            for start in range(0, len(message_ids), batch_size):
                batch_ids = message_ids[start:start + batch_size]
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
        except Exception as exc:
            logger.error(f"[情感服务] 批量缓存读取失败: {exc}")

        return results

    def batch_cache_sentiments(self, results: List[Dict[str, Any]]):
        """Write many sentiment results into cache."""
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
        except Exception as exc:
            logger.error(f"[情感服务] 批量缓存写入失败: {exc}")

    def get_cache_stats(self) -> Dict[str, Any]:
        """Return sentiment cache statistics."""
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
        except Exception as exc:
            logger.error(f"[情感服务] 缓存统计失败: {exc}")
            return {
                "total_cached": 0,
                "memory_cache_size": 0,
                "positive_count": 0,
                "negative_count": 0,
                "neutral_count": 0,
            }

    def clear_memory_cache(self):
        """Clear in-memory embedding cache."""
        self._embedding_cache.clear()
        logger.debug("[情感服务] 内存缓存已清空")
