"""Window based attribution for realtime suggestion feedback."""

from __future__ import annotations

import difflib
import json
import logging
import threading
import time
from typing import Any

from .rag_config import load_rag_settings
from .rag_embedding import (
    RagEmbeddingDimensionMismatch,
    RagEmbeddingService,
    RagEmbeddingUnavailable,
)
from .rag_store import RAG_INDEX_VERSION, RagStore


logger = logging.getLogger(__name__)

POSITIVE_ATTRIBUTIONS = {"accepted", "rewritten", "preface_then_reply"}


def similarity(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, str(a or ""), str(b or "")).ratio()


class SuggestionFeedbackAttributor:
    """Classify user behavior after a suggestion using a time and conversation window."""

    MIN_WINDOW_SECONDS = 180
    MAX_WINDOW_SECONDS = 600
    PREFACE_MAX_CHARS = 8
    MERGE_GAP_SECONDS = 90
    PREFACE_MARKERS = ("对了", "等等", "还有", "我想说", "等下", "先说")

    def __init__(self, conn: Any):
        self.conn = conn
        self.store = RagStore(conn)
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS suggestion_feedback_attributions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                account_wxid TEXT NOT NULL,
                conversation_id INTEGER,
                suggestion_id INTEGER NOT NULL,
                batch_id TEXT,
                attribution_type TEXT NOT NULL,
                confidence REAL NOT NULL,
                candidate_messages_json TEXT NOT NULL,
                selected_speech TEXT,
                final_message TEXT,
                writeback_document_id INTEGER,
                metadata_json TEXT,
                created_at INTEGER NOT NULL
            )
            """
        )

    def attribute(
        self,
        *,
        suggestion_id: int,
        now_ts: int | None = None,
        allow_pending: bool = True,
    ) -> dict[str, Any]:
        now = int(now_ts or time.time())
        suggestion = self._load_suggestion(suggestion_id)
        if not suggestion:
            return {"ok": False, "pending": False, "error": "suggestion_not_found"}

        messages = self._load_window_messages(suggestion, now)
        self_messages = [msg for msg in messages if msg.get("sender_attr") == "self"]
        other_after = [msg for msg in messages if msg.get("sender_attr") not in {"self", "system"}]
        if other_after and (not self_messages or other_after[0]["timestamp"] < self_messages[0]["timestamp"]):
            result = self._result("interrupted", 0.45, messages)
            self._write_attribution(suggestion, result)
            return {"ok": True, "pending": False, **result}

        if not self_messages:
            if allow_pending and now - int(suggestion["created_at"]) < self.MAX_WINDOW_SECONDS:
                return {"ok": True, "pending": True}
            result = self._result("low_confidence", 0.0, messages)
            self._write_attribution(suggestion, result)
            return {"ok": True, "pending": False, **result}

        merged = self._merge_self_messages(self_messages)
        if (
            len(merged) == 1
            and len(merged[0].get("message_ids") or []) <= 1
            and self._is_preface(merged[0]["content"])
        ):
            if allow_pending and now - int(suggestion["created_at"]) < self.MAX_WINDOW_SECONDS:
                return {"ok": True, "pending": True}

        speeches = self._load_speeches(suggestion)
        final_message = merged[-1]["content"] if merged else ""
        selected_speech, max_similarity = self._best_match(final_message, speeches)

        first_raw_content = str(self_messages[0].get("content") or "").strip()
        if len(self_messages) >= 2 and self._is_preface(first_raw_content):
            final_message = str(self_messages[-1].get("content") or final_message).strip()
            selected_speech, max_similarity = self._best_match(final_message, speeches)
            result = self._result(
                "preface_then_reply",
                max(0.70, max_similarity),
                self_messages,
                selected_speech=selected_speech,
                final_message=final_message,
            )
        elif max_similarity >= 0.90:
            result = self._result(
                "accepted",
                max_similarity,
                self_messages,
                selected_speech=selected_speech,
                final_message=final_message,
            )
        elif max_similarity >= 0.35:
            result = self._result(
                "rewritten",
                max_similarity,
                self_messages,
                selected_speech=selected_speech,
                final_message=final_message,
            )
        elif now - int(suggestion["created_at"]) < self.MIN_WINDOW_SECONDS and allow_pending:
            return {"ok": True, "pending": True}
        else:
            result = self._result(
                "unrelated",
                max_similarity,
                self_messages,
                selected_speech=selected_speech,
                final_message=final_message,
            )

        self._write_attribution(suggestion, result)
        return {"ok": True, "pending": False, **result}

    @classmethod
    def schedule_check(cls, conn_factory, suggestion_id: int, delay_seconds: int | None = None) -> None:
        delay = cls.MIN_WINDOW_SECONDS if delay_seconds is None else int(delay_seconds)

        def _run() -> None:
            conn = conn_factory()
            try:
                result = cls(conn).attribute(
                    suggestion_id=suggestion_id,
                    allow_pending=False,
                )
                if result.get("ok") and not result.get("pending"):
                    suggestion = conn.execute(
                        "SELECT account_wxid, id FROM realtime_suggestions WHERE id = ?",
                        (int(suggestion_id),),
                    ).fetchone()
                    if suggestion:
                        conn.execute(
                            """
                            UPDATE realtime_suggestions
                            SET status = 'feedback_collected'
                            WHERE account_wxid = ? AND id = ?
                              AND status IN ('attribution_window', 'feedback_processing')
                            """,
                            (suggestion["account_wxid"], int(suggestion_id)),
                        )
                        conn.commit()
            except Exception:
                try:
                    conn.rollback()
                except Exception:
                    pass

        timer = threading.Timer(delay, _run)
        timer.daemon = True
        timer.start()

    def _load_suggestion(self, suggestion_id: int) -> dict[str, Any] | None:
        row = self.conn.execute(
            """
            SELECT *
            FROM realtime_suggestions
            WHERE id = ?
            LIMIT 1
            """,
            (int(suggestion_id),),
        ).fetchone()
        return dict(row) if row else None

    def _load_speeches(self, suggestion: dict[str, Any]) -> list[str]:
        try:
            data = json.loads(suggestion.get("speeches") or "[]")
            if isinstance(data, list):
                return [str(item) for item in data if str(item).strip()]
        except Exception:
            pass
        return []

    def _load_window_messages(self, suggestion: dict[str, Any], now: int) -> list[dict[str, Any]]:
        batch_id = suggestion.get("batch_id")
        account_wxid = suggestion.get("account_wxid")
        if not batch_id or not account_wxid:
            return []
        start_ts = int(suggestion.get("created_at") or 0)
        end_ts = min(now, start_ts + self.MAX_WINDOW_SECONDS)
        rows = self.conn.execute(
            """
            SELECT id, account_wxid, batch_id, talker_username, talker_display_name,
                   sender_attr, content, message_type, timestamp, created_at
            FROM realtime_message_buffer
            WHERE account_wxid = ? AND batch_id = ?
              AND timestamp >= ? AND timestamp <= ?
              AND COALESCE(TRIM(content), '') != ''
            ORDER BY timestamp ASC, created_at ASC, id ASC
            """,
            (account_wxid, batch_id, start_ts, end_ts),
        ).fetchall()
        return [dict(row) for row in rows]

    def _merge_self_messages(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        merged: list[dict[str, Any]] = []
        for msg in messages:
            content = str(msg.get("content") or "").strip()
            if not content:
                continue
            if (
                merged
                and int(msg.get("timestamp") or 0) - int(merged[-1].get("timestamp") or 0) <= self.MERGE_GAP_SECONDS
            ):
                merged[-1]["content"] = f"{merged[-1]['content']} {content}".strip()
                merged[-1]["timestamp"] = msg.get("timestamp")
                merged[-1].setdefault("message_ids", []).append(msg.get("id"))
            else:
                item = dict(msg)
                item["content"] = content
                item["message_ids"] = [msg.get("id")]
                merged.append(item)
        return merged

    def _best_match(self, message: str, speeches: list[str]) -> tuple[str | None, float]:
        best_speech = None
        best_score = 0.0
        for speech in speeches:
            score = similarity(message, speech)
            if score > best_score:
                best_score = score
                best_speech = speech
        return best_speech, round(best_score, 4)

    def _is_preface(self, content: str) -> bool:
        text = str(content or "").strip()
        if not text:
            return False
        if len(text) <= self.PREFACE_MAX_CHARS:
            return True
        return any(text.startswith(marker) for marker in self.PREFACE_MARKERS)

    def _result(
        self,
        attribution_type: str,
        confidence: float,
        messages: list[dict[str, Any]],
        *,
        selected_speech: str | None = None,
        final_message: str | None = None,
    ) -> dict[str, Any]:
        return {
            "attribution_type": attribution_type,
            "confidence": round(float(confidence), 4),
            "candidate_messages": [
                {
                    "id": msg.get("id"),
                    "sender_attr": msg.get("sender_attr"),
                    "content": str(msg.get("content") or "")[:200],
                    "timestamp": msg.get("timestamp"),
                }
                for msg in messages
            ],
            "selected_speech": selected_speech,
            "final_message": final_message,
        }

    def _write_attribution(self, suggestion: dict[str, Any], result: dict[str, Any]) -> None:
        conversation_id = self._resolve_conversation_id(suggestion)
        writeback_document_id = None
        if (
            result["attribution_type"] in POSITIVE_ATTRIBUTIONS
            and float(result["confidence"]) >= 0.65
            and conversation_id
        ):
            content = (
                f"AI建议: {result.get('selected_speech') or ''}\n"
                f"用户实际发送: {result.get('final_message') or ''}\n"
                f"归因: {result['attribution_type']}"
            ).strip()
            writeback_document_id = self.store.upsert_document(
                account_wxid=suggestion["account_wxid"],
                conversation_id=conversation_id,
                doc_type="feedback_example",
                source_table="suggestion_feedback_attributions",
                source_id=str(suggestion["id"]),
                source_ts=int(time.time()),
                content=content,
                redacted_content=content,
                metadata={
                    "confidence": result["confidence"],
                    "source_kind": "feedback",
                    "index_version": RAG_INDEX_VERSION,
                    "summary_method": "rules",
                },
                index_version=RAG_INDEX_VERSION,
                source_kind="feedback",
            )
            self._try_embed_feedback_document(
                writeback_document_id,
                suggestion["account_wxid"],
                conversation_id,
                content,
            )

        self.conn.execute(
            """
            INSERT INTO suggestion_feedback_attributions
            (account_wxid, conversation_id, suggestion_id, batch_id, attribution_type,
             confidence, candidate_messages_json, selected_speech, final_message,
             writeback_document_id, metadata_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                suggestion["account_wxid"],
                conversation_id,
                suggestion["id"],
                suggestion.get("batch_id"),
                result["attribution_type"],
                result["confidence"],
                json.dumps(result["candidate_messages"], ensure_ascii=False),
                result.get("selected_speech"),
                result.get("final_message"),
                writeback_document_id,
                json.dumps({"window": "3-10min"}, ensure_ascii=False),
                int(time.time()),
            ),
        )
        # P2.1 影子信号：正归因绑定该建议实际使用的策略/注入项——
        # "反馈→策略修正"的审计底账（只记录不决策），失败不影响归因
        if result["attribution_type"] in POSITIVE_ATTRIBUTIONS:
            candidate_ids: list[int] = []
            try:
                candidate_ids = self._try_extract_feedback_candidates(suggestion, result)
            except Exception as exc:
                # G7：抽取失败不再完全静默（其余候选被丢弃属于异常路径，
                # 需要留痕）；归因主链路仍不受影响
                logger.warning(
                    "[FeedbackAttribution] candidate extraction failed: %s", exc
                )
                candidate_ids = []
            try:
                self._write_policy_signal(
                    suggestion, result, conversation_id, extra_detail={"candidate_fact_ids": candidate_ids}
                )
            except Exception as exc:
                logger.warning(
                    "[FeedbackAttribution] policy signal write failed: %s", exc
                )

    def _try_extract_feedback_candidates(
        self, suggestion: dict[str, Any], result: dict[str, Any]
    ) -> list[int]:
        """P2.1 影子闭环：rewritten 差异 → 偏好候选（uncertain 影子行）。

        候选 status='uncertain'（读侧 list_facts 只取 active，不参与检索
        与注入）；积累到量并经 P0.3 人工集校准后，才批量转正。跟随
        rag_structured_fact_extraction_enabled 开关；同一建议只抽一次；
        任何失败静默返回空，绝不阻塞归因主链路。
        """
        if str(result.get("attribution_type") or "") != "rewritten":
            return []
        if float(result.get("confidence") or 0.0) < 0.65:
            return []
        from .rag_config import load_rag_settings

        if not load_rag_settings().get("rag_structured_fact_extraction_enabled"):
            return []
        suggestion_id = int(suggestion.get("id") or 0)
        if not suggestion_id:
            return []
        existing = self.conn.execute(
            """
            SELECT 1 FROM rag_feedback_policy_signals
            WHERE suggestion_id = ? AND action = 'rewritten'
              AND outcome = 'candidate_created' LIMIT 1
            """,
            (suggestion_id,),
        ).fetchone()
        if existing:
            return []

        original = str(result.get("selected_speech") or "")
        final = str(result.get("final_message") or "")
        if not original or not final:
            return []
        from .rag_fact_llm import build_llm_fact_extractor

        adapter = build_llm_fact_extractor()
        if adapter is None:
            return []
        signals = adapter.extract_feedback_signals(
            original_speech=original, final_message=final
        )
        from .rag_fact_quality import fact_quality_reason

        account_wxid = str(suggestion.get("account_wxid") or "")
        conversation_id = self._resolve_conversation_id(suggestion)
        created: list[int] = []
        now = int(time.time())
        for signal in signals[:5]:
            if fact_quality_reason(
                signal.get("kind"), signal.get("content"), require_kind_signal=False
            ) is not None:
                continue
            cursor = self.conn.execute(
                """
                INSERT OR IGNORE INTO rag_facts
                (account_wxid, conversation_id, subject, kind, content, status, as_of,
                 confidence, sensitivity, enabled, evidence_message_ids_json,
                 source_window_json, summary_method, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, 'uncertain', ?, ?, 'normal', 1, '[]', ?,
                        'feedback_shadow', ?, ?)
                """,
                (
                    account_wxid,
                    conversation_id,
                    signal.get("subject") or "我",
                    signal.get("kind") or "preference",
                    signal.get("content"),
                    now,
                    min(0.75, float(signal.get("confidence") or 0.0)),
                    # evidence 为模型基于（远程时已脱敏）输入生成的差异说明；
                    # 原始建议/发送文本不入库
                    json.dumps({"evidence": signal.get("evidence") or ""}, ensure_ascii=False),
                    now,
                    now,
                ),
            )
            if cursor.rowcount:
                created.append(int(cursor.lastrowid or 0))
            else:
                # G7：同内容信号第二次触发会撞 UNIQUE(account,conversation,
                # kind,content)——忽略本次插入并回查已存在行 id 继续用作
                # 候选，不再让 IntegrityError 把其余候选一起吞掉
                existing_fact = self.conn.execute(
                    """
                    SELECT id FROM rag_facts
                    WHERE account_wxid=? AND conversation_id=? AND kind=? AND content=?
                    """,
                    (
                        account_wxid,
                        conversation_id,
                        signal.get("kind") or "preference",
                        signal.get("content"),
                    ),
                ).fetchone()
                if existing_fact is not None:
                    created.append(int(existing_fact["id"]))
        if not created and signals:
            outcome = "no_qualified_candidate"
        else:
            outcome = "candidate_created" if created else "no_candidate"
        try:
            from .rag_store import RagStore

            RagStore(self.conn).record_feedback_policy_signal(
                account_wxid=account_wxid,
                conversation_id=conversation_id,
                suggestion_id=suggestion_id,
                action="rewritten",
                signal_kind="feedback_candidate_extraction",
                affected_policy_ids=[],
                outcome=outcome,
                detail={"signals": len(signals), "candidate_fact_ids": created},
            )
        except Exception:
            pass
        return created

    def _write_policy_signal(
        self, suggestion: dict[str, Any], result: dict[str, Any], conversation_id: int | None,
        extra_detail: dict[str, Any] | None = None,
    ) -> None:
        from .rag_store import RagStore

        log = self.conn.execute(
            """
            SELECT id, policy_ids_json, contact_preference_ids_json, injected_item_ids_json
            FROM rag_retrieval_logs WHERE suggestion_id = ? ORDER BY id DESC LIMIT 1
            """,
            (int(suggestion["id"]),),
        ).fetchone()
        if log is None:
            return
        RagStore(self.conn).record_feedback_policy_signal(
            account_wxid=str(suggestion.get("account_wxid") or ""),
            conversation_id=conversation_id,
            suggestion_id=int(suggestion["id"]),
            action=str(result["attribution_type"]),
            signal_kind="suggestion_attribution",
            affected_policy_ids=json.loads(log["policy_ids_json"] or "[]"),
            outcome="recorded",
            retrieval_log_id=int(log["id"]),
            detail={
                "confidence": result["confidence"],
                "contact_preference_ids": json.loads(log["contact_preference_ids_json"] or "[]"),
                "injected_item_ids": json.loads(log["injected_item_ids_json"] or "[]"),
                "selected_speech": (result.get("selected_speech") or "")[:200],
                "final_message": (result.get("final_message") or "")[:200],
            },
        )

    def _resolve_conversation_id(self, suggestion: dict[str, Any]) -> int | None:
        trigger_context = {}
        try:
            trigger_context = json.loads(suggestion.get("trigger_context") or "{}")
        except Exception:
            pass
        raw = trigger_context.get("conversation_id") or trigger_context.get("_rag_conversation_id")
        try:
            if raw:
                return int(raw)
        except (TypeError, ValueError):
            pass
        row = self.conn.execute(
            """
            SELECT c.id
            FROM conversations c
            INNER JOIN realtime_message_buffer b
              ON b.account_wxid = c.account_wxid
             AND (b.talker_username = c.username OR b.talker_display_name = c.display_name)
            WHERE b.account_wxid = ? AND b.batch_id = ?
            ORDER BY c.updated_at DESC
            LIMIT 1
            """,
            (suggestion.get("account_wxid"), suggestion.get("batch_id")),
        ).fetchone()
        return int(row["id"]) if row else None

    def _try_embed_feedback_document(
        self,
        document_id: int | None,
        account_wxid: str,
        conversation_id: int,
        content: str,
    ) -> None:
        if not document_id:
            return
        try:
            settings = load_rag_settings()
            model = str(settings["rag_embedding_model"])
            dim = int(settings["rag_embedding_dim"])
            vector = RagEmbeddingService().embed_text(content)
            if len(vector) != dim:
                raise RagEmbeddingDimensionMismatch(
                    f"feedback embedding dimension mismatch: vector={len(vector)} configured={dim}"
                )
            self.store.upsert_embedding(
                document_id=int(document_id),
                account_wxid=account_wxid,
                conversation_id=conversation_id,
                embedding_model=model,
                embedding_dim=dim,
                vector=vector,
                embedding_provider="local",
            )
        except (RagEmbeddingUnavailable, RagEmbeddingDimensionMismatch):
            self._mark_feedback_dirty(account_wxid, conversation_id)
        except Exception:
            self._mark_feedback_dirty(account_wxid, conversation_id)

    def _mark_feedback_dirty(self, account_wxid: str, conversation_id: int) -> None:
        try:
            from .rag_indexer import RagIndexQueue

            RagIndexQueue.mark_dirty(account_wxid, conversation_id)
        except Exception:
            pass
