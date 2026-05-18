"""Build minimized RAG retrieval context for LLM suggestions."""

from __future__ import annotations

import re
import time
from typing import Any

from ...db.connection import get_db
from .privacy_redactor import PrivacyRedactor
from .rag_config import is_remote_llm_model, load_rag_settings
from .rag_indexer import RagIndexer
from .rag_retriever import RagRetriever
from .rag_store import RagStore


class RagContextBuilder:
    """Orchestrates lazy index, retrieval, minimization, redaction and logs."""

    MAX_CONTEXT_CHARS = 560

    def __init__(
        self,
        store: RagStore | None = None,
        indexer: RagIndexer | None = None,
        retriever: RagRetriever | None = None,
    ):
        self.store = store or RagStore()
        self.indexer = indexer or RagIndexer(self.store)
        self.retriever = retriever or RagRetriever(self.store)

    def enrich_context(
        self,
        context: dict[str, Any],
        *,
        trigger_type: str,
        intent: str,
        model_config: dict[str, Any] | None = None,
    ) -> None:
        settings = load_rag_settings()
        if not settings.get("rag_enabled"):
            context.pop("retrieval_context", None)
            return

        account_wxid = str(context.get("account_wxid") or "").strip()
        conversation_id = self._resolve_conversation_id(context, account_wxid)
        if not account_wxid or not conversation_id:
            return

        remote_model = is_remote_llm_model(model_config)
        started = time.perf_counter()
        deadline = started + 0.8
        query = self.retriever.build_query(context, trigger_type, intent)
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
            )
            return

        index_status = self.indexer.ensure_contact_index(
            account_wxid=account_wxid,
            conversation_id=conversation_id,
        )
        status_name = (index_status or {}).get("status")
        document_count = int((index_status or {}).get("document_count") or 0)
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
            )
            return
        if status_name in {"pending", "indexing"} and document_count <= 0:
            self._log_skip(
                context,
                account_wxid=account_wxid,
                conversation_id=conversation_id,
                query=query,
                started=started,
                index_status=status_name,
                remote_model=remote_model,
                reason="index_not_ready",
            )
            return
        if status_name == "failed":
            self._log_skip(
                context,
                account_wxid=account_wxid,
                conversation_id=conversation_id,
                query=query,
                started=started,
                index_status=status_name,
                remote_model=remote_model,
                reason="index_failed",
            )
            return

        remaining_ms = max(1, int((deadline - time.perf_counter()) * 1000))
        result = self.retriever.retrieve(
            account_wxid=account_wxid,
            conversation_id=conversation_id,
            query=query,
            timeout_ms=remaining_ms,
            deadline=deadline,
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
                result.get("items") or [],
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
        )
        self.store.conn.commit()
        context["_rag_log_id"] = log_id
        context["_rag_conversation_id"] = conversation_id
        if items:
            context["retrieval_context"] = {
                "account_wxid": account_wxid,
                "conversation_id": conversation_id,
                "items": items,
                "index_status": (index_status or {}).get("status"),
                "elapsed_ms": elapsed_ms,
                "redaction_status": redaction_status,
                "redaction_disabled": redaction_disabled,
                "degraded": bool(result.get("degraded")),
                "degrade_reason": result.get("degrade_reason"),
            }
        else:
            context.pop("retrieval_context", None)

    def attach_log_to_suggestion(self, log_id: int | None, suggestion_id: int) -> None:
        self.store.attach_log_to_suggestion(log_id, suggestion_id)
        self.store.conn.commit()

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
        minimized = []
        total_chars = 0
        for scored in items:
            doc = scored.get("doc") or {}
            content = str(doc.get("redacted_content") if use_redacted else doc.get("content") or "").strip()
            content = re.sub(r"\s+", " ", content)
            if not content:
                continue
            remaining = self.MAX_CONTEXT_CHARS - total_chars
            if remaining <= 0:
                break
            content = content[: min(160, remaining)]
            minimized.append(
                {
                    "document_id": int(doc["id"]),
                    "doc_type": doc.get("doc_type"),
                    "content": content,
                    "score": scored.get("score"),
                    "source_ts": doc.get("source_ts"),
                    "sensitivity": doc.get("sensitivity") or "normal",
                }
            )
            total_chars += len(content)
        return minimized

    def _safe_query_for_log(self, query: str) -> str:
        # Retrieval logs need traceability, not raw long chat history.
        text = re.sub(r"\s+", " ", str(query or "")).strip()
        try:
            return PrivacyRedactor(self.store.conn).strong_mask(text[:500])
        except Exception:
            return text[:120]

    def _budget_exhausted(self, deadline: float) -> bool:
        return time.perf_counter() > deadline

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
    ) -> None:
        settings = load_rag_settings()
        redaction_disabled = bool(remote_model and not settings.get("rag_remote_context_redaction"))
        log_id = self.store.insert_retrieval_log(
            account_wxid=account_wxid,
            conversation_id=conversation_id,
            query_text=self._safe_query_for_log(query),
            document_ids=[],
            retrieval_scores={},
            index_status=index_status,
            elapsed_ms=int((time.perf_counter() - started) * 1000),
            timed_out=timed_out,
            degraded=True,
            degrade_reason=reason,
            redaction_status="disabled" if redaction_disabled else ("raw_local" if not remote_model else "redacted"),
            redaction_disabled=redaction_disabled,
            redaction_fallback=False,
            remote_model=remote_model,
        )
        self.store.conn.commit()
        context["_rag_log_id"] = log_id
        context["_rag_conversation_id"] = conversation_id
        context.pop("retrieval_context", None)
