"""Relevance gate for deciding whether retrieved RAG items enter prompts."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import re
from typing import Any, Literal


GateDecisionValue = Literal["inject", "weak_inject", "no_hit", "skip"]


@dataclass(frozen=True)
class RagGateDecision:
    decision: GateDecisionValue
    reason: str
    top_score: float = 0.0
    no_hit_eligible: bool = False
    allowed_doc_types: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["allowed_doc_types"] = list(self.allowed_doc_types)
        return data


class RagRelevanceGate:
    """Small, explicit relevance policy between retrieval and prompt injection."""

    HIGH_VALUE_TYPES = {
        "hot_context",
        "fact_memory",
        "topic_segment",
        "evidence_excerpt",
        "shared_memory",
        "dialogue_turn",
        "feedback_example",
    }
    RELATIONSHIP_TYPES = {"relationship_state", "contact_preference", "communication_style"}
    DISALLOWED_SENSITIVITY = {"sensitive"}

    def decide(
        self,
        *,
        query: str,
        items: list[dict[str, Any]],
        strategy: str | None,
        output_mode: str,
        trigger_type: str,
        recent_messages: list[dict[str, Any]] | None = None,
        user_context: Any = None,
        memory_intent: dict[str, Any] | None = None,
        timed_out: bool = False,
        degraded_reason: str | None = None,
        previous_rag_hit: bool = False,
    ) -> RagGateDecision:
        if timed_out or degraded_reason == "timeout":
            return RagGateDecision("skip", "timeout", 0.0, False)
        if strategy == "none" and degraded_reason in {"conversation_disabled", "index_failed"}:
            return RagGateDecision("skip", degraded_reason or "disabled", 0.0, False)

        usable = [item for item in items if self._is_usable_item(item)]
        no_hit_eligible = self.is_no_hit_eligible(
            query=query,
            output_mode=output_mode,
            trigger_type=trigger_type,
            user_context=user_context,
            memory_intent=memory_intent,
            previous_rag_hit=previous_rag_hit,
        )
        if not usable:
            return RagGateDecision(
                "no_hit" if no_hit_eligible else "skip",
                "no_result",
                0.0,
                no_hit_eligible,
            )

        top = usable[0]
        top_score = round(float(top.get("score") or 0.0), 4)
        top_type = self._doc_type(top)
        mode = str((memory_intent or {}).get("mode") or "")

        if top_type == "hot_context" and top_score >= 0.20:
            return RagGateDecision("inject", "hot_context", top_score, no_hit_eligible)
        if mode == "memory_request":
            memory_items = [
                item
                for item in usable
                if self._doc_type(item) in {"fact_memory", "topic_segment", "evidence_excerpt", "shared_memory", "dialogue_turn"}
            ]
            if memory_items:
                best_memory = memory_items[0]
                best_score = round(float(best_memory.get("score") or 0.0), 4)
                if best_score >= 0.10:
                    return RagGateDecision("inject", "memory_request_match", best_score, no_hit_eligible)
        if top_score >= 0.42 or (top_score >= 0.30 and top_type in self.HIGH_VALUE_TYPES):
            return RagGateDecision("inject", "high_score", top_score, no_hit_eligible)

        if 0.25 <= top_score < 0.42 and top_type in self.RELATIONSHIP_TYPES:
            return RagGateDecision(
                "weak_inject",
                "weak_relationship_context",
                top_score,
                no_hit_eligible,
                tuple(sorted(self.RELATIONSHIP_TYPES)),
            )

        return RagGateDecision("skip", "low_score", top_score, no_hit_eligible)

    def is_no_hit_eligible(
        self,
        *,
        query: str,
        output_mode: str,
        trigger_type: str,
        user_context: Any = None,
        memory_intent: dict[str, Any] | None = None,
        previous_rag_hit: bool = False,
    ) -> bool:
        memory_intent = memory_intent or {}
        if bool(memory_intent.get("no_hit_eligible")):
            return True
        if trigger_type in {"memory_search", "memory_lookup", "rag_search"}:
            return True
        if previous_rag_hit and self._looks_like_followup(query):
            return True
        mode = str(memory_intent.get("mode") or "")
        if output_mode == "reply" and mode in {"memory_request", "relationship_context"}:
            return True
        return output_mode == "reply" and self._looks_like_history_question(
            self._latest_user_text(user_context) or query
        )

    def _is_usable_item(self, item: dict[str, Any]) -> bool:
        doc = item.get("doc") or item
        if str(doc.get("sensitivity") or item.get("sensitivity") or "normal") in self.DISALLOWED_SENSITIVITY:
            return False
        if int(doc.get("enabled", item.get("enabled", 1)) or 0) != 1:
            return False
        if doc.get("superseded_by") is not None:
            return False
        return True

    def _doc_type(self, item: dict[str, Any]) -> str:
        doc = item.get("doc") or item
        return str(doc.get("doc_type") or item.get("doc_type") or "")

    def _latest_user_text(self, user_context: Any) -> str:
        if isinstance(user_context, str):
            return user_context.strip()
        if isinstance(user_context, list):
            for msg in reversed(user_context):
                if isinstance(msg, dict) and msg.get("role") == "user":
                    return str(msg.get("content") or "").strip()
        return ""

    def _looks_like_followup(self, text: str) -> bool:
        compact = re.sub(r"\s+", "", str(text or ""))
        if not compact:
            return False
        if len(compact) <= 12:
            return True
        return any(token in compact for token in ("具体", "哪家", "哪个", "还有", "相关建议", "怎么回", "给建议"))

    def _looks_like_history_question(self, text: str) -> bool:
        compact = re.sub(r"\s+", "", str(text or ""))
        if not compact:
            return False
        has_temporal_anchor = any(token in compact for token in ("上次", "上回", "之前", "以前", "那次", "刚刚", "上轮"))
        asks_detail = any(token in compact for token in ("啥", "什么", "哪", "谁", "记得", "不记得", "说过", "聊过", "提过"))
        has_person_anchor = any(token in compact for token in ("她", "他", "对方", "我们", "ta", "TA"))
        reported_memory = any(token in compact for token in ("说过", "聊过", "提过", "说的", "聊的", "提的"))
        referential_anchor = any(token in compact for token in ("那个", "那家", "那次", "这个", "这家"))
        direct_lookup = any(token in compact for token in ("找一下", "找下", "找找", "查一下", "查下", "翻一下", "翻下", "看看", "看下"))
        explicit_memory_store = any(token in compact for token in ("历史记录", "聊天记录", "RAG文档", "rag文档", "记忆文档", "文档里", "记录里", "历史里"))
        return (
            (has_temporal_anchor and asks_detail and has_person_anchor)
            or (has_person_anchor and reported_memory and asks_detail)
            or (has_person_anchor and referential_anchor and reported_memory)
            or (explicit_memory_store and (direct_lookup or asks_detail))
        )
