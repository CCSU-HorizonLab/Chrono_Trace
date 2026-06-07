"""RAG retrieval and ranking for realtime suggestions."""

from __future__ import annotations

import json
import math
import re
import time
from typing import Any

from .rag_config import load_rag_settings
from .rag_embedding import RagEmbeddingService, RagEmbeddingUnavailable
from .rag_store import RagStore


class RagRetriever:
    """Contact-scoped retriever with vector and keyword fallback."""

    DOC_TYPE_WEIGHTS = {
        "hot_context": 0.65,
        "fact_memory": 0.55,
        "topic_segment": 0.45,
        "evidence_excerpt": 0.42,
        "dialogue_turn": 0.30,
        "shared_memory": 0.40,
        "relationship_state": 0.12,
        "communication_style": 0.12,
        "self_style_example": 0.20,
        "feedback_example": 0.45,
    }

    def __init__(
        self,
        store: RagStore | None = None,
        embedding_service: RagEmbeddingService | None = None,
    ):
        self.store = store or RagStore()
        self.embedding_service = embedding_service or RagEmbeddingService()

    def build_query(self, context: dict[str, Any], trigger_type: str, intent: str) -> str:
        parts = [trigger_type, intent]
        trigger_context = context.get("trigger_context") or {}
        if trigger_context:
            parts.extend(str(value) for value in trigger_context.values())
        for msg in (context.get("recent_messages") or [])[-8:]:
            content = str(msg.get("content") or "").strip()
            if content:
                parts.append(content)
        user_context = context.get("user_context")
        if isinstance(user_context, str):
            parts.append(user_context)
        elif isinstance(user_context, list):
            parts.extend(str(item.get("content") or "") for item in user_context[-3:])
        return "\n".join(parts)[:1200]

    def retrieve(
        self,
        *,
        account_wxid: str,
        conversation_id: int,
        query: str,
        timeout_ms: int = 800,
        deadline: float | None = None,
        limit: int = 6,
    ) -> dict[str, Any]:
        started = time.perf_counter()
        if self._timed_out(started, timeout_ms, deadline):
            return self._empty(started, {}, degraded=True, reason="timeout", timed_out=True)
        settings = load_rag_settings()
        model = str(settings["rag_embedding_model"])
        dim = int(settings["rag_embedding_dim"])
        status = self.store.get_status(account_wxid, conversation_id) or {}
        if not status.get("enabled", 1):
            return self._empty(started, status, degraded=True, reason="conversation_disabled")
        if status.get("status") == "failed":
            return self._empty(started, status, degraded=True, reason="index_failed")

        try:
            docs = self.store.list_documents_with_vectors(
                account_wxid,
                conversation_id,
                embedding_model=model,
                embedding_dim=dim,
            )
            if docs:
                if self._timed_out(started, timeout_ms, deadline):
                    return self._empty(started, status, degraded=True, reason="timeout", timed_out=True)
                if self._embedding_is_warm():
                    query_vector = self.embedding_service.embed_text(query)
                    scored = self._score_vector_docs(query, query_vector, docs)
                    strategy = "vector"
                else:
                    scored = self._score_keyword_docs(query, docs)
                    strategy = "keyword_fallback"
            else:
                docs = self.store.list_documents(account_wxid, conversation_id)
                scored = self._score_keyword_docs(query, docs)
                strategy = "keyword_fallback"
        except RagEmbeddingUnavailable:
            docs = self.store.list_documents(account_wxid, conversation_id)
            scored = self._score_keyword_docs(query, docs)
            strategy = "keyword_fallback"
        except Exception:
            docs = self.store.list_documents(account_wxid, conversation_id)
            scored = self._score_keyword_docs(query, docs)
            strategy = "keyword_fallback"

        elapsed_ms = int((time.perf_counter() - started) * 1000)
        if elapsed_ms > timeout_ms or (deadline is not None and time.perf_counter() > deadline):
            return self._empty(started, status, degraded=True, reason="timeout", timed_out=True)

        filtered = []
        query_tokens = set(self._tokens(query))
        time_scope = self._time_scope(query)
        memory_lookup = self._is_memory_lookup_query(query)
        for item in scored:
            doc = item["doc"]
            if memory_lookup and str(doc.get("doc_type") or "") in {"self_style_example", "communication_style"}:
                continue
            if not self._within_time_scope(doc, time_scope):
                continue
            if str(doc.get("sensitivity") or "normal") == "sensitive":
                # Sensitive memories require explicit current-topic overlap.
                doc_tokens = set(self._tokens(doc.get("content") or ""))
                if len(query_tokens & doc_tokens) < 2:
                    continue
            if self._timed_out(started, timeout_ms, deadline):
                return self._empty(started, status, degraded=True, reason="timeout", timed_out=True)
            if float(item["score"]) <= 0:
                continue
            item["score"] = round(float(item["score"]), 4)
            filtered.append(item)
            if len(filtered) >= limit:
                break

        return {
            "items": filtered,
            "strategy": strategy,
            "status": status,
            "timed_out": False,
            "degraded": strategy != "vector" or status.get("status") in {"pending", "stale"},
            "degrade_reason": None if strategy == "vector" else strategy,
            "elapsed_ms": elapsed_ms,
            "by_type": self._count_by_type(filtered),
        }

    def _timed_out(self, started: float, timeout_ms: int, deadline: float | None) -> bool:
        if deadline is not None and time.perf_counter() > deadline:
            return True
        return int((time.perf_counter() - started) * 1000) > timeout_ms

    def _embedding_is_warm(self) -> bool:
        service = getattr(self.embedding_service, "sentiment_service", None)
        if service is None:
            return True
        return getattr(service, "_embedding_model", None) is not None

    def _empty(
        self,
        started: float,
        status: dict[str, Any],
        *,
        degraded: bool,
        reason: str,
        timed_out: bool = False,
    ) -> dict[str, Any]:
        return {
            "items": [],
            "strategy": "none",
            "status": status,
            "timed_out": timed_out,
            "degraded": degraded,
            "degrade_reason": reason,
            "elapsed_ms": int((time.perf_counter() - started) * 1000),
        }

    def _score_vector_docs(
        self,
        query: str,
        query_vector: list[float],
        docs: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        keyword_scores = {item["id"]: score for item, score in self._keyword_pairs(query, docs)}
        scored = []
        for doc in docs:
            cosine = self._cosine(query_vector, doc.get("vector") or [])
            keyword_score = keyword_scores.get(doc["id"], 0.0)
            score = self._final_score(
                doc,
                vector_score=cosine,
                keyword_score=keyword_score,
            )
            scored.append({"doc": doc, "score": round(score, 4)})
        return sorted(scored, key=lambda item: item["score"], reverse=True)

    def _score_keyword_docs(
        self,
        query: str,
        docs: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        scored = []
        for doc, base_score in self._keyword_pairs(query, docs):
            if base_score <= 0:
                continue
            score = self._final_score(doc, vector_score=0.0, keyword_score=base_score)
            scored.append({"doc": doc, "score": round(score, 4)})
        return sorted(scored, key=lambda item: item["score"], reverse=True)

    def _keyword_pairs(
        self,
        query: str,
        docs: list[dict[str, Any]],
    ) -> list[tuple[dict[str, Any], float]]:
        query_tokens = set(self._tokens(query))
        pairs = []
        for doc in docs:
            text = f"{doc.get('content') or ''} {doc.get('redacted_content') or ''}"
            doc_tokens = set(self._tokens(text))
            overlap = len(query_tokens & doc_tokens)
            score = overlap / max(4, len(query_tokens)) if query_tokens else 0.0
            if query and str(doc.get("content") or "").strip() in query:
                score += 0.2
            pairs.append((doc, score))
        return pairs

    def _tokens(self, text: str) -> list[str]:
        compact = re.sub(r"\s+", "", str(text or ""))
        tokens = re.split(r"[\s,，。！？；：、/()（）\[\]\-]+", str(text or ""))
        words = [token for token in tokens if len(token) >= 2]
        for size in (2, 3, 4):
            words.extend(compact[index:index + size] for index in range(max(0, len(compact) - size + 1)))
        return words[:300]

    def _cosine(self, a: list[float], b: list[float]) -> float:
        if not a or not b:
            return 0.0
        size = min(len(a), len(b))
        dot = sum(float(a[index]) * float(b[index]) for index in range(size))
        norm_a = math.sqrt(sum(float(a[index]) ** 2 for index in range(size)))
        norm_b = math.sqrt(sum(float(b[index]) ** 2 for index in range(size)))
        if norm_a <= 0 or norm_b <= 0:
            return 0.0
        return dot / (norm_a * norm_b)

    def _time_decay(self, doc: dict[str, Any]) -> float:
        try:
            source_ts = int(doc.get("source_ts") or 0)
        except (TypeError, ValueError):
            return 1.0
        if source_ts <= 0:
            return 1.0
        age_days = max(0.0, (time.time() - source_ts) / 86400)
        return max(0.20, math.exp(-age_days / 60.0))

    def _final_score(self, doc: dict[str, Any], *, vector_score: float, keyword_score: float) -> float:
        doc_type = str(doc.get("doc_type") or "")
        recency_score = self._time_decay(doc)
        type_score = self.DOC_TYPE_WEIGHTS.get(doc_type, 0.1)
        if vector_score > 0:
            return (
                float(vector_score) * 0.40
                + float(keyword_score) * 0.25
                + recency_score * 0.25
                + type_score * 0.10
            )
        return (
            float(keyword_score) * 0.65
            + recency_score * 0.25
            + type_score * 0.10
        )

    def _time_scope(self, query: str) -> str:
        compact = re.sub(r"\s+", "", str(query or ""))
        if any(token in compact for token in ("刚刚", "刚才", "刚", "刚说")):
            return "recent_24h"
        if "上次" in compact or "上回" in compact:
            return "recent_preferred"
        return "all"

    def _is_memory_lookup_query(self, query: str) -> bool:
        compact = re.sub(r"\s+", "", str(query or ""))
        return any(
            token in compact
            for token in (
                "历史记录",
                "聊天记录",
                "RAG文档",
                "rag文档",
                "记忆文档",
                "文档里",
                "记录里",
                "历史里",
                "找一下",
                "找下",
                "找找",
                "查一下",
                "查下",
                "翻一下",
                "翻下",
            )
        )

    def _within_time_scope(self, doc: dict[str, Any], time_scope: str) -> bool:
        if time_scope != "recent_24h":
            return True
        try:
            source_ts = int(doc.get("source_ts") or 0)
        except (TypeError, ValueError):
            return False
        if source_ts <= 0:
            return False
        return (time.time() - source_ts) <= 86400

    def _count_by_type(self, items: list[dict[str, Any]]) -> dict[str, int]:
        counts: dict[str, int] = {}
        for item in items:
            doc = item.get("doc") or {}
            doc_type = str(doc.get("doc_type") or "")
            counts[doc_type] = counts.get(doc_type, 0) + 1
        return counts

    def metadata(self, doc: dict[str, Any]) -> dict[str, Any]:
        try:
            return json.loads(doc.get("metadata_json") or "{}")
        except Exception:
            return {}
