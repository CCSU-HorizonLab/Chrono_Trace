"""Embedding adapter for suggestion RAG."""

from __future__ import annotations

from typing import Iterable

from ...analysis.sentiment_service import SentimentService
from ...model_paths import EMBEDDING_MODEL_REPO_ID


class RagEmbeddingUnavailable(RuntimeError):
    """Raised when the local RAG embedding model is not installed."""


class RagEmbeddingDimensionMismatch(RuntimeError):
    """Raised when a model emits vectors different from the configured index dimension."""


class RagEmbeddingService:
    """Thin adapter over the existing local text2vec model."""

    model_name = EMBEDDING_MODEL_REPO_ID
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
        results = self.sentiment_service.analyze_batch(safe_texts)
        vectors = []
        self.last_raw_dimensions = []
        for result in results:
            vector = list(result.get("embedding") or [])
            self.last_raw_dimensions.append(len(vector))
            if not vector:
                raise RagEmbeddingUnavailable("本地 embedding 模型未返回可用向量")
            vectors.append(vector)
        return vectors

    def embed_text(self, text: str) -> list[float]:
        vectors = self.embed_texts([text])
        return vectors[0] if vectors else []

    def is_warm(self) -> bool:
        """公共 API：嵌入模型是否已加载（此前调用方探测私有 _embedding_model）。"""
        return bool(getattr(self._get_shared_service(), "_embedding_model", None))
