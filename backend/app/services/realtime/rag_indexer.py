"""Contact-scoped lazy and incremental RAG indexing."""

from __future__ import annotations

import logging
import re
import threading
import time
from typing import Any

from ...db.connection import get_db
from .privacy_redactor import PrivacyRedactor
from .rag_config import load_rag_settings
from .rag_embedding import RagEmbeddingService, RagEmbeddingUnavailable
from .rag_semantic_memory import SemanticFactExtractor
from .rag_segmenter import RagSegment, RagSegmenter
from .rag_store import RAG_INDEX_VERSION, RagStore


logger = logging.getLogger(__name__)


class RagIndexer:
    """Build a minimal but useful per-contact RAG index."""

    INDEX_VERSION = RAG_INDEX_VERSION
    SELF_STYLE_LIMIT = 24
    EMBED_BATCH_SIZE = 64
    WRITE_COMMIT_INTERVAL = 64

    def __init__(
        self,
        store: RagStore | None = None,
        embedding_service: RagEmbeddingService | None = None,
    ):
        self.store = store or RagStore()
        self.embedding_service = embedding_service or RagEmbeddingService()
        self.segmenter = RagSegmenter()
        self.semantic_fact_extractor = SemanticFactExtractor(self.embedding_service, self.segmenter)

    def ensure_contact_index(
        self,
        *,
        account_wxid: str,
        conversation_id: int,
        force: bool = False,
    ) -> dict[str, Any]:
        settings = load_rag_settings()
        self.store.mark_stale_for_config_change(
            account_wxid,
            embedding_model=str(settings["rag_embedding_model"]),
            embedding_dim=int(settings["rag_embedding_dim"]),
            privacy_mode=str(settings["rag_privacy_mode"]),
            index_version=self.INDEX_VERSION,
        )
        status = self.store.get_status(account_wxid, conversation_id)
        if (
            status
            and status.get("enabled", 1)
            and status.get("index_version") != self.INDEX_VERSION
            and status.get("status") in {"ready", "stale"}
        ):
            self.store.upsert_status(
                account_wxid,
                conversation_id,
                status="stale",
                dirty_since=int(time.time()),
                index_version=self.INDEX_VERSION,
            )
            self.store.conn.commit()
            status = self.store.get_status(account_wxid, conversation_id)
        if force:
            return self.rebuild_contact_index(
                account_wxid=account_wxid,
                conversation_id=conversation_id,
            )
        if status and not status.get("enabled", 1):
            return status
        if (
            status
            and status.get("enabled", 1)
            and status.get("status") == "ready"
            and int(status.get("document_count") or 0) > 0
        ):
            return status
        if (
            status
            and status.get("enabled", 1)
            and status.get("status") == "stale"
            and int(status.get("document_count") or 0) > 0
        ):
            RagIndexQueue.enqueue(account_wxid, conversation_id)
            return status
        if status and status.get("status") == "failed":
            if self._can_retry_failed_status(status):
                self.store.upsert_status(
                    account_wxid,
                    conversation_id,
                    status="pending",
                    embedding_model=str(settings["rag_embedding_model"]),
                    embedding_dim=int(settings["rag_embedding_dim"]),
                    privacy_mode=str(settings["rag_privacy_mode"]),
                    dirty_since=int(time.time()),
                    last_error=None,
                    index_version=self.INDEX_VERSION,
                )
                self.store.conn.commit()
                RagIndexQueue.enqueue(account_wxid, conversation_id)
                return self.store.get_status(account_wxid, conversation_id) or {}
            return status

        self.store.upsert_status(
            account_wxid,
            conversation_id,
            status="pending",
            embedding_model=str(settings["rag_embedding_model"]),
            embedding_dim=int(settings["rag_embedding_dim"]),
            privacy_mode=str(settings["rag_privacy_mode"]),
            dirty_since=int(time.time()),
            index_version=self.INDEX_VERSION,
        )
        self.store.conn.commit()
        RagIndexQueue.enqueue(account_wxid, conversation_id)
        return self.store.get_status(account_wxid, conversation_id) or {}

    def rebuild_contact_index(self, *, account_wxid: str, conversation_id: int) -> dict[str, Any]:
        settings = load_rag_settings()
        model = str(settings["rag_embedding_model"])
        dim = int(settings["rag_embedding_dim"])
        privacy_mode = str(settings["rag_privacy_mode"])
        self.store.upsert_status(
            account_wxid,
            conversation_id,
            status="indexing",
            embedding_model=model,
            embedding_dim=dim,
            privacy_mode=privacy_mode,
            last_error=None,
            index_version=self.INDEX_VERSION,
        )
        self.store.conn.commit()
        try:
            conversation = self._load_conversation(account_wxid, conversation_id)
            messages = self._load_messages(conversation_id)
            if not conversation or not messages:
                cleaned_old = self.store.delete_auto_documents(
                    account_wxid,
                    conversation_id,
                    index_version=self.INDEX_VERSION,
                )
                self.store.upsert_status(
                    account_wxid,
                    conversation_id,
                    status="ready",
                    document_count=0,
                    vector_count=0,
                    dirty_since=None,
                    index_version=self.INDEX_VERSION,
                )
                self.store.conn.commit()
                logger.debug(
                    "[RAG Index] version=%s docs=0 vectors=0 cleaned_old=%s",
                    self.INDEX_VERSION,
                    cleaned_old,
                )
                return self.store.get_status(account_wxid, conversation_id) or {}

            cleaned_old = self.store.delete_auto_documents(
                account_wxid,
                conversation_id,
                index_version=self.INDEX_VERSION,
            )
            self.store.conn.commit()
            docs = self._build_documents(account_wxid, conversation_id, conversation, messages)
            self.store.conn.commit()
            docs.extend(self._load_feedback_documents_for_embedding(account_wxid, conversation_id))
            if not docs:
                self.store.upsert_status(
                    account_wxid,
                    conversation_id,
                    status="ready",
                    document_count=0,
                    vector_count=0,
                    dirty_since=None,
                    index_version=self.INDEX_VERSION,
                )
                self.store.conn.commit()
                logger.debug(
                    "[RAG Index] version=%s docs=0 vectors=0 cleaned_old=%s",
                    self.INDEX_VERSION,
                    cleaned_old,
                )
                return self.store.get_status(account_wxid, conversation_id) or {}

            document_count = 0
            vector_count = 0
            for start in range(0, len(docs), self.EMBED_BATCH_SIZE):
                batch = docs[start:start + self.EMBED_BATCH_SIZE]
                vectors = self.embedding_service.embed_texts([doc["content"] for doc in batch])
                for doc, vector in zip(batch, vectors):
                    existing_document_id = doc.pop("_existing_document_id", None)
                    if existing_document_id:
                        document_id = int(existing_document_id)
                    else:
                        document_id = self.store.upsert_document(**doc)
                        document_count += 1
                    self.store.upsert_embedding(
                        document_id=document_id,
                        account_wxid=account_wxid,
                        conversation_id=conversation_id,
                        embedding_model=model,
                        embedding_dim=dim,
                        vector=vector,
                        embedding_provider="local",
                    )
                    vector_count += 1
                self.store.conn.commit()
                logger.debug(
                    "[RAG Index] progress version=%s docs=%s/%s vectors=%s",
                    self.INDEX_VERSION,
                    min(start + len(batch), len(docs)),
                    len(docs),
                    vector_count,
                )

            self.store.upsert_status(
                account_wxid,
                conversation_id,
                status="ready",
                embedding_model=model,
                embedding_dim=dim,
                privacy_mode=privacy_mode,
                document_count=self._count_indexed_documents(account_wxid, conversation_id),
                vector_count=vector_count,
                dirty_since=None,
                last_error=None,
                index_version=self.INDEX_VERSION,
            )
            self.store.conn.commit()
            logger.debug(
                "[RAG Index] version=%s docs=%s vectors=%s cleaned_old=%s",
                self.INDEX_VERSION,
                document_count,
                vector_count,
                cleaned_old,
            )
            return self.store.get_status(account_wxid, conversation_id) or {}
        except RagEmbeddingUnavailable as exc:
            self.store.upsert_status(
                account_wxid,
                conversation_id,
                status="failed",
                embedding_model=model,
                embedding_dim=dim,
                privacy_mode=privacy_mode,
                last_error=str(exc),
                index_version=self.INDEX_VERSION,
            )
            self.store.conn.commit()
            return self.store.get_status(account_wxid, conversation_id) or {}
        except Exception as exc:
            logger.exception("[RAG] contact index failed")
            self.store.upsert_status(
                account_wxid,
                conversation_id,
                status="failed",
                embedding_model=model,
                embedding_dim=dim,
                privacy_mode=privacy_mode,
                last_error=type(exc).__name__,
                index_version=self.INDEX_VERSION,
            )
            self.store.conn.commit()
            return self.store.get_status(account_wxid, conversation_id) or {}

    def _load_conversation(self, account_wxid: str, conversation_id: int) -> dict[str, Any] | None:
        row = self.store.conn.execute(
            """
            SELECT *
            FROM conversations
            WHERE account_wxid = ? AND id = ?
            LIMIT 1
            """,
            (account_wxid, conversation_id),
        ).fetchone()
        return dict(row) if row else None

    def _load_messages(self, conversation_id: int) -> list[dict[str, Any]]:
        rows = self.store.conn.execute(
            """
            SELECT id, conversation_id, is_sender, content, timestamp, message_type
            FROM messages
            WHERE conversation_id = ?
              AND message_type = 1
              AND content IS NOT NULL
              AND TRIM(content) != ''
            ORDER BY timestamp ASC, id ASC
            """,
            (conversation_id,),
        ).fetchall()
        return [dict(row) for row in rows]

    def _build_documents(
        self,
        account_wxid: str,
        conversation_id: int,
        conversation: dict[str, Any],
        messages: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        redactor = PrivacyRedactor(self.store.conn)
        docs: list[dict[str, Any]] = []
        sessions = self._load_sessions_reference(conversation_id)
        display_name = (
            str(conversation.get("display_name") or conversation.get("username") or "").strip()
        )
        first_ts = int(messages[0].get("timestamp") or 0)
        last_ts = int(messages[-1].get("timestamp") or 0)
        relationship = (
            f"与 {display_name} 的关系状态摘要：累计 {conversation.get('message_count') or len(messages)} 条消息，"
            f"最近对话时间 {last_ts}。当前建议仍以最近对话为最高优先级。"
        )
        docs.append(
            self._doc_payload(
                redactor,
                account_wxid,
                conversation_id,
                "relationship_state",
                relationship,
                "conversations",
                str(conversation_id),
                last_ts or first_ts,
                metadata=self._metadata(
                    segment=None,
                    source_kind="historical",
                    summary_method="rules",
                    extra={"display_name": display_name},
                ),
            )
        )

        segments = self.segmenter.segment(messages, conversation_id=conversation_id, sessions=sessions)
        logger.debug(
            "[RAG Segment] messages=%s segments=%s sessions=%s source=sessions/reference_only",
            len(messages),
            len(segments),
            len(sessions),
        )

        semantic_fact_count = 0
        for index, segment in enumerate(segments, 1):
            topic_content = self.segmenter.render_segment(segment)
            sensitivity = "sensitive" if self._looks_sensitive(topic_content) else "normal"
            docs.append(
                self._doc_payload(
                    redactor,
                    account_wxid,
                    conversation_id,
                    "topic_segment",
                    topic_content,
                    "messages",
                    f"segment:{index}:{segment.start_ts}:{segment.end_ts}",
                    segment.end_ts,
                    sensitivity=sensitivity,
                    metadata=self._metadata(segment, source_kind="historical", summary_method="rules"),
                )
            )
            excerpt_content = self.segmenter.render_excerpt(segment)
            docs.append(
                self._doc_payload(
                    redactor,
                    account_wxid,
                    conversation_id,
                    "evidence_excerpt",
                    excerpt_content,
                    "messages",
                    f"evidence:{index}:{segment.start_ts}:{segment.end_ts}",
                    segment.end_ts,
                    sensitivity="sensitive" if self._looks_sensitive(excerpt_content) else "normal",
                    metadata=self._metadata(segment, source_kind="historical", summary_method="rules"),
                )
            )
            semantic_facts = self.semantic_fact_extractor.extract(segment)
            semantic_fact_count += len(
                [fact for fact in semantic_facts if fact.memory_kind != "marker_fallback"]
            )
            for fact_index, fact in enumerate(semantic_facts, 1):
                fact_metadata = self._metadata(
                    segment,
                    source_kind="historical",
                    summary_method="semantic_embedding"
                    if fact.memory_kind != "marker_fallback"
                    else "marker_fallback",
                    extra={
                        "fact_source_id": fact.source_id,
                        "subject": fact.subject,
                        "topics": fact.topics or segment.topics,
                        "entities": fact.entities or segment.entities,
                        "memory_kind": fact.memory_kind,
                        "semantic_score": fact.semantic_score,
                        "evidence_message_ids": fact.evidence_message_ids,
                        "source_window_start_ts": fact.source_window_start_ts,
                        "source_window_end_ts": fact.source_window_end_ts,
                    },
                )
                docs.append(
                    self._doc_payload(
                        redactor,
                        account_wxid,
                        conversation_id,
                        "fact_memory",
                        f"时间：{segment.time_label}\n{fact.content}",
                        "messages",
                        f"fact:{index}:{fact_index}:{fact.source_id or 'window'}:{fact.memory_kind}",
                        int(fact.source_ts or segment.end_ts),
                        sensitivity="sensitive" if self._looks_sensitive(fact.content) else "normal",
                        metadata=fact_metadata,
                    )
                )

        self_messages = self._select_style_samples(messages, last_ts=last_ts)
        for index, content in enumerate(self_messages, 1):
            docs.append(
                self._doc_payload(
                    redactor,
                    account_wxid,
                    conversation_id,
                    "self_style_example",
                    content,
                    "messages",
                    f"style:{index}:{hash(content)}",
                    last_ts,
                    metadata=self._metadata(
                        segment=None,
                        source_kind="historical",
                        summary_method="rules",
                        extra={
                            "style_sample": True,
                            "style_sample_rank": index,
                            "style_sample_strategy": "recent_quality",
                        },
                    ),
                )
            )

        style_lines = [
            self._compact_content(msg.get("content"))
            for msg in messages
            if int(msg.get("is_sender") or 0) and self._is_style_sample(msg.get("content"))
        ]
        if style_lines:
            communication_style = self._build_communication_style_summary(style_lines, self_messages)
            docs.append(
                self._doc_payload(
                    redactor,
                    account_wxid,
                    conversation_id,
                    "communication_style",
                    communication_style,
                    "messages",
                    f"communication_style:{conversation_id}",
                    last_ts,
                    metadata=self._metadata(
                        segment=None,
                        source_kind="historical",
                        summary_method="rules",
                        extra={
                            "style_sample": True,
                            "style_sample_count": len(self_messages),
                            "semantic_fact_count": semantic_fact_count,
                        },
                    ),
                )
            )
        logger.debug(
            "[RAG Index] semantic_facts=%s style_samples=%s",
            semantic_fact_count,
            len(self_messages),
        )
        return docs

    def _doc_payload(
        self,
        redactor: PrivacyRedactor,
        account_wxid: str,
        conversation_id: int,
        doc_type: str,
        content: str,
        source_table: str,
        source_id: str,
        source_ts: int,
        *,
        sensitivity: str = "normal",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        metadata = dict(metadata or {})
        metadata.setdefault("index_version", self.INDEX_VERSION)
        metadata.setdefault("source_kind", "historical")
        metadata.setdefault("summary_method", "rules")
        redacted = redactor.redact(
            content,
            account_wxid=account_wxid,
            conversation_id=conversation_id,
            source_table=source_table,
            source_id=source_id,
        )
        return {
            "account_wxid": account_wxid,
            "conversation_id": conversation_id,
            "doc_type": doc_type,
            "content": content,
            "source_table": source_table,
            "source_id": source_id,
            "source_ts": int(source_ts or time.time()),
            "redacted_content": redacted.redacted_text,
            "entity_map_json": redacted.entity_map_json,
            "pii_flags_json": redacted.pii_flags_json,
            "metadata": metadata,
            "sensitivity": sensitivity,
            "index_version": self.INDEX_VERSION,
            "source_kind": str(metadata.get("source_kind") or "historical"),
        }

    def _compact_content(self, content: Any) -> str:
        text = re.sub(r"\s+", " ", str(content or "")).strip()
        return text[:180]

    def _is_style_sample(self, content: Any) -> bool:
        text = self._compact_content(content)
        if not (1 <= len(text) <= 80) or self._looks_sensitive(text):
            return False
        if not re.search(r"[A-Za-z0-9\u4e00-\u9fff]", text):
            return False
        if re.fullmatch(r"[\W_]+", text, flags=re.UNICODE):
            return False
        compact = re.sub(r"\s+", "", text)
        if compact in {"哈哈", "哈哈哈", "哈哈哈哈", "嗯", "嗯嗯", "哦", "好的", "可以", "行吧"}:
            return False
        meta_markers = (
            "请帮我",
            "帮我生成",
            "根据以上",
            "以下是",
            "作为AI",
            "作为ai",
            "模型",
            "prompt",
            "system",
        )
        return not any(marker in compact for marker in meta_markers)

    def _select_style_samples(self, messages: list[dict[str, Any]], *, last_ts: int) -> list[str]:
        candidates: list[tuple[float, int, str]] = []
        recent_cutoff = int(last_ts or time.time()) - 30 * 86400
        for index, msg in enumerate(messages):
            if not int(msg.get("is_sender") or 0):
                continue
            content = self._compact_content(msg.get("content"))
            if not self._is_style_sample(content):
                continue
            try:
                source_ts = int(msg.get("timestamp") or 0)
            except (TypeError, ValueError):
                source_ts = 0
            length = len(content)
            score = 0.0
            if source_ts >= recent_cutoff:
                score += 3.0
            if 4 <= length <= 36:
                score += 1.0
            if 37 <= length <= 80:
                score += 0.4
            if re.search(r"[？?]", content):
                score += 0.35
            if self._count_emoji(content) > 0:
                score += 0.25
            age_days = max(0.0, (int(last_ts or time.time()) - source_ts) / 86400) if source_ts else 365.0
            score += max(0.0, 1.0 - age_days / 90.0)
            candidates.append((score, index, content))

        candidates.sort(key=lambda item: (-item[0], -item[1]))
        selected: list[str] = []
        seen = set()
        for _score, _index, content in candidates:
            if content in seen:
                continue
            seen.add(content)
            selected.append(content)
            if len(selected) >= self.SELF_STYLE_LIMIT:
                break
        return selected

    def _build_communication_style_summary(self, style_lines: list[str], samples: list[str]) -> str:
        lines = style_lines[:80]
        avg_len = sum(len(line) for line in lines) / max(1, len(lines))
        question_ratio = sum(1 for line in lines if re.search(r"[？?]", line)) / max(1, len(lines))
        emoji_count = sum(self._count_emoji(line) for line in lines)
        emoji_ratio = emoji_count / max(1, len(lines))
        repeated_punct = sum(1 for line in lines if re.search(r"([!?！？。~～])\1+", line)) / max(1, len(lines))
        communication_type = (
            "proactive"
            if question_ratio >= 0.32 or avg_len >= 22
            else "reactive"
            if avg_len <= 8 and question_ratio < 0.18
            else "balanced"
        )
        emotional_style = (
            "warm"
            if emoji_ratio >= 0.20 or repeated_punct >= 0.18
            else "cold"
            if avg_len <= 7 and emoji_ratio <= 0.05
            else "neutral"
        )
        sample_text = " / ".join(samples[:8])
        return (
            "用户表达风格摘要："
            f"平均长度 {avg_len:.1f} 字；"
            f"问句比例 {question_ratio:.0%}；"
            f"emoji 使用率 {emoji_ratio:.0%}；"
            f"重复标点比例 {repeated_punct:.0%}；"
            f"沟通类型 {communication_type}；"
            f"情感风格 {emotional_style}。"
            f"近期高质量样例：{sample_text}"
        )

    def _count_emoji(self, text: str) -> int:
        return len(
            re.findall(
                r"[\U0001F300-\U0001FAFF\u2600-\u27BF]",
                str(text or ""),
            )
        )

    def _looks_sensitive(self, text: str) -> bool:
        keywords = ("秘密", "保密", "身份证", "银行卡", "密码", "密钥", "住址", "地址", "电话")
        return any(keyword in str(text or "") for keyword in keywords)

    def _metadata(
        self,
        segment: RagSegment | None,
        *,
        source_kind: str,
        summary_method: str,
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        metadata = dict(extra or {})
        if segment:
            metadata.update(
                {
                    "segment_id": segment.segment_id,
                    "start_ts": segment.start_ts,
                    "end_ts": segment.end_ts,
                    "time_label": segment.time_label,
                    "message_ids": segment.message_ids,
                    "topics": metadata.get("topics") or segment.topics,
                    "entities": metadata.get("entities") or segment.entities,
                    "session_id": segment.session_id,
                }
            )
        metadata["source_kind"] = source_kind
        metadata["summary_method"] = summary_method
        metadata["index_version"] = self.INDEX_VERSION
        return metadata

    def _load_sessions_reference(self, conversation_id: int) -> list[dict[str, Any]]:
        try:
            rows = self.store.conn.execute(
                """
                SELECT id, start_time, end_time, message_count, initiator
                FROM sessions
                WHERE conversation_id = ?
                ORDER BY start_time ASC
                """,
                (conversation_id,),
            ).fetchall()
            return [dict(row) for row in rows]
        except Exception:
            return []

    def _load_feedback_documents_for_embedding(self, account_wxid: str, conversation_id: int) -> list[dict[str, Any]]:
        settings = load_rag_settings()
        rows = self.store.conn.execute(
            """
            SELECT d.*
            FROM rag_documents d
            LEFT JOIN rag_embeddings e
              ON e.document_id = d.id
             AND e.embedding_model = ?
             AND e.embedding_dim = ?
            WHERE d.account_wxid = ?
              AND d.conversation_id = ?
              AND d.doc_type = 'feedback_example'
              AND d.enabled = 1
              AND d.superseded_by IS NULL
              AND e.id IS NULL
            """,
            (
                str(settings["rag_embedding_model"]),
                int(settings["rag_embedding_dim"]),
                account_wxid,
                conversation_id,
            ),
        ).fetchall()
        docs = []
        for row in rows:
            item = dict(row)
            docs.append(
                {
                    "_existing_document_id": int(item["id"]),
                    "content": item.get("content") or "",
                }
            )
        return docs

    def _count_indexed_documents(self, account_wxid: str, conversation_id: int) -> int:
        row = self.store.conn.execute(
            """
            SELECT COUNT(*) AS count
            FROM rag_documents
            WHERE account_wxid = ?
              AND conversation_id = ?
              AND enabled = 1
              AND superseded_by IS NULL
            """,
            (account_wxid, conversation_id),
        ).fetchone()
        return int(row["count"] if row else 0)

    def _can_retry_failed_status(self, status: dict[str, Any]) -> bool:
        last_error = str(status.get("last_error") or "").lower()
        if "embedding" not in last_error and "模型缺失" not in last_error and "模型" not in last_error:
            return False
        try:
            self.embedding_service.ensure_available()
            return True
        except RagEmbeddingUnavailable:
            return False
        except Exception:
            return False


class RagIndexQueue:
    """Best-effort coalescing background index queue."""

    _lock = threading.Lock()
    _pending: set[tuple[str, int]] = set()
    _worker: threading.Thread | None = None

    @classmethod
    def mark_dirty(cls, account_wxid: str, conversation_id: int | None) -> None:
        if not account_wxid or not conversation_id:
            return
        try:
            RagStore(get_db()).mark_dirty(account_wxid, int(conversation_id))
            get_db().commit()
        except Exception as exc:
            logger.debug("[RAG] mark dirty skipped: %s", exc)
        with cls._lock:
            cls._pending.add((account_wxid, int(conversation_id)))
            if cls._worker is None or not cls._worker.is_alive():
                cls._worker = threading.Thread(target=cls._run, daemon=True)
                cls._worker.start()

    @classmethod
    def enqueue(cls, account_wxid: str, conversation_id: int | None) -> None:
        if not account_wxid or not conversation_id:
            return
        with cls._lock:
            cls._pending.add((account_wxid, int(conversation_id)))
            if cls._worker is None or not cls._worker.is_alive():
                cls._worker = threading.Thread(target=cls._run, daemon=True)
                cls._worker.start()

    @classmethod
    def _run(cls) -> None:
        time.sleep(0.8)
        while True:
            with cls._lock:
                if not cls._pending:
                    return
                account_wxid, conversation_id = cls._pending.pop()
            try:
                if not load_rag_settings().get("rag_enabled"):
                    continue
                RagIndexer().rebuild_contact_index(
                    account_wxid=account_wxid,
                    conversation_id=conversation_id,
                )
            except Exception as exc:
                logger.debug("[RAG] background index skipped: %s", exc)
