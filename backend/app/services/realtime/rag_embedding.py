"""Embedding adapter for suggestion RAG."""

from __future__ import annotations

from typing import Iterable

from ..analysis.sentiment_service import SentimentService
from ..model_paths import EMBEDDING_MODEL_REPO_ID


class RagEmbeddingUnavailable(RuntimeError):
    """Raised when the local RAG embedding model is not installed."""


class RagEmbeddingService:
    """Thin adapter over the existing local text2vec model."""

    model_name = EMBEDDING_MODEL_REPO_ID
    dim = 384

    def __init__(self, sentiment_service: SentimentService | None = None):
        self.sentiment_service = sentiment_service or SentimentService()

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
        for result in results:
            vector = list(result.get("embedding") or [])
            if len(vector) > self.dim:
                vector = vector[: self.dim]
            elif len(vector) < self.dim:
                vector.extend([0.0] * (self.dim - len(vector)))
            vectors.append(vector)
        return vectors

    def embed_text(self, text: str) -> list[float]:
        vectors = self.embed_texts([text])
        return vectors[0] if vectors else [0.0] * self.dim
