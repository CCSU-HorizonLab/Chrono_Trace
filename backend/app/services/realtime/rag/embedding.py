"""Embedding adapter for suggestion RAG."""

from __future__ import annotations

import logging
import threading
from typing import Iterable

from ...analysis.sentiment_service import SentimentService
from ...model_paths import get_embedding_model_repo_id


class RagEmbeddingUnavailable(RuntimeError):
    """Raised when the local RAG embedding model is not installed."""


class RagEmbeddingDimensionMismatch(RuntimeError):
    """Raised when a model emits vectors different from the configured index dimension."""


class RagEmbeddingService:
    """Thin adapter over the existing local text2vec model."""

    @property
    def model_name(self) -> str:
        # 跟随激活变体（错误提示与诊断口径一致）
        return get_embedding_model_repo_id()
    _shared_sentiment_service: SentimentService | None = None

    def __init__(self, sentiment_service: SentimentService | None = None):
        self.last_raw_dimensions: list[int] = []
        if sentiment_service is not None:
            self.sentiment_service = sentiment_service
            return
        if RagEmbeddingService._shared_sentiment_service is None:
            RagEmbeddingService._shared_sentiment_service = SentimentService()
        self.sentiment_service = RagEmbeddingService._shared_sentiment_service

    def ensure_available(self) -> None:
        if not self.sentiment_service.has_local_embedding_model():
            raise RagEmbeddingUnavailable(
                f"本地 embedding 模型缺失: {self.model_name}"
            )

    def embed_texts(self, texts: Iterable[str]) -> list[list[float]]:
        safe_texts = [str(text or "") for text in texts]
        if not safe_texts:
            return []
        self.ensure_available()
        # Reuse the existing analysis service to avoid a second model stack.
        # include_embeddings=True：RAG 真正消费向量（预处理路径默认不嵌）
        results = self.sentiment_service.analyze_batch(
            safe_texts, include_embeddings=True
        )
        vectors = []
        self.last_raw_dimensions = []
        for result in results:
            vector = list(result.get("embedding") or [])
            self.last_raw_dimensions.append(len(vector))
            # 零向量同样视为模型不可用:ONNX 故障窗口期曾产出零向量并被
            # 落库,导致 199 条事实余弦恒 0、检索静默失效。
            if not vector or all(float(x) == 0.0 for x in vector):
                raise RagEmbeddingUnavailable("本地 embedding 模型未返回可用向量")
            vectors.append(vector)
        return vectors

    def embed_text(self, text: str) -> list[float]:
        vectors = self.embed_texts([text])
        return vectors[0] if vectors else []

    def prewarm(self) -> bool:
        """暖机:触发 embedding 引擎加载。

        模型是懒加载,而检索路径的暖机检查只探测不加载——没有任何前置
        调用(实时情感/好感分析)时,RAG 向量通道会以 embedding_cold 永久
        降级 keyword_fallback,记忆注入随之失效。调用方应在后台线程执行。
        """
        try:
            self.embed_texts(["预热"])
            return True
        except Exception:
            return False

    def is_warm(self) -> bool:
        """公共 API：嵌入模型是否已加载（此前调用方探测私有 _embedding_model）。"""
        return bool(getattr(self._get_shared_service(), "_embedding_model", None))


_prewarm_lock = threading.Lock()
_prewarm_started = False
logger = logging.getLogger(__name__)


def kick_background_prewarm(embedding_service: "RagEmbeddingService | None" = None) -> None:
    """进程级一次性后台预热。

    在监听启动/上下文装配时调用,使 embedding 引擎在用户第一次提问前
    就绪——否则首次检索落在懒加载窗口内,事实会因向量分缺失被门禁丢弃
    (真实使用:22:39 首查 selected=1 仅 hot_context,预热同秒才完成)。
    """
    global _prewarm_started
    with _prewarm_lock:
        if _prewarm_started:
            return
        _prewarm_started = True

    def _warm():
        try:
            service = embedding_service or RagEmbeddingService()
            if service.prewarm():
                logger.info("[RAG Embedding] 进程级后台预热完成")
        except Exception as exc:
            logger.debug("[RAG Embedding] 进程级预热失败: %s", exc)

    threading.Thread(target=_warm, daemon=True, name="rag-embedding-prewarm-app").start()
