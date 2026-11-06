"""Historical sentiment analysis service."""

import logging
import os
import pickle
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from ...db.connection import get_db
from ..model_paths import (
    EMBEDDING_MODEL_DIM,
    get_embedding_model_dir,
    get_embedding_model_dim,
    get_embedding_model_repo_id,
)
from .embedding_cache_store import EmbeddingCacheStore
from .feature_extraction_config import (
    ANALYSIS_DEVICE_MODE_CPU,
    ANALYSIS_DEVICE_MODE_GPU,
    FeatureExtractionConfig,
    normalize_analysis_device_mode,
)

try:  # onnxruntime 环境必有 numpy；缺库退化为准旧格式的 list pickle
    import numpy as _np
except Exception:  # pragma: no cover
    _np = None


def pack_embedding(embedding) -> Optional[bytes]:
    """向量 → float16 ndarray pickle（512 维 2KB→1KB）；全零向量落 None。

    sentiment_cache.embedding_vector 是问答向量通道的唯一数据源，按条数
    线性胀库（5 万条 float32≈100MB），float16 无损减半。全零落 None：
    模型加载失败期的零向量兜底写实了会毒化余弦排序。读出口（问答
    _load_vector_cache / 本服务单行读）双 dtype 兼容，旧行无迁移。
    """
    if embedding is None:
        return None
    if _np is not None and isinstance(embedding, _np.ndarray):
        # ndarray 快路径（矩阵出口行）：跳过逐元素 float() 装箱；
        # astype(float16) 与 asarray(list, float16) 同舍入，pickle 字节一致
        if embedding.size == 0 or not _np.any(embedding):
            return None
        return pickle.dumps(embedding.astype(_np.float16))
    values = [float(v) for v in embedding]
    if not any(values):
        return None
    if _np is None:
        return pickle.dumps(values)
    return pickle.dumps(_np.asarray(values, dtype=_np.float16))




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
        self._embedding_dimension: Optional[int] = None
        self._embedding_device = "cpu"
        self._embedding_model_path: Optional[str] = None
        self._device_mode = FeatureExtractionConfig.from_settings().analysis_device_mode
        self._embedding_cache: Dict[str, Any] = {}  # 值为只读 float32 ndarray 行（见 _remember_embedding）
        self._l2_store: Optional[EmbeddingCacheStore] = None  # 记忆化句柄，模型/维度变化时重置
        self._lock = threading.Lock()

        try:
            self._load_realtime_service()
        except Exception as exc:
            logger.error(f"[情感服务] 实时情感分析服务预加载失败: {exc}")

    def has_local_embedding_model(self) -> bool:
        """Return whether the embedding model is available locally (ONNX fp32)."""
        if self._embedding_model is not None:
            return True
        try:
            from .onnx_inference import has_embedding_model

            return has_embedding_model()
        except Exception:
            return False

    def _resolve_local_embedding_model_path(self) -> Optional[str]:
        """Resolve a usable local embedding model path without any network access."""
        if self._embedding_model_path and Path(self._embedding_model_path).exists():
            return self._embedding_model_path

        local_path = get_embedding_model_dir()
        if local_path.exists():
            self._embedding_model_path = str(local_path)
            return self._embedding_model_path

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
        self._embedding_dimension = None
        self._embedding_cache.clear()
        self._l2_store = None  # 设备/模型随模式重建，L2 identity 失效
        self._embedding_device = "cpu"
        self._embedding_model_path = None
        try:
            # ONNX 共享 session 按 providers 缓存，模式切换需重建
            from .onnx_inference import reset_shared_engines

            reset_shared_engines()
        except Exception:
            pass
        if self._realtime_service is not None:
            self._realtime_service.configure_device_mode(normalized_mode)

        logger.info(f"[情感服务] 切换分析设备模式: {normalized_mode}")
        return self._device_mode

    def _load_realtime_service(self):
        """Load realtime sentiment service lazily and keep device mode in sync."""
        if self._realtime_service is None:
            from ..realtime.realtime_sentiment_service import RealtimeSentimentService

            self._realtime_service = RealtimeSentimentService()

        self._realtime_service.configure_device_mode(self._device_mode)
        logger.debug("[情感服务] 实时情感分析服务加载成功")

    def _load_embedding_model(self):
        """Load the ONNX embedding model using the configured device mode."""
        if self._embedding_load_failed:
            # 失败可能只是暂时的(onnxruntime 后装、模型后导出):文件就位时
            # 允许重试,避免整个进程生命周期被一次瞬时失败锁死。
            try:
                from .onnx_inference import has_embedding_model

                if not has_embedding_model():
                    return
            except Exception:
                return
            self._embedding_load_failed = False
        if self._embedding_model is not None:
            return
        with self._lock:
            if self._embedding_model is not None:
                return
            try:
                from .onnx_inference import get_shared_engine, has_embedding_model

                if not has_embedding_model():
                    raise FileNotFoundError(
                        "缺少 ONNX fp32 嵌入模型（models/<name>/onnx/model.onnx；"
                        "开发机先跑 backend/scripts/export_models_onnx.py，打包版应内置）"
                    )
                engine = get_shared_engine("embedding", device_mode=self._device_mode)
                self._embedding_model = engine
                self._embedding_device = engine.device_tag
                self._embedding_load_failed = False
                self._l2_store = None  # 新引擎可能换变体：L2 identity 随加载重建
                self._set_embedding_dimension_from_model()
                logger.info(
                    "[情感服务] ONNX 嵌入模型已加载 (device=%s, providers=%s)",
                    engine.device_tag, engine.providers,
                )
            except Exception as exc:
                logger.error("[情感服务] ONNX 嵌入模型加载失败: %s}", exc)
                self._embedding_load_failed = True

    def _set_embedding_dimension_from_model(self) -> None:
        """Record the model's native vector width without projecting vectors."""
        getter = getattr(self._embedding_model, "get_sentence_embedding_dimension", None)
        try:
            raw_dimension = getter() if callable(getter) else None
        except Exception:
            raw_dimension = None
        if isinstance(raw_dimension, (int, float)) and int(raw_dimension) > 0:
            self._set_embedding_dimension(int(raw_dimension))

    def _set_embedding_dimension(self, dimension: int) -> None:
        if dimension <= 0:
            return
        if self._embedding_dimension not in {None, dimension}:
            # Avoid mixing old projected vectors with a newly loaded model.
            self._embedding_cache.clear()
            self._l2_store = None  # L2 identity 含 dim，随维度失效
        self._embedding_dimension = dimension

    def _fallback_embedding(self) -> List[float]:
        return [0.0] * (self._embedding_dimension or EMBEDDING_MODEL_DIM)

    def _expected_embedding_dimension(self) -> Optional[int]:
        """Load the local model if needed so persisted old-width vectors are skipped."""
        self._load_embedding_model()
        return self._embedding_dimension

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
                "embedding": self._fallback_embedding(),
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
                "embedding": self._fallback_embedding(),
            }

    def analyze_batch(
        self, texts: List[str], include_embeddings: bool = False
    ) -> List[Dict[str, Any]]:
        """Analyze a batch of texts.

        include_embeddings 由调用方决定：预处理编排器在嵌入模型可用时传
        True（问答向量通道以本表 embedding_vector 为唯一数据源）；缺模型
        时 False 落 NULL。相似度特征走 pairs 自己的 L2 嵌入缓存，不经本表。
        """
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
        embeddings = (
            self._get_embeddings_batch(safe_texts)
            if include_embeddings
            else [None] * len(safe_texts)
        )

        results: List[Dict[str, Any]] = []
        for index, text in enumerate(safe_texts):
            if not text or not text.strip():
                results.append({
                    "polarity": 0,
                    "intensity": 0.0,
                    "embedding": self._fallback_embedding(),
                })
                continue

            result = sentiment_results[index] if index < len(sentiment_results) else {}
            results.append({
                "polarity": result.get("polarity", 0),
                "intensity": round(result.get("intensity", 0.0), 4),
                "embedding": embeddings[index] if index < len(embeddings) else self._fallback_embedding(),
            })

        return results

    def embed_texts_batch(self, texts: List[str]) -> List[List[float]]:
        """仅产向量（跳过情感推理），调用方只消费 embedding 时使用。

        RAG 索引构建曾走 analyze_batch(include_embeddings=True)——语义抽取
        每段候选句白跑一遍情感分类模型，产出从未被读取。向量口径与
        analyze_batch 完全一致（同一 _get_embeddings_batch，含 L1/L2 缓存）。
        """
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
        return self._get_embeddings_batch(safe_texts)

    def _get_embedding(self, text: str) -> List[float]:
        """Encode one text using the local model's native vector dimension.

        委托批量路径：L1/L2 缓存与维度校验单点维护（此前单条直调 encode
        绕过 L2，是与 interaction_pairs 同源的缓存旁路）。
        """
        try:
            return self._get_embeddings_batch([text])[0]
        except Exception as exc:
            logger.error(f"[情感服务] 向量生成失败: {exc}")
            return self._fallback_embedding()

    def _remember_embedding(self, text: str, vector) -> None:
        """L1 写入（FIFO 上限 4000）：模型编码与 L2 命中回填共用。

        行统一存只读 float32 ndarray（numpy 可用时）：矩阵出口零装箱复用；
        write=False 让误写当场抛错而非静默脏缓存。回填路径此前裸写无上
        限——重建/重分析场景 L2 全命中时，历史库每个唯一文本都会驻留内
        存（十万级文本即数百 MB），与编码路径的 FIFO 预算不一致。
        """
        if _np is not None:
            if not isinstance(vector, _np.ndarray):
                vector = _np.asarray(vector, dtype=_np.float32)
            vector.setflags(write=False)
        if len(self._embedding_cache) >= 4000:
            del self._embedding_cache[next(iter(self._embedding_cache))]
        self._embedding_cache[text] = vector

    def _get_embeddings_batch(self, texts: List[str], batch_size: int = 64) -> List[List[float]]:
        """list 出口薄壳：内部统一走矩阵路径（L1/L2/encode 缓存链单点）。"""
        if not texts:
            return []
        if _np is None:  # 无 onnxruntime 环境：无模型，全零兜底（不 new 依赖）
            self._load_embedding_model()
            return [self._fallback_embedding() for _ in texts]
        return [row.tolist() for row in self._get_embeddings_matrix(texts, batch_size=batch_size)]

    def _get_embeddings_matrix(self, texts: List[str], batch_size: int = 64) -> "_np.ndarray":
        """矩阵出口：与 list 出口同一条 L1/L2/encode 缓存链，返回
        (len(texts), dim) 的 float32 只读矩阵（行序对齐输入）。

        三级缓存：L1 内存 dict（进程内）→ L2 embedding_cache 表（跨进程，
        键=content_sha1+model+device）→ 模型 encode。重复分析/增量导入后
        重分析只嵌新文本（嵌入占分析耗时 99%）。

        相似度消费侧（会话切分/交互对）直连 einsum：此前 list 出口每行
        dim 个 float 装箱（L2 tolist / encode tolist）再被消费侧 asarray
        拆箱，8 万单元热跑 ≈ 8000 万元素往返，是相似度阶段的纯开销大头。
        """
        if _np is None:
            raise RuntimeError("[情感服务] 嵌入矩阵出口依赖 numpy")
        if not texts:
            return _np.zeros((0, self._embedding_dimension or 0), dtype=_np.float32)

        self._load_embedding_model()
        dim = self._embedding_dimension
        fallback_row: Optional["_np.ndarray"] = None

        def zero_row() -> "_np.ndarray":
            nonlocal fallback_row
            if fallback_row is None:
                fallback_row = _np.zeros(dim or EMBEDDING_MODEL_DIM, dtype=_np.float32)
            return fallback_row

        rows: List[Optional["_np.ndarray"]] = [None] * len(texts)
        uncached_indices: List[int] = []
        uncached_texts: List[str] = []

        for index, text in enumerate(texts):
            if not text or not text.strip():
                rows[index] = zero_row()
            elif (
                text in self._embedding_cache
                and len(self._embedding_cache[text]) == dim
            ):
                rows[index] = self._embedding_cache[text]
            else:
                uncached_indices.append(index)
                uncached_texts.append(text)

        # L2 持久缓存：命中回填 L1（后续同文本内存级命中）；
        # as_arrays 直出 frombuffer 只读视图，免去每行 dim 个 float 装箱
        l2_store = self._embedding_cache_store()
        if l2_store is not None and uncached_texts:
            try:
                l2_hits = l2_store.batch_lookup(uncached_texts, as_arrays=True)
            except Exception as exc:
                logger.debug("[情感服务] 嵌入 L2 查询失败（忽略）: %s", exc)
                l2_hits = {}
            if l2_hits:
                remaining_indices: List[int] = []
                remaining_texts: List[str] = []
                for index, text in zip(uncached_indices, uncached_texts):
                    vector = l2_hits.get(text)
                    if vector is not None:
                        rows[index] = vector
                        self._remember_embedding(text, vector)
                    else:
                        remaining_indices.append(index)
                        remaining_texts.append(text)
                uncached_indices = remaining_indices
                uncached_texts = remaining_texts

        if uncached_texts:
            try:
                if self._embedding_model is None:
                    for index in uncached_indices:
                        rows[index] = zero_row()
                else:
                    with self._lock:
                        embeddings = self._embedding_model.encode(
                            uncached_texts,
                            normalize_embeddings=True,
                            show_progress_bar=False,
                            batch_size=batch_size,
                        )
                    encoded = _np.asarray(embeddings, dtype=_np.float32)
                    self._set_embedding_dimension(int(encoded.shape[1]))

                    new_vectors: List["_np.ndarray"] = []
                    for local_index, original_index in enumerate(uncached_indices):
                        row = encoded[local_index]
                        row.setflags(write=False)
                        rows[original_index] = row
                        new_vectors.append(row)

                        self._remember_embedding(uncached_texts[local_index], row)
                    # L2 落库：模型已加载（gate 在 _embedding_cache_store），零向量
                    # 兜底不会进入此分支；INSERT OR IGNORE 幂等
                    if l2_store is not None:
                        try:
                            l2_store.batch_store(uncached_texts, new_vectors)
                        except Exception as exc:
                            logger.debug("[情感服务] 嵌入 L2 写入失败（忽略）: %s", exc)
            except Exception as exc:
                logger.error(f"[情感服务] 批量向量生成失败: {exc}")
                for index in uncached_indices:
                    if rows[index] is None:
                        rows[index] = zero_row()

        # np.zeros 兜底 None 行（全路径应已填满，防御口径与旧 list 出口一致）
        matrix = _np.zeros((len(texts), dim or EMBEDDING_MODEL_DIM), dtype=_np.float32)
        for index, row in enumerate(rows):
            if row is not None:
                matrix[index] = row
        matrix.setflags(write=False)
        return matrix

    def _embedding_cache_store(self) -> Optional[EmbeddingCacheStore]:
        """L2 持久缓存句柄（模型加载后记忆化，失效点见重置处）。

        模型未加载/加载失败时返回 None——此路径产出的是零向量兜底，
        读写 L2 都会毒化缓存（把「无模型跑过一次」固化成假命中）。
        记忆化：相似度链路分块调用数千次，此前每次构造都读 settings.json
        解析模型变体（repo_id/dim），8 万单元实测白付 13s。
        """
        if self._embedding_model is None or self._embedding_load_failed:
            return None
        if self._l2_store is not None:
            return self._l2_store
        # 维度与模型名跟随激活变体：L2 键含 repo_id，切模型自动隔离旧向量
        dim = self._embedding_dimension or get_embedding_model_dim() or EMBEDDING_MODEL_DIM
        try:
            self._l2_store = EmbeddingCacheStore(
                get_embedding_model_repo_id(), self._embedding_device, dim
            )
        except Exception:
            self._l2_store = None
        return self._l2_store

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
            embedding_bytes = pack_embedding(embedding)
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
            expected_dim = self._expected_embedding_dimension()
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
                return None
            try:
                embedding = pickle.loads(embedding_data)
            except Exception:
                return None
            if _np is not None and isinstance(embedding, _np.ndarray):
                embedding = embedding.astype(_np.float32).tolist()  # float16 紧凑行
            if not isinstance(embedding, list) or not embedding:
                return None
            if expected_dim is not None and len(embedding) != expected_dim:
                return None

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
                    SELECT message_id, polarity, intensity
                    FROM sentiment_cache
                    WHERE message_id IN ({placeholders})
                    """,
                    batch_ids,
                )

                for row in cursor.fetchall():
                    # 存在性即有效：不 SELECT 向量列（旧库十万行 768 维
                    # torch pickle 的反序列化纯浪费），极性/强度是唯一
                    # 被消费的字段（pairs 直读 SQL、orchestrator 只判跳过）
                    results[row[0]] = {
                        "polarity": row[1],
                        "intensity": row[2],
                        "embedding": None,
                    }
        except Exception as exc:
            logger.debug(f"[情感服务] 批量缓存读取跳过（含旧 torch pickle 行，按 miss 处理）: {exc}")

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
                embedding = result.get("embedding")
                batch_data.append(
                    (
                        result["message_id"],
                        result["polarity"],
                        result["intensity"],
                        pack_embedding(embedding),
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
