"""Build minimized RAG retrieval context for LLM suggestions."""

from __future__ import annotations

import hashlib
import json
import re
import time
import logging
from typing import Any

from ....db.connection import get_db
from ..privacy_redactor import PrivacyRedactor
from .config import is_remote_llm_model, load_rag_settings
from .indexer import RagIndexer
from .retriever import RagRetriever
from .relevance_gate import RagGateDecision, RagRelevanceGate
from .segmenter import RagSegmenter
from .store import RAG_INDEX_VERSION
from .store import RagStore
from ..memory_intent import MemoryIntent, detect_memory_intent


logger = logging.getLogger(__name__)


class RagQueryBuilder:
    """Build a retrieval query from the current request and nearby context."""

    MAX_QUERY_CHARS = 1200

    def build(
        self,
        context: dict[str, Any],
        *,
        trigger_type: str,
        intent: str,
        memory_intent: MemoryIntent | None = None,
    ) -> str:
        parts: list[str] = []
        latest = self._latest_user_input(context)
        mode = str(getattr(memory_intent, "mode", "") or "")
        if mode == "memory_request" and memory_intent and memory_intent.query:
            parts.append(memory_intent.query)
        if latest:
            parts.append(latest)

        compacted: list[str] = []
        seen = set()
        for part in parts:
            text = re.sub(r"\s+", " ", str(part or "")).strip()
            if not text or text in seen:
                continue
            compacted.append(text)
            seen.add(text)
        return "\n".join(compacted)[: self.MAX_QUERY_CHARS]

    def expanded_terms(
        self,
        context: dict[str, Any],
        *,
        memory_intent: MemoryIntent | None = None,
    ) -> list[str]:
        # Query expansion used to inject a hand-maintained domain vocabulary.
        # Semantic retrieval now receives only the user question; hot context
        # remains a separate display/scoring channel.
        return []

    def _latest_user_input(self, context: dict[str, Any]) -> str:
        user_context = context.get("user_context")
        if isinstance(user_context, list):
            for msg in reversed(user_context):
                if isinstance(msg, dict) and msg.get("role") == "user":
                    return str(msg.get("content") or "").strip()
        if isinstance(user_context, str):
            return user_context.strip()
        recent = context.get("recent_messages") or []
        if isinstance(recent, list):
            for msg in reversed(recent):
                if not isinstance(msg, dict):
                    continue
                if msg.get("is_sender") == 1 or msg.get("sender_attr") == "self":
                    return str(msg.get("content") or "").strip()
        return ""


class RagContextBuilder:
    """Orchestrates lazy index, retrieval, minimization, redaction and logs."""

    MAX_CONTEXT_CHARS = 560
    HOT_CONTEXT_MAX_AGE_SECONDS = 86400
    # P1.5 注入护栏：影子开关关闭=用户停用关系策略链路（含已生成的历史
    # 策略行）；低置信策略不注入，只留在影子层
    RELATIONSHIP_POLICY_MIN_CONFIDENCE = 0.55
    # P1.2 对方偏好策略独立预算槽：不占事实 1600 字、不占关系策略槽
    CONTACT_PREFERENCE_MAX_ITEMS = 6
    CONTACT_PREFERENCE_MIN_CONFIDENCE = 0.55

    def __init__(
        self,
        store: RagStore | None = None,
        indexer: RagIndexer | None = None,
        retriever: RagRetriever | None = None,
        query_builder: RagQueryBuilder | None = None,
        relevance_gate: RagRelevanceGate | None = None,
    ):
        self.store = store or RagStore()
        self.indexer = indexer or RagIndexer(self.store)
        self.retriever = retriever or RagRetriever(self.store)
        self.query_builder = query_builder or RagQueryBuilder()
        self.relevance_gate = relevance_gate or RagRelevanceGate()
        self.segmenter = RagSegmenter()

    def _inject_relationship_policy(
        self,
        context: dict[str, Any],
        *,
        account_wxid: str,
        conversation_id: int,
        remote_model: bool,
        redaction_disabled: bool,
    ) -> int | None:
        """P1.3 分槽注入：关系策略独立于检索结果，不占事实预算。

        数据源是 P1.1 影子表（默认无数据→零行为变化）；远程模型发送前
        对文本字段脱敏；sensitivity 行深度防御跳过。返回 state_id 供
        检索日志 policy_ids 记录，无注入返回 None。

        P1.5 护栏：注入前提为注入开关与影子开关同时开启（设置页只写
        shadow 开关，关掉即全链路停用，历史策略行不再注入）；影子行
        置信度低于下限不注入（留在影子层观察）。
        """
        settings = load_rag_settings()
        if not settings.get("rag_relationship_policy_injection_enabled", True):
            return None
        if not settings.get("rag_relationship_policy_shadow_enabled", False):
            return None
        try:
            state = self.store.get_latest_relationship_state(account_wxid, conversation_id)
        except Exception:
            return None
        if not state or str(state.get("sensitivity") or "normal") == "sensitive":
            return None
        if float(state.get("confidence") or 0.0) < self.RELATIONSHIP_POLICY_MIN_CONFIDENCE:
            logger.debug(
                "[RAG Policy] state=%s below confidence floor (%.2f < %.2f); keep shadow-only",
                state.get("id"),
                float(state.get("confidence") or 0.0),
                self.RELATIONSHIP_POLICY_MIN_CONFIDENCE,
            )
            return None

        policy = {
            "stage": state.get("stage") or "",
            "closeness_band": state.get("closeness_band") or "",
            "initiative_pattern": state.get("initiative_pattern") or "",
            "boundary_summary": state.get("boundary_summary") or "",
            "communication_tips": state.get("communication_tips") or "",
            "confidence": float(state.get("confidence") or 0.0),
            "policy_version": state.get("policy_version") or "",
            "state_id": int(state.get("id") or 0),
        }
        if remote_model and not redaction_disabled:
            try:
                redactor = PrivacyRedactor(self.store.conn)
                for field in ("boundary_summary", "communication_tips"):
                    if policy[field]:
                        policy[field] = redactor.redact(
                            policy[field],
                            account_wxid=account_wxid,
                            conversation_id=conversation_id,
                            source_table="rag_relationship_state",
                            source_id=str(policy["state_id"]),
                        ).redacted_text
            except Exception:
                # 脱敏失败时丢弃文本字段，保留结构化枚举（阶段/主动性）
                policy["boundary_summary"] = ""
                policy["communication_tips"] = ""

        if not any((policy["stage"], policy["boundary_summary"], policy["communication_tips"])):
            return None
        context["relationship_policy"] = policy
        return policy["state_id"]

    def _inject_contact_preferences(
        self,
        context: dict[str, Any],
        *,
        account_wxid: str,
        conversation_id: int,
        remote_model: bool,
        redaction_disabled: bool,
    ) -> list[int]:
        """P1.2 分槽注入：对方偏好/雷点速查，独立于检索与关系策略。

        数据源是槽位级影子表（默认无数据→零行为变化）；注入前提同
        T6 护栏（注入+影子开关同时开启）；低置信槽不注入；远程模型
        对摘要脱敏（失败丢弃该槽文本保留枚举）。返回注入的 pref_id
        列表供检索日志 contact_preference_ids 记录。
        """
        settings = load_rag_settings()
        if not settings.get("rag_relationship_policy_injection_enabled", True):
            return []
        if not settings.get("rag_relationship_policy_shadow_enabled", False):
            return []
        try:
            prefs = self.store.list_contact_preferences(account_wxid, conversation_id)
        except Exception:
            return []

        selected: list[dict[str, Any]] = []
        for row in prefs:
            if len(selected) >= self.CONTACT_PREFERENCE_MAX_ITEMS:
                break
            if str(row.get("sensitivity") or "normal") == "sensitive":
                continue
            if float(row.get("confidence") or 0.0) < self.CONTACT_PREFERENCE_MIN_CONFIDENCE:
                continue
            summary = str(row.get("summary") or "").strip()
            if not summary:
                continue
            selected.append(
                {
                    "pref_id": int(row.get("id") or 0),
                    "slot_kind": str(row.get("slot_kind") or "preference"),
                    "summary": summary,
                    "confidence": float(row.get("confidence") or 0.0),
                    "support_count": int(row.get("support_count") or 1),
                    "policy_version": str(row.get("policy_version") or ""),
                }
            )
        if not selected:
            return []

        if remote_model and not redaction_disabled:
            try:
                redactor = PrivacyRedactor(self.store.conn)
                for pref in selected:
                    if pref["summary"]:
                        pref["summary"] = redactor.redact(
                            pref["summary"],
                            account_wxid=account_wxid,
                            conversation_id=conversation_id,
                            source_table="rag_contact_preferences",
                            source_id=str(pref["pref_id"]),
                        ).redacted_text
            except Exception:
                # 脱敏失败丢弃文本，保留槽位枚举（偏好/雷点类型）
                for pref in selected:
                    pref["summary"] = ""

        usable = [pref for pref in selected if pref["summary"]]
        if not usable:
            return []
        context["contact_preferences"] = usable
        return [pref["pref_id"] for pref in usable]

    def enrich_context(
        self,
        context: dict[str, Any],
        *,
        trigger_type: str,
        intent: str,
        model_config: dict[str, Any] | None = None,
    ) -> None:
        memory_intent = self._resolve_memory_intent(context)
        context["memory_intent"] = memory_intent.to_dict()
        logger.debug(
            '[RAG Intent] mode=%s confidence=%.2f query="%s" reason=%s',
            memory_intent.mode,
            memory_intent.confidence,
            memory_intent.query,
            memory_intent.reason,
        )

        settings = load_rag_settings()
        rag_enabled = bool(settings.get("rag_enabled"))
        if not settings.get("rag_enabled"):
            logger.debug(
                "[RAG Skip] reason=rag_disabled memory_mode=%s confidence=%.2f",
                memory_intent.mode,
                memory_intent.confidence,
            )
            context.pop("retrieval_context", None)
            self._set_debug_state(
                context,
                memory_intent=memory_intent,
                rag_enabled=False,
                rag_retrieved=False,
                hit_count=0,
                injection_mode="none",
                no_hit_guard=False,
                degraded_reason="rag_disabled",
                latency_ms=0,
            )
            return

        account_wxid = str(context.get("account_wxid") or "").strip()
        conversation_id = self._resolve_conversation_id(context, account_wxid)
        if not account_wxid or not conversation_id:
            logger.debug(
                "[RAG Skip] reason=missing_scope account_wxid_present=%s "
                "conversation_id=%s display_name_present=%s memory_mode=%s confidence=%.2f",
                bool(account_wxid),
                conversation_id,
                bool(str(context.get("display_name") or "").strip()),
                memory_intent.mode,
                memory_intent.confidence,
            )
            self._set_debug_state(
                context,
                memory_intent=memory_intent,
                rag_enabled=rag_enabled,
                rag_retrieved=False,
                hit_count=0,
                injection_mode="none",
                no_hit_guard=False,
                degraded_reason="missing_scope",
                latency_ms=0,
            )
            return

        injection_mode = self._resolve_injection_mode(context)
        remote_model = is_remote_llm_model(model_config)
        started = time.perf_counter()
        deadline = started + 0.8
        query = self.query_builder.build(
            context,
            trigger_type=trigger_type,
            intent=intent,
            memory_intent=memory_intent,
        ) or memory_intent.query or self.retriever.build_query(context, trigger_type, intent)
        expanded_terms = self.query_builder.expanded_terms(context, memory_intent=memory_intent)
        context["_rag_query_expanded_terms"] = expanded_terms
        logger.debug(
            "[RAG Query] mode=%s expanded_terms=%s",
            memory_intent.mode,
            expanded_terms,
        )
        hot_items = self._build_hot_context_items(
            context,
            account_wxid=account_wxid,
            conversation_id=conversation_id,
            query=query,
            expanded_terms=expanded_terms,
        )
        logger.debug(
            "[RAG] attempt enabled=%s scope=contact query_len=%s",
            rag_enabled,
            len(query),
        )
        if self._budget_exhausted(deadline):
            self._log_skip(
                context,
                account_wxid=account_wxid,
                conversation_id=conversation_id,
                query=query,
                started=started,
                index_status=None,
                remote_model=remote_model,
                reason="timeout",
                timed_out=True,
                trigger_type=trigger_type,
                memory_intent=memory_intent,
                rag_enabled=rag_enabled,
                injection_mode="none",
                gate_decision=RagGateDecision("skip", "timeout"),
            )
            return

        index_status = self.indexer.ensure_contact_index(
            account_wxid=account_wxid,
            conversation_id=conversation_id,
        )
        status_name = (index_status or {}).get("status")
        document_count = int((index_status or {}).get("document_count") or 0)
        logger.debug(
            "[RAG] context build: account=%s conversation=%s status=%s docs=%s",
            account_wxid,
            conversation_id,
            status_name,
            document_count,
        )
        if self._budget_exhausted(deadline):
            self._log_skip(
                context,
                account_wxid=account_wxid,
                conversation_id=conversation_id,
                query=query,
                started=started,
                index_status=status_name,
                remote_model=remote_model,
                reason="timeout",
                timed_out=True,
                trigger_type=trigger_type,
                memory_intent=memory_intent,
                rag_enabled=rag_enabled,
                injection_mode="none",
            )
            return
        if status_name in {"pending", "indexing"} and document_count <= 0 and not hot_items:
            self._log_skip(
                context,
                account_wxid=account_wxid,
                conversation_id=conversation_id,
                query=query,
                started=started,
                index_status=status_name,
                remote_model=remote_model,
                reason="index_not_ready",
                trigger_type=trigger_type,
                memory_intent=memory_intent,
                rag_enabled=rag_enabled,
                injection_mode="none",
            )
            return
        if status_name == "failed" and not hot_items:
            self._log_skip(
                context,
                account_wxid=account_wxid,
                conversation_id=conversation_id,
                query=query,
                started=started,
                index_status=status_name,
                remote_model=remote_model,
                reason="index_failed",
                trigger_type=trigger_type,
                memory_intent=memory_intent,
                rag_enabled=rag_enabled,
                injection_mode="none",
            )
            return

        if status_name in {"pending", "indexing", "failed"} and hot_items:
            result = {
                "items": hot_items,
                "strategy": "hot_context",
                "status": index_status,
                "timed_out": False,
                "degraded": status_name != "ready",
                "degrade_reason": "hot_context_only",
                "elapsed_ms": int((time.perf_counter() - started) * 1000),
                "by_type": {"hot_context": len(hot_items)},
            }
        else:
            remaining_ms = max(1, int((deadline - time.perf_counter()) * 1000))
            result = self.retriever.retrieve(
                account_wxid=account_wxid,
                conversation_id=conversation_id,
                query=query,
                timeout_ms=remaining_ms,
                deadline=deadline,
            )
            if hot_items:
                result["items"] = sorted(
                    hot_items + list(result.get("items") or []),
                    key=lambda item: float(item.get("score") or 0.0),
                    reverse=True,
                )
                by_type = dict(result.get("by_type") or {})
                by_type["hot_context"] = by_type.get("hot_context", 0) + len(hot_items)
                result["by_type"] = by_type
        logger.debug(
            "[RAG] retrieved hit_count=%s top_score=%.4f strategy=%s latency=%sms",
            len(result.get("items") or []),
            self._top_score(result.get("items") or []),
            result.get("strategy"),
            result.get("elapsed_ms"),
        )
        result["items"] = self._rerank_candidates_for_task(
            result.get("items") or [],
            query=query,
            context=context,
            memory_intent=memory_intent,
            injection_mode=injection_mode,
        )
        rerank_debug = context.get("_rag_rerank_debug") or {}
        logger.debug(
            "[RAG] retrieval result: conversation=%s strategy=%s items=%s degraded=%s reason=%s elapsed=%sms",
            conversation_id,
            result.get("strategy"),
            len(result.get("items") or []),
            result.get("degraded"),
            result.get("degrade_reason"),
            result.get("elapsed_ms"),
        )
        logger.debug(
            "[RAG Retrieve] candidates=%s by_type=%s top_score=%.4f strategy=%s task_top=%.4f off_topic=%s",
            len(result.get("items") or []),
            result.get("by_type") or {},
            self._top_score(result.get("items") or []),
            result.get("strategy"),
            float(rerank_debug.get("task_relevance_score") or 0.0),
            int(rerank_debug.get("off_topic_rejected_count") or 0),
        )
        gate_decision = self.relevance_gate.decide(
            query=query,
            items=result.get("items") or [],
            strategy=result.get("strategy"),
            output_mode=injection_mode,
            trigger_type=trigger_type,
            recent_messages=context.get("recent_messages") or [],
            user_context=context.get("user_context"),
            memory_intent=memory_intent.to_dict(),
            timed_out=bool(result.get("timed_out")),
            degraded_reason=result.get("degrade_reason"),
            previous_rag_hit=self._previous_rag_hit(context),
        )
        logger.debug(
            "[RAG Gate] decision=%s reason=%s top_score=%.4f no_hit_eligible=%s",
            gate_decision.decision,
            gate_decision.reason,
            gate_decision.top_score,
            gate_decision.no_hit_eligible,
        )
        selected_scored_items = self._select_gate_items(result.get("items") or [], gate_decision)
        logger.debug(
            "[RAG Rank] selected=%s doc_types=%s",
            len(selected_scored_items),
            [str((item.get("doc") or {}).get("doc_type") or "") for item in selected_scored_items],
        )

        redaction_disabled = bool(remote_model and not settings.get("rag_remote_context_redaction"))
        redaction_fallback = False
        redaction_status = "raw_local" if not remote_model else "redacted"
        if redaction_disabled:
            redaction_status = "disabled"

        try:
            if self._budget_exhausted(deadline):
                raise TimeoutError("rag budget exhausted before minimization")
            items = self._minimize_items(
                selected_scored_items,
                use_redacted=remote_model and not redaction_disabled,
            )
        except TimeoutError:
            items = []
            result["timed_out"] = True
            result["degraded"] = True
            result["degrade_reason"] = "timeout"
        except Exception:
            items = []
            result["degraded"] = True
            result["degrade_reason"] = "compression_failed"

        if remote_model and not redaction_disabled and items:
            try:
                if self._budget_exhausted(deadline):
                    raise TimeoutError("rag budget exhausted before redaction")
                redactor = PrivacyRedactor(self.store.conn)
                for item in items:
                    if item.get("sensitivity") == "sensitive":
                        continue
                    item["content"] = redactor.redact(
                        item.get("content") or "",
                        account_wxid=account_wxid,
                        conversation_id=conversation_id,
                        source_table="rag_context",
                        source_id=str(item.get("document_id") or ""),
                    ).redacted_text
            except TimeoutError:
                items = []
                result["timed_out"] = True
                result["degraded"] = True
                result["degrade_reason"] = "timeout"
            except Exception:
                redaction_fallback = True
                redaction_status = "strong_mask"
                try:
                    redactor = PrivacyRedactor(self.store.conn)
                    safe_items = []
                    for item in items:
                        if item.get("sensitivity") == "sensitive":
                            continue
                        item["content"] = redactor.strong_mask(item.get("content") or "")
                        safe_items.append(item)
                    items = safe_items
                except Exception:
                    items = []
                    result["degraded"] = True
                    result["degrade_reason"] = "redaction_failed"
                    redaction_status = "blocked"

        elapsed_ms = max(int((time.perf_counter() - started) * 1000), int(result.get("elapsed_ms") or 0))
        if elapsed_ms > 800:
            items = []
            result["timed_out"] = True
            result["degraded"] = True
            result["degrade_reason"] = "timeout"

        rag_retrieved = not bool(result.get("timed_out"))
        retrieved_hit_count = len(result.get("items") or [])
        hit_count = len(items)
        degrade_reason = str(result.get("degrade_reason") or "")
        no_hit_guard = bool(rag_retrieved and gate_decision.decision == "no_hit")
        if gate_decision.decision in {"inject", "weak_inject"} and not items:
            effective_gate_decision = RagGateDecision(
                "skip",
                result.get("degrade_reason") or "context_build_empty",
                gate_decision.top_score,
                gate_decision.no_hit_eligible,
                gate_decision.allowed_doc_types,
            )
        else:
            effective_gate_decision = gate_decision
        effective_injection_mode = injection_mode if (items or no_hit_guard) else "none"
        prompt_query = self._safe_query_for_prompt(
            query,
            remote_model=remote_model,
            redaction_disabled=redaction_disabled,
        )

        candidate_items = result.get("items") or []
        injected_ids = [item.get("document_id") for item in items]
        hot_context_only = bool(items) and (
            str(result.get("strategy") or "") == "hot_context"
            or all(str(item.get("doc_type") or "") == "hot_context" for item in items)
        )
        prompt_context_hash = None
        if items:
            digest = hashlib.sha256()
            for item in items:
                digest.update(str(item.get("document_id") or "").encode("utf-8", "ignore"))
                digest.update(b"\x1f")
                digest.update(str(item.get("doc_type") or "").encode("utf-8", "ignore"))
                digest.update(b"\x1f")
                digest.update(str(item.get("content") or "").encode("utf-8", "ignore"))
                digest.update(b"\x1e")
            prompt_context_hash = digest.hexdigest()

        relationship_policy_state_id = self._inject_relationship_policy(
            context,
            account_wxid=account_wxid,
            conversation_id=conversation_id,
            remote_model=remote_model,
            redaction_disabled=redaction_disabled,
        )
        contact_preference_ids = self._inject_contact_preferences(
            context,
            account_wxid=account_wxid,
            conversation_id=conversation_id,
            remote_model=remote_model,
            redaction_disabled=redaction_disabled,
        )

        log_id = self.store.insert_retrieval_log(
            account_wxid=account_wxid,
            conversation_id=conversation_id,
            query_text=self._safe_query_for_log(query),
            document_ids=[item["document_id"] for item in items],
            retrieval_scores={
                str(item["document_id"]): item.get("score")
                for item in items
            },
            index_status=(index_status or {}).get("status"),
            elapsed_ms=elapsed_ms,
            timed_out=bool(result.get("timed_out")),
            degraded=bool(result.get("degraded")),
            degrade_reason=result.get("degrade_reason"),
            redaction_status=redaction_status,
            redaction_disabled=redaction_disabled,
            redaction_fallback=redaction_fallback,
            remote_model=remote_model,
            memory_intent_mode=memory_intent.mode,
            memory_intent_confidence=memory_intent.confidence,
            memory_intent_query=self._safe_query_for_log(memory_intent.query),
            memory_intent_reason=memory_intent.reason,
            rag_enabled=rag_enabled,
            rag_retrieved=rag_retrieved,
            rag_hit_count=retrieved_hit_count,
            rag_injection_mode=effective_injection_mode,
            rag_no_hit_guard=no_hit_guard,
            rag_latency_ms=elapsed_ms,
            rag_degraded_reason=result.get("degrade_reason"),
            rag_gate_decision=effective_gate_decision.decision,
            rag_gate_reason=effective_gate_decision.reason,
            rag_top_score=effective_gate_decision.top_score,
            rag_strategy=result.get("strategy"),
            index_version=RAG_INDEX_VERSION,
            selected_doc_types=[
                str(item.get("doc_type") or "")
                for item in items
                if item.get("doc_type")
            ],
            top_doc_time_label=items[0].get("time_label") if items else None,
            query_expanded_terms=expanded_terms,
            no_hit_reason=effective_gate_decision.reason if no_hit_guard else None,
            task_relevance_score=effective_gate_decision.task_relevance_score,
            off_topic_rejected_count=effective_gate_decision.off_topic_rejected_count,
            semantic_fact_count=self._semantic_fact_count(result.get("items") or []),
            style_sample_count=self._style_sample_count(result.get("items") or []),
            rerank_reason=effective_gate_decision.rerank_reason or rerank_debug.get("rerank_reason"),
            retrieval_source="fact" if result.get("strategy") == "facts" else "document",
            fact_ids=[
                item.get("document_id")
                for item in items
                if str(item.get("doc_type") or "") == "fact_memory"
            ],
            evidence_ids=[
                evidence_id
                for item in items
                if str(item.get("doc_type") or "") == "fact_memory"
                for evidence_id in (item.get("evidence_message_ids") or [])
            ],
            query_scope=str(load_rag_settings().get("rag_query_scope") or "latest_turn"),
            supersession_decision=None,
            run_provenance=context.get("_rag_run_provenance") or "production",
            candidate_ids=[
                item.get("document_id")
                for item in candidate_items
                if item.get("document_id") is not None
            ],
            injected_item_ids=[
                item_id for item_id in injected_ids if item_id is not None
            ],
            hot_context_only=hot_context_only,
            prompt_context_hash=prompt_context_hash,
            policy_ids=[relationship_policy_state_id] if relationship_policy_state_id else [],
            contact_preference_ids=contact_preference_ids,
            trigger_type=trigger_type,
        )
        self.store.conn.commit()
        context["_rag_log_id"] = log_id
        context["_rag_conversation_id"] = conversation_id
        logger.debug(
            "[RAG] retrieved hit_count=%s latency=%sms degraded=%s reason=%s",
            hit_count,
            elapsed_ms,
            bool(result.get("degraded")),
            result.get("degrade_reason"),
        )
        if items:
            logger.debug(
                "[RAG Inject] status=hit mode=%s no_hit_guard=false conversation=%s docs=%s redaction=%s elapsed=%sms",
                injection_mode,
                conversation_id,
                [item.get("document_id") for item in items],
                redaction_status,
                elapsed_ms,
            )
            context["retrieval_context"] = {
                "account_wxid": account_wxid,
                "conversation_id": conversation_id,
                "items": items,
                "retrieval_status": "weak_hit" if effective_gate_decision.decision == "weak_inject" else "hit",
                "query": prompt_query,
                "memory_intent": memory_intent.to_dict(),
                "injection_mode": injection_mode,
                "hit_count": hit_count,
                "no_hit_guard": False,
                "gate_decision": effective_gate_decision.decision,
                "gate_reason": effective_gate_decision.reason,
                "top_score": effective_gate_decision.top_score,
                "task_relevance_score": effective_gate_decision.task_relevance_score,
                "strategy": result.get("strategy"),
                "index_status": (index_status or {}).get("status"),
                "elapsed_ms": elapsed_ms,
                "redaction_status": redaction_status,
                "redaction_disabled": redaction_disabled,
                "degraded": bool(result.get("degraded")),
                "degrade_reason": result.get("degrade_reason"),
            }
        elif no_hit_guard:
            logger.debug(
                "[RAG Inject] status=no_hit mode=%s no_hit_guard=true conversation=%s elapsed=%sms",
                injection_mode,
                conversation_id,
                elapsed_ms,
            )
            context["retrieval_context"] = {
                "account_wxid": account_wxid,
                "conversation_id": conversation_id,
                "items": [],
                "retrieval_status": "no_hit",
                "query": prompt_query,
                "memory_intent": memory_intent.to_dict(),
                "injection_mode": injection_mode,
                "hit_count": 0,
                "no_hit_guard": True,
                "gate_decision": effective_gate_decision.decision,
                "gate_reason": effective_gate_decision.reason,
                "top_score": effective_gate_decision.top_score,
                "task_relevance_score": effective_gate_decision.task_relevance_score,
                "strategy": result.get("strategy"),
                "index_status": (index_status or {}).get("status"),
                "elapsed_ms": elapsed_ms,
                "redaction_status": redaction_status,
                "redaction_disabled": redaction_disabled,
                "degraded": bool(result.get("degraded")),
                "degrade_reason": result.get("degrade_reason"),
            }
        else:
            logger.debug(
                "[RAG Inject] status=none mode=none reason=%s gate=%s gate_reason=%s "
                "candidates=%s selected=%s minimized=%s top_candidates=%s status=%s "
                "retrieval_reason=%s timed_out=%s elapsed=%sms",
                effective_gate_decision.reason,
                effective_gate_decision.decision,
                gate_decision.reason,
                len(result.get("items") or []),
                len(selected_scored_items),
                len(items),
                self._candidate_snapshot(result.get("items") or []),
                (index_status or {}).get("status"),
                result.get("degrade_reason"),
                bool(result.get("timed_out")),
                elapsed_ms,
            )
            logger.debug(
                "[RAG Inject] status=none mode=none no_hit_guard=false conversation=%s status=%s reason=%s timed_out=%s elapsed=%sms",
                conversation_id,
                (index_status or {}).get("status"),
                result.get("degrade_reason"),
                bool(result.get("timed_out")),
                elapsed_ms,
            )
            context.pop("retrieval_context", None)
        self._set_debug_state(
            context,
            memory_intent=memory_intent,
            rag_enabled=rag_enabled,
            rag_retrieved=rag_retrieved,
            hit_count=retrieved_hit_count,
            injection_mode=effective_injection_mode,
            no_hit_guard=no_hit_guard,
            degraded_reason=result.get("degrade_reason"),
            latency_ms=elapsed_ms,
            gate_decision=effective_gate_decision,
            strategy=result.get("strategy"),
            task_relevance_score=effective_gate_decision.task_relevance_score,
            off_topic_rejected_count=effective_gate_decision.off_topic_rejected_count,
            semantic_fact_count=self._semantic_fact_count(result.get("items") or []),
            style_sample_count=self._style_sample_count(result.get("items") or []),
            rerank_reason=effective_gate_decision.rerank_reason or rerank_debug.get("rerank_reason"),
            hot_context_only=hot_context_only,
            run_provenance=context.get("_rag_run_provenance") or "production",
        )
        if relationship_policy_state_id:
            context["_rag_debug"]["relationship_policy_injected"] = True
        if contact_preference_ids:
            context["_rag_debug"]["contact_preference_injected"] = True
            context["_rag_debug"]["contact_preference_ids"] = contact_preference_ids

    def attach_log_to_suggestion(self, log_id: int | None, suggestion_id: int) -> None:
        self.store.attach_log_to_suggestion(log_id, suggestion_id)
        self.store.conn.commit()

    def _build_hot_context_items(
        self,
        context: dict[str, Any],
        *,
        account_wxid: str,
        conversation_id: int,
        query: str,
        expanded_terms: list[str],
    ) -> list[dict[str, Any]]:
        messages = self._collect_hot_messages(
            context,
            account_wxid=account_wxid,
            conversation_id=conversation_id,
        )
        # A manual lookup question is often present in the same realtime
        # buffer as the conversation.  It is not evidence for itself: without
        # at least one actual counterparty turn, a hot context would merely
        # echo "我：我们一起玩过什么游戏" back into the prompt and be displayed
        # as a false historical hit while the index is still pending.
        if not messages or not any(not int(msg.get("is_sender") or 0) for msg in messages):
            return []
        rendered = []
        source_ts = 0
        message_ids: list[int] = []
        for msg in messages[-20:]:
            sender = "我" if int(msg.get("is_sender") or 0) else "对方"
            content = re.sub(r"\s+", " ", str(msg.get("content") or "")).strip()
            if not content:
                continue
            rendered.append(f"{sender}: {content[:160]}")
            try:
                source_ts = max(source_ts, int(msg.get("timestamp") or 0))
            except (TypeError, ValueError):
                pass
            try:
                if int(msg.get("id") or 0):
                    message_ids.append(int(msg.get("id") or 0))
            except (TypeError, ValueError):
                pass
        if not rendered:
            return []
        content = f"时间：{self.segmenter.time_label(source_ts or int(time.time()))}\n" + "\n".join(rendered)
        score = max(0.25, self._hot_context_score(query, content, expanded_terms))
        doc = {
            "id": -1,
            "doc_type": "hot_context",
            "content": content,
            "redacted_content": content,
            "source_ts": source_ts or int(time.time()),
            "sensitivity": "normal",
            "enabled": 1,
            "metadata_json": self._json_dumps(
                {
                    "source_kind": "realtime",
                    "index_version": RAG_INDEX_VERSION,
                    "time_label": self.segmenter.time_label(source_ts or int(time.time())),
                    "message_ids": message_ids,
                    "topics": self.segmenter.extract_topics(content),
                    "entities": self.segmenter.extract_entities(content),
                }
            ),
        }
        return [{"doc": doc, "score": round(score, 4)}]

    def _collect_hot_messages(
        self,
        context: dict[str, Any],
        *,
        account_wxid: str,
        conversation_id: int,
    ) -> list[dict[str, Any]]:
        messages: list[dict[str, Any]] = []
        for msg in context.get("recent_messages") or []:
            if not isinstance(msg, dict):
                continue
            item = self._normalize_hot_message(msg)
            if item and self._is_hot_context_message(item):
                messages.append(item)

        try:
            display_name = str(context.get("display_name") or "").strip()
            batch_id = str(context.get("batch_id") or context.get("current_batch_id") or "").strip()
            if not batch_id and not display_name:
                raise ValueError("missing realtime buffer scope")
            params: list[Any] = [account_wxid]
            where = ["account_wxid = ?", "message_type = 'text'", "content IS NOT NULL", "TRIM(content) != ''"]
            min_ts = int(time.time()) - self.HOT_CONTEXT_MAX_AGE_SECONDS
            where.append("timestamp >= ?")
            params.append(min_ts)
            if batch_id:
                where.append("batch_id = ?")
                params.append(batch_id)
            elif display_name:
                where.append("(talker_display_name = ? OR talker_username = ?)")
                params.extend([display_name, display_name])
            rows = self.store.conn.execute(
                f"""
                SELECT id, sender_attr, content, timestamp, talker_display_name, talker_username
                FROM realtime_message_buffer
                WHERE {' AND '.join(where)}
                ORDER BY timestamp DESC, id DESC
                LIMIT 30
                """,
                tuple(params),
            ).fetchall()
            for row in rows:
                item = self._normalize_hot_message(dict(row))
                if item and self._is_hot_context_message(item):
                    messages.append(item)
        except Exception:
            pass

        deduped: list[dict[str, Any]] = []
        seen = set()
        for msg in sorted(messages, key=lambda item: (int(item.get("timestamp") or 0), int(item.get("id") or 0))):
            key = (msg.get("timestamp"), msg.get("is_sender"), msg.get("content"))
            if key in seen:
                continue
            seen.add(key)
            deduped.append(msg)
        return deduped[-30:]

    def _normalize_hot_message(self, msg: dict[str, Any]) -> dict[str, Any] | None:
        content = re.sub(r"\s+", " ", str(msg.get("content") or "")).strip()
        if not content:
            return None
        sender_attr = str(msg.get("sender_attr") or "").lower()
        is_sender = 1 if sender_attr == "self" or msg.get("is_sender") == 1 else 0
        # Never manufacture a timestamp for an un-timestamped legacy row.
        # Doing so makes an old message look like live context, letting it
        # bypass the one-day hot-context limit and masquerade as a RAG hit.
        raw_timestamp = msg.get("timestamp") or msg.get("created_at")
        try:
            timestamp = int(raw_timestamp)
        except (TypeError, ValueError):
            return None
        if timestamp <= 0:
            return None
        try:
            message_id = int(msg.get("id") or 0)
        except (TypeError, ValueError):
            message_id = 0
        return {
            "id": message_id,
            "is_sender": is_sender,
            "content": content,
            "timestamp": timestamp,
        }

    def _is_hot_context_message(self, msg: dict[str, Any]) -> bool:
        try:
            timestamp = int(msg.get("timestamp") or 0)
        except (TypeError, ValueError):
            return False
        if timestamp <= 0:
            return False
        return (time.time() - timestamp) <= self.HOT_CONTEXT_MAX_AGE_SECONDS

    def _hot_context_score(self, query: str, content: str, expanded_terms: list[str]) -> float:
        query_tokens = set(self.segmenter.extract_topics(query) + expanded_terms)
        content_tokens = set(self.segmenter.extract_topics(content))
        if not query_tokens or not content_tokens:
            return 0.25
        overlap = len(query_tokens & content_tokens) / max(1, min(len(query_tokens), len(content_tokens)))
        return 0.35 + overlap * 0.55

    def _json_dumps(self, data: dict[str, Any]) -> str:
        import json

        return json.dumps(data, ensure_ascii=False, sort_keys=True)

    def _resolve_conversation_id(self, context: dict[str, Any], account_wxid: str) -> int | None:
        raw = context.get("conversation_id") or context.get("_rag_conversation_id")
        try:
            if raw:
                return int(raw)
        except (TypeError, ValueError):
            pass
        display_name = str(context.get("display_name") or "").strip()
        if not display_name:
            recent = context.get("recent_messages") or []
            if recent:
                display_name = str(recent[-1].get("talker_display_name") or recent[-1].get("talker_username") or "").strip()
        if not display_name:
            return None
        row = get_db().execute(
            """
            SELECT id
            FROM conversations
            WHERE account_wxid = ?
              AND (display_name = ? OR username = ?)
              AND is_deleted = 0
            ORDER BY updated_at DESC
            LIMIT 1
            """,
            (account_wxid, display_name, display_name),
        ).fetchone()
        return int(row["id"]) if row else None

    def _minimize_items(self, items: list[dict[str, Any]], *, use_redacted: bool) -> list[dict[str, Any]]:
        import json

        minimized = []
        total_chars = 0
        fact_mode = any(
            str((scored.get("doc") or {}).get("doc_type") or "") == "fact_memory"
            for scored in items
        )
        context_budget = 1600 if fact_mode else self.MAX_CONTEXT_CHARS
        item_limit = 8 if fact_mode else len(items)
        for scored in items:
            if len(minimized) >= item_limit:
                break
            doc = scored.get("doc") or {}
            # 脱敏字段只在确实生成了内容时才覆盖原文。历史索引中的部分
            # fact_memory 没有 redacted_content；此前在 redaction=redacted 时会
            # 将这些有效事实错误地渲染成 "None"，导致 UI 显示命中而模型拿到空证据。
            preferred_content = doc.get("redacted_content") if use_redacted else doc.get("content")
            content = str(preferred_content or doc.get("content") or "").strip()
            content = re.sub(r"\s+", " ", content)
            if not content:
                continue
            is_fact = str(doc.get("doc_type") or "") == "fact_memory"
            # StructuredFactExtractor caps facts at 500 chars. If legacy data
            # violates that contract, drop the item instead of cutting a fact
            # through the middle of a sentence.
            if fact_mode and is_fact and len(content) > 500:
                continue
            remaining = context_budget - total_chars
            if remaining <= 0:
                break
            if not (fact_mode and is_fact):
                content = content[: min(160, remaining)]
            elif len(content) > remaining:
                continue
            try:
                metadata = json.loads(doc.get("metadata_json") or "{}")
            except Exception:
                metadata = {}
            item = {
                "document_id": int(doc["id"]),
                "doc_type": doc.get("doc_type"),
                "content": content,
                "score": scored.get("score"),
                "task_relevance_score": scored.get("task_relevance_score"),
                "source_ts": doc.get("source_ts"),
                "as_of": scored.get("as_of") or doc.get("source_ts"),
                "time_label": metadata.get("time_label")
                or self.segmenter.time_label(int(doc.get("source_ts") or time.time())),
                "topics": metadata.get("topics") or [],
                "entities": metadata.get("entities") or [],
                "sensitivity": doc.get("sensitivity") or "normal",
            }
            if str(doc.get("doc_type") or "") == "fact_memory":
                item.update(
                    {
                        "fact_status": scored.get("fact_status") or "active",
                        "fact_confidence": float(scored.get("fact_confidence") or 0.0),
                        "evidence_message_ids": scored.get("evidence_message_ids") or metadata.get("evidence_message_ids") or [],
                        "subject": scored.get("subject") or metadata.get("subject") or "",
                        "memory_kind": scored.get("memory_kind") or metadata.get("memory_kind") or "",
                    }
                )
            minimized.append(item)
            total_chars += len(content)
        return minimized

    def _rerank_candidates_for_task(
        self,
        items: list[dict[str, Any]],
        *,
        query: str,
        context: dict[str, Any],
        memory_intent: MemoryIntent,
        injection_mode: str,
    ) -> list[dict[str, Any]]:
        recent_text = self._recent_task_text(context)
        query_tokens = set(self.segmenter.extract_topics(query))
        recent_tokens = set(self.segmenter.extract_topics(recent_text))
        output: list[dict[str, Any]] = []
        off_topic_count = 0
        for item in items:
            doc = item.get("doc") or {}
            doc_type = str(doc.get("doc_type") or "")
            content = str(doc.get("content") or doc.get("redacted_content") or "")
            metadata = self._metadata(doc)
            doc_tokens = set(
                self.segmenter.extract_topics(
                    " ".join(
                        [
                            content,
                            " ".join(str(value) for value in metadata.get("topics") or []),
                            " ".join(str(value) for value in metadata.get("entities") or []),
                        ]
                    )
                )
            )
            lexical_score = self._overlap_score(query_tokens, doc_tokens)
            recent_overlap = self._overlap_score(recent_tokens, doc_tokens)
            vector_score = float(item.get("vector_score") or 0.0)
            keyword_score = float(item.get("keyword_score") or 0.0)
            if doc_type == "hot_context":
                task_score = max(float(item.get("score") or 0.0), 0.80)
                reason = "hot_context"
            elif doc_type in {"self_style_example", "communication_style"}:
                task_score = max(vector_score * 0.75, keyword_score, lexical_score, 0.35)
                reason = "style_context"
            else:
                task_score = max(vector_score * 0.90, keyword_score, lexical_score)
                reason = "semantic_rerank" if vector_score else "keyword_rerank"
                if memory_intent.mode == "memory_request" and (keyword_score > 0 or lexical_score > 0):
                    task_score = max(task_score, 0.50)
                    reason = "memory_request_anchor"

            off_topic = False
            if (
                injection_mode == "suggestion"
                and memory_intent.mode not in {"memory_request", "relationship_context"}
                and doc_type not in {"hot_context", "fact_memory", "self_style_example", "communication_style"}
                and recent_tokens
                and recent_overlap <= 0.0
                and task_score < 0.68
            ):
                off_topic = True
                reason = "off_topic"
                off_topic_count += 1

            enriched = dict(item)
            enriched["task_relevance_score"] = round(float(task_score), 4)
            enriched["recent_topic_overlap"] = round(float(recent_overlap), 4)
            enriched["off_topic_memory"] = off_topic
            enriched["rerank_reason"] = reason
            output.append(enriched)

        output.sort(
            key=lambda item: (
                bool(item.get("off_topic_memory")),
                -(float(item.get("task_relevance_score") or 0.0) * 0.55 + float(item.get("score") or 0.0) * 0.45),
            )
        )
        context["_rag_rerank_debug"] = {
            "task_relevance_score": max((float(item.get("task_relevance_score") or 0.0) for item in output), default=0.0),
            "off_topic_rejected_count": off_topic_count,
            "rerank_reason": output[0].get("rerank_reason") if output else "no_candidates",
        }
        return output

    def _recent_task_text(self, context: dict[str, Any]) -> str:
        parts: list[str] = []
        latest = self.query_builder._latest_user_input(context)
        if latest:
            parts.append(latest)
        recent = context.get("recent_messages") or []
        if isinstance(recent, list):
            for msg in recent[-4:]:
                if isinstance(msg, dict):
                    content = str(msg.get("content") or "").strip()
                    if content:
                        parts.append(content)
        return "\n".join(parts)

    def _overlap_score(self, left: set[str], right: set[str]) -> float:
        if not left or not right:
            return 0.0
        return len(left & right) / max(1, min(len(left), len(right)))

    def _metadata(self, doc: dict[str, Any]) -> dict[str, Any]:
        try:
            return json.loads(doc.get("metadata_json") or "{}")
        except Exception:
            return {}

    def _semantic_fact_count(self, items: list[dict[str, Any]]) -> int:
        count = 0
        for item in items:
            doc = item.get("doc") or item
            if str(doc.get("doc_type") or item.get("doc_type") or "") != "fact_memory":
                continue
            metadata = self._metadata(doc)
            if metadata.get("memory_kind") and metadata.get("memory_kind") != "marker_fallback":
                count += 1
        return count

    def _style_sample_count(self, items: list[dict[str, Any]]) -> int:
        return sum(
            1
            for item in items
            if str((item.get("doc") or item).get("doc_type") or "") in {"self_style_example", "communication_style"}
        )

    def _select_gate_items(
        self,
        items: list[dict[str, Any]],
        gate_decision: RagGateDecision,
    ) -> list[dict[str, Any]]:
        if gate_decision.decision == "skip":
            return []
        if gate_decision.decision == "no_hit":
            return []
        selected = [item for item in items if item.get("_rag_gate_selected")]
        if selected:
            return selected[:4]
        if gate_decision.decision == "weak_inject":
            allowed = set(gate_decision.allowed_doc_types or ())
            return [
                item
                for item in items
                if str((item.get("doc") or {}).get("doc_type") or "") in allowed
                and not item.get("off_topic_memory")
            ]
        allowed = set(gate_decision.allowed_doc_types or ())
        if allowed:
            return [
                item
                for item in items
                if str((item.get("doc") or {}).get("doc_type") or "") in allowed
                and not item.get("off_topic_memory")
            ][:4]
        return [item for item in items if not item.get("off_topic_memory")][:4]

    def _top_score(self, items: list[dict[str, Any]]) -> float:
        if not items:
            return 0.0
        return round(float((items[0] or {}).get("score") or 0.0), 4)

    def _candidate_snapshot(self, items: list[dict[str, Any]], *, limit: int = 3) -> list[dict[str, Any]]:
        snapshot = []
        for item in (items or [])[:limit]:
            doc = item.get("doc") or {}
            metadata: dict[str, Any] = {}
            try:
                metadata = json.loads(doc.get("metadata_json") or "{}")
            except Exception:
                metadata = {}
            snapshot.append(
                {
                    "id": doc.get("id"),
                    "type": doc.get("doc_type"),
                    "score": round(float(item.get("score") or 0.0), 4),
                    "time": metadata.get("time_label")
                    or self.segmenter.time_label(int(doc.get("source_ts") or time.time())),
                }
            )
        return snapshot

    def _previous_rag_hit(self, context: dict[str, Any]) -> bool:
        debug = context.get("_rag_debug")
        if isinstance(debug, dict) and debug.get("rag_injection_mode") in {"reply", "suggestion"}:
            return True
        for item in reversed(context.get("memory_intent_history") or []):
            if isinstance(item, dict) and item.get("rag_gate_decision") in {"inject", "weak_inject"}:
                return True
        return False

    def _safe_query_for_log(self, query: str) -> str:
        # Retrieval logs need traceability, not raw long chat history.
        text = re.sub(r"\s+", " ", str(query or "")).strip()
        try:
            return PrivacyRedactor(self.store.conn).strong_mask(text[:500])
        except Exception:
            return text[:120]

    def _safe_query_for_prompt(
        self,
        query: str,
        *,
        remote_model: bool,
        redaction_disabled: bool,
    ) -> str:
        text = re.sub(r"\s+", " ", str(query or "")).strip()
        if not remote_model or redaction_disabled:
            return text
        try:
            return PrivacyRedactor(self.store.conn).strong_mask(text[:500])
        except Exception:
            return ""

    def _budget_exhausted(self, deadline: float) -> bool:
        return time.perf_counter() > deadline

    def _resolve_memory_intent(self, context: dict[str, Any]) -> MemoryIntent:
        raw = context.get("memory_intent")
        if isinstance(raw, MemoryIntent):
            return raw
        if isinstance(raw, dict):
            try:
                return MemoryIntent(
                    bool(raw.get("should_retrieve")),
                    raw.get("mode") or "none",
                    float(raw.get("confidence") or 0.0),
                    str(raw.get("query") or ""),
                    str(raw.get("reason") or "provided"),
                )
            except Exception:
                return MemoryIntent.none("invalid_provided_memory_intent")
        return detect_memory_intent(context)

    def _resolve_injection_mode(self, context: dict[str, Any]) -> str:
        raw = str(context.get("_rag_output_mode") or context.get("rag_injection_mode") or "").strip()
        if raw in {"reply", "suggestion"}:
            return raw
        return "suggestion"

    def _set_debug_state(
        self,
        context: dict[str, Any],
        *,
        memory_intent: MemoryIntent,
        rag_enabled: bool,
        rag_retrieved: bool,
        hit_count: int,
        injection_mode: str,
        no_hit_guard: bool,
        degraded_reason: str | None,
        latency_ms: int,
        gate_decision: RagGateDecision | None = None,
        strategy: str | None = None,
        task_relevance_score: float = 0.0,
        off_topic_rejected_count: int = 0,
        semantic_fact_count: int = 0,
        style_sample_count: int = 0,
        rerank_reason: str | None = None,
        hot_context_only: bool = False,
        run_provenance: str | None = None,
    ) -> None:
        gate_decision = gate_decision or RagGateDecision("skip", degraded_reason or "not_attempted")
        task_score = task_relevance_score or gate_decision.task_relevance_score
        context["_rag_debug"] = {
            "memory_intent_mode": memory_intent.mode,
            "memory_intent_confidence": memory_intent.confidence,
            "memory_intent_query": memory_intent.query,
            "memory_intent_reason": memory_intent.reason,
            "rag_enabled": rag_enabled,
            "rag_retrieved": rag_retrieved,
            "rag_hit_count": int(hit_count),
            "rag_injection_mode": injection_mode,
            "rag_no_hit_guard": no_hit_guard,
            "rag_latency_ms": int(latency_ms),
            "rag_degraded_reason": degraded_reason,
            "rag_gate_decision": gate_decision.decision,
            "rag_gate_reason": gate_decision.reason,
            "rag_top_score": gate_decision.top_score,
            "rag_strategy": strategy,
            "task_relevance_score": task_score,
            "off_topic_rejected_count": off_topic_rejected_count or gate_decision.off_topic_rejected_count,
            "semantic_fact_count": semantic_fact_count,
            "style_sample_count": style_sample_count,
            "rerank_reason": rerank_reason or gate_decision.rerank_reason,
            "hot_context_only": bool(hot_context_only),
            "run_provenance": run_provenance or "production",
        }

    def _log_skip(
        self,
        context: dict[str, Any],
        *,
        account_wxid: str,
        conversation_id: int,
        query: str,
        started: float,
        index_status: str | None,
        remote_model: bool,
        reason: str,
        timed_out: bool = False,
        trigger_type: str | None = None,
        memory_intent: MemoryIntent | None = None,
        rag_enabled: bool = True,
        injection_mode: str = "none",
        gate_decision: RagGateDecision | None = None,
        strategy: str | None = None,
    ) -> None:
        memory_intent = memory_intent or MemoryIntent.none()
        gate_decision = gate_decision or RagGateDecision("skip", reason)
        settings = load_rag_settings()
        redaction_disabled = bool(remote_model and not settings.get("rag_remote_context_redaction"))
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        log_id = self.store.insert_retrieval_log(
            account_wxid=account_wxid,
            conversation_id=conversation_id,
            query_text=self._safe_query_for_log(query),
            document_ids=[],
            retrieval_scores={},
            index_status=index_status,
            elapsed_ms=elapsed_ms,
            timed_out=timed_out,
            degraded=True,
            degrade_reason=reason,
            redaction_status="disabled" if redaction_disabled else ("raw_local" if not remote_model else "redacted"),
            redaction_disabled=redaction_disabled,
            redaction_fallback=False,
            remote_model=remote_model,
            memory_intent_mode=memory_intent.mode,
            memory_intent_confidence=memory_intent.confidence,
            memory_intent_query=self._safe_query_for_log(memory_intent.query),
            memory_intent_reason=memory_intent.reason,
            rag_enabled=rag_enabled,
            rag_retrieved=False,
            rag_hit_count=0,
            rag_injection_mode=injection_mode,
            rag_no_hit_guard=False,
            rag_latency_ms=elapsed_ms,
            rag_degraded_reason=reason,
            rag_gate_decision=gate_decision.decision,
            rag_gate_reason=gate_decision.reason,
            rag_top_score=gate_decision.top_score,
            rag_strategy=strategy,
            index_version=RAG_INDEX_VERSION,
            selected_doc_types=[],
            query_expanded_terms=context.get("_rag_query_expanded_terms") or [],
            no_hit_reason=reason if gate_decision.decision == "no_hit" else None,
            task_relevance_score=gate_decision.task_relevance_score,
            off_topic_rejected_count=gate_decision.off_topic_rejected_count,
            semantic_fact_count=0,
            style_sample_count=0,
            rerank_reason=gate_decision.rerank_reason,
            retrieval_source="none",
            fact_ids=[],
            evidence_ids=[],
            query_scope=str(settings.get("rag_query_scope") or "latest_turn"),
            supersession_decision=None,
            run_provenance=context.get("_rag_run_provenance") or "production",
            trigger_type=trigger_type,
        )
        self.store.conn.commit()
        logger.debug(
            "[RAG Skip] conversation=%s status=%s reason=%s timed_out=%s",
            conversation_id,
            index_status,
            reason,
            timed_out,
        )
        context["_rag_log_id"] = log_id
        context["_rag_conversation_id"] = conversation_id
        context.pop("retrieval_context", None)
        self._set_debug_state(
            context,
            memory_intent=memory_intent,
            rag_enabled=rag_enabled,
            rag_retrieved=False,
            hit_count=0,
            injection_mode=injection_mode,
            no_hit_guard=False,
            degraded_reason=reason,
            latency_ms=elapsed_ms,
            gate_decision=gate_decision,
            strategy=strategy,
        )
