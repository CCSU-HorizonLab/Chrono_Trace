"""Semantic fact extraction for contact-scoped RAG indexing."""

from __future__ import annotations

from dataclasses import dataclass
import math
import re
from typing import Any

from .rag_embedding import RagEmbeddingService, RagEmbeddingUnavailable
from .rag_fact_quality import (
    SYSTEM_MESSAGE_MARKERS,
    is_usable_shadow_fact,
    looks_corrupted,
)
from .rag_segmenter import RagSegment, RagSegmenter


@dataclass(frozen=True)
class SemanticFact:
    content: str
    source_id: int | None
    source_ts: int
    subject: str
    topics: list[str]
    entities: list[str]
    memory_kind: str
    semantic_score: float
    evidence_message_ids: list[int]
    source_window_start_ts: int
    source_window_end_ts: int


def calibrate_fact_confidence(
    semantic_score: float,
    *,
    evidence_count: int,
    memory_kind: str = "",
) -> float:
    """Convert a raw embedding-cosine score into a usable confidence signal.

    原实现把余弦相似度直接当 confidence，导致分布塌缩在 0.5~0.7（text2vec
    短文本的天然余弦区间），下游“高置信派生 / 低置信 quarantine”无从谈起。
    校准分三部分：

    1. 语义分量：把余弦域 [0.45, 0.80] 线性映射到 [0.30, 0.90]，拉开分布；
    2. 证据加成：合并后 >=2 条证据消息时逐条加分，封顶 0.10；
    3. 弱方法封顶：marker_fallback 只有规则标记、无语义匹配，压在 0.55 以下。

    重复确认的阶梯递增由 merge_fact_evidence 在合并时执行（每次 +0.06，
    封顶 0.95），因为它依赖历史行而与单次抽取无关。
    """
    score = float(semantic_score or 0.0)
    norm = min(1.0, max(0.0, (score - 0.45) / 0.35))
    semantic_component = 0.30 + 0.60 * norm
    evidence_bonus = min(0.10, 0.04 * max(0, int(evidence_count) - 1))
    calibrated = semantic_component + evidence_bonus
    if str(memory_kind or "") == "marker_fallback":
        calibrated = min(calibrated, 0.55)
    return round(min(0.95, max(0.20, calibrated)), 4)


CONFIRMATION_STEP = 0.06
CONFIDENCE_CEILING = 0.95


class SemanticFactExtractor:
    """Extract reusable memories by matching chat turns against semantic prototypes."""

    SINGLE_THRESHOLD = 0.58
    WINDOW_THRESHOLD = 0.52
    MAX_FACTS_PER_SEGMENT = 8

    PROTOTYPES: dict[str, tuple[str, ...]] = {
        "preference_like": (
            "对方表达了喜欢、偏好、想要、感兴趣的事物",
            "用户或对方说自己爱用、爱吃、爱玩、愿意再次尝试某个东西",
        ),
        "preference_dislike": (
            "对方表达了不喜欢、排斥、讨厌、避开的事物",
            "用户或对方说某件事不合胃口、不想再做、不适合自己",
        ),
        "plan_or_appointment": (
            "双方约定了时间、地点、见面、吃饭、出行或共同活动",
            "聊天里出现未来计划、安排、预约、要一起做的事情",
        ),
        "promise_or_commitment": (
            "一方答应、承诺、说好、确认会做某件事",
            "聊天里有需要之后遵守或记住的承诺和约定",
        ),
        "purchase_or_price": (
            "聊天提到价格、预算、购买、贵、便宜、下单或想买",
            "对某个商品、服务、门票、游戏或礼物的花费有讨论",
        ),
        "food_or_place": (
            "聊天提到餐厅、饮品、食物、地点、店铺或去哪里",
            "双方讨论吃什么、喝什么、去哪家店、在哪里见",
        ),
        "hobby_or_game": (
            "聊天提到游戏、卡组、流派、运动、影视、音乐或长期爱好",
            "对方透露了自己正在玩、正在看、常做的娱乐兴趣",
        ),
        "relationship_boundary": (
            "聊天提到边界、分寸、玩笑、关系状态、介意或不介意",
            "对方表达了相处方式、沟通边界或关系里的舒适度",
        ),
        "personal_profile": (
            "聊天透露了个人背景、工作、学校、家庭、生日、身体状态",
            "对方说了关于自己的稳定身份信息或个人情况",
        ),
        "recurring_habit": (
            "聊天提到经常、每次、习惯、总是、固定会做的事情",
            "对方透露了反复出现的生活习惯或情绪应对方式",
        ),
    }

    def __init__(
        self,
        embedding_service: RagEmbeddingService,
        segmenter: RagSegmenter | None = None,
    ):
        self.embedding_service = embedding_service
        self.segmenter = segmenter or RagSegmenter()
        self._prototype_vectors: dict[str, list[float]] | None = None

    def extract(self, segment: RagSegment) -> list[SemanticFact]:
        candidates = self._candidate_windows(segment)
        if not candidates:
            return []
        try:
            return self._extract_with_embeddings(segment, candidates)
        except RagEmbeddingUnavailable:
            return self._fallback_marker_facts(segment)
        except Exception:
            return self._fallback_marker_facts(segment)

    def _extract_with_embeddings(
        self,
        segment: RagSegment,
        candidates: list[dict[str, Any]],
    ) -> list[SemanticFact]:
        prototype_vectors = self._load_prototype_vectors()
        vectors = self.embedding_service.embed_texts(
            [item["content"] for item in candidates]
            + [item["window_text"] for item in candidates]
        )
        single_vectors = vectors[: len(candidates)]
        window_vectors = vectors[len(candidates) :]

        facts: list[SemanticFact] = []
        for item, single_vector, window_vector in zip(candidates, single_vectors, window_vectors):
            single_kind, single_score = self._best_match(single_vector, prototype_vectors)
            window_kind, window_score = self._best_match(window_vector, prototype_vectors)
            if single_score >= self.SINGLE_THRESHOLD and is_usable_shadow_fact(
                single_kind,
                item["content"],
                context=item["window_text"],
            ):
                facts.append(self._build_fact(segment, item, single_kind, single_score))
            elif (
                window_score >= self.WINDOW_THRESHOLD
                and single_score >= 0.45
                and is_usable_shadow_fact(
                    window_kind,
                    item["content"],
                    context=item["window_text"],
                )
            ):
                facts.append(self._build_fact(segment, item, window_kind, window_score))

        facts.sort(key=lambda fact: (-fact.semantic_score, fact.source_ts))
        return self._consolidate_fact_clusters(facts)

    def _consolidate_fact_clusters(self, facts: list[SemanticFact]) -> list[SemanticFact]:
        """Collapse overlapping candidate windows into one auditable memory.

        The old implementation deduplicated by source message ID, so every
        adjacent turn became a separate active fact.  Overlapping evidence IDs
        identify one conversational episode; retain the strongest focal turn and
        union its evidence instead of exposing all fragments.
        """
        clusters: list[list[SemanticFact]] = []
        for fact in sorted(facts, key=lambda item: item.source_ts):
            fact_ids = set(fact.evidence_message_ids or [])
            target: list[SemanticFact] | None = None
            for cluster in reversed(clusters):
                anchor = cluster[-1]
                if anchor.memory_kind != fact.memory_kind:
                    continue
                if abs(int(fact.source_ts or 0) - int(anchor.source_ts or 0)) > 600:
                    continue
                anchor_ids = set(anchor.evidence_message_ids or [])
                if len(fact_ids & anchor_ids) >= 2:
                    target = cluster
                    break
            if target is None:
                clusters.append([fact])
            else:
                target.append(fact)

        consolidated: list[SemanticFact] = []
        for cluster in clusters:
            representative = max(cluster, key=lambda item: item.semantic_score)
            evidence_ids = sorted({
                evidence_id
                for item in cluster
                for evidence_id in (item.evidence_message_ids or [])
            })
            consolidated.append(
                SemanticFact(
                    content=representative.content,
                    source_id=representative.source_id,
                    source_ts=representative.source_ts,
                    subject=representative.subject,
                    topics=representative.topics,
                    entities=representative.entities,
                    memory_kind=representative.memory_kind,
                    semantic_score=representative.semantic_score,
                    evidence_message_ids=evidence_ids,
                    source_window_start_ts=min(item.source_window_start_ts for item in cluster),
                    source_window_end_ts=max(item.source_window_end_ts for item in cluster),
                )
            )
        consolidated.sort(key=lambda fact: fact.source_ts)
        return consolidated[: self.MAX_FACTS_PER_SEGMENT]

    def _load_prototype_vectors(self) -> dict[str, list[float]]:
        if self._prototype_vectors is not None:
            return self._prototype_vectors
        labels: list[str] = []
        texts: list[str] = []
        for kind, prototypes in self.PROTOTYPES.items():
            for prototype in prototypes:
                labels.append(kind)
                texts.append(prototype)
        vectors = self.embedding_service.embed_texts(texts)
        by_kind: dict[str, list[list[float]]] = {}
        for kind, vector in zip(labels, vectors):
            by_kind.setdefault(kind, []).append(vector)
        self._prototype_vectors = {
            kind: self._mean_vector(kind_vectors)
            for kind, kind_vectors in by_kind.items()
        }
        return self._prototype_vectors

    def _candidate_windows(self, segment: RagSegment) -> list[dict[str, Any]]:
        output: list[dict[str, Any]] = []
        messages = list(segment.messages)
        for index, msg in enumerate(messages):
            content = self._compact(msg.get("content"))
            if not self._is_informative_candidate(content):
                continue
            window = [
                item
                for item in messages[max(0, index - 1): min(len(messages), index + 2)]
                if self._compact(item.get("content"))
                and self._is_informative_candidate(self._compact(item.get("content")))
            ]
            output.append(
                {
                    "message": msg,
                    "content": content,
                    "window": window,
                    "window_text": "\n".join(
                        f"{self._sender_label(item)}: {self._compact(item.get('content'))}"
                        for item in window
                    ),
                }
            )
        return output

    def _build_fact(
        self,
        segment: RagSegment,
        item: dict[str, Any],
        memory_kind: str,
        score: float,
    ) -> SemanticFact:
        msg = item["message"]
        content = item["content"]
        sender = self._sender_label(msg)
        context_lines = [
            f"{self._sender_label(window_msg)}: {self._compact(window_msg.get('content'))}"
            for window_msg in item["window"]
            if int(window_msg.get("id") or 0) != int(msg.get("id") or 0)
        ]
        rendered = f"{sender}提到：{content}"
        if context_lines:
            rendered += "\n相关上下文：" + " / ".join(context_lines[:2])
        timestamps = [int(window_msg.get("timestamp") or segment.end_ts) for window_msg in item["window"]]
        evidence_ids = [
            int(window_msg.get("id") or 0)
            for window_msg in item["window"]
            if int(window_msg.get("id") or 0)
        ]
        return SemanticFact(
            content=rendered,
            source_id=int(msg.get("id") or 0) or None,
            source_ts=int(msg.get("timestamp") or segment.end_ts),
            subject=sender,
            topics=self.segmenter.extract_topics(content),
            entities=self.segmenter.extract_entities(content),
            memory_kind=memory_kind,
            semantic_score=round(float(score), 4),
            evidence_message_ids=evidence_ids,
            source_window_start_ts=min(timestamps) if timestamps else segment.start_ts,
            source_window_end_ts=max(timestamps) if timestamps else segment.end_ts,
        )

    def _fallback_marker_facts(self, segment: RagSegment) -> list[SemanticFact]:
        facts: list[SemanticFact] = []
        for fallback in self.segmenter.build_fact_memories(segment):
            source_ts = int(fallback.get("source_ts") or segment.end_ts)
            source_id = fallback.get("source_id")
            try:
                normalized_source_id = int(source_id or 0) or None
            except (TypeError, ValueError):
                normalized_source_id = None
            if not is_usable_shadow_fact(
                "marker_fallback",
                fallback.get("content") or "",
                context=segment.render_excerpt(segment, max_messages=4)
                if hasattr(segment, "render_excerpt")
                else "",
            ):
                continue
            facts.append(
                SemanticFact(
                    content=str(fallback.get("content") or ""),
                    source_id=normalized_source_id,
                    source_ts=source_ts,
                    subject=str(fallback.get("subject") or ""),
                    topics=list(fallback.get("topics") or segment.topics),
                    entities=list(fallback.get("entities") or segment.entities),
                    memory_kind="marker_fallback",
                    semantic_score=0.5,
                    evidence_message_ids=[normalized_source_id] if normalized_source_id else [],
                    source_window_start_ts=source_ts,
                    source_window_end_ts=source_ts,
                )
            )
        return facts[: self.MAX_FACTS_PER_SEGMENT]

    def _best_match(
        self,
        vector: list[float],
        prototype_vectors: dict[str, list[float]],
    ) -> tuple[str, float]:
        best_kind = "personal_profile"
        best_score = 0.0
        for kind, prototype_vector in prototype_vectors.items():
            score = self._cosine(vector, prototype_vector)
            if score > best_score:
                best_kind = kind
                best_score = score
        return best_kind, best_score

    def _mean_vector(self, vectors: list[list[float]]) -> list[float]:
        if not vectors:
            return []
        size = min(len(vector) for vector in vectors if vector)
        if size <= 0:
            return []
        return [
            sum(float(vector[index]) for vector in vectors) / len(vectors)
            for index in range(size)
        ]

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

    def _is_informative_candidate(self, content: str) -> bool:
        if len(content) < 3:
            return False
        if re.fullmatch(r"[\W_]+", content, flags=re.UNICODE):
            return False
        compact = re.sub(r"\s+", "", content)
        if compact in {"哈哈哈", "哈哈哈哈", "嗯嗯", "好的", "可以", "行吧"}:
            return False
        # 乱码/二进制消息（加密残留、损坏内容）：不作为焦点，也不进上下文窗口
        if looks_corrupted(compact):
            return False
        # 微信系统/通知消息不是用户表达
        if any(marker in compact for marker in SYSTEM_MESSAGE_MARKERS):
            return False
        return True

    def _sender_label(self, msg: dict[str, Any]) -> str:
        return "我" if int(msg.get("is_sender") or 0) else "对方"

    def _compact(self, content: Any) -> str:
        return re.sub(r"\s+", " ", str(content or "")).strip()[:180]
