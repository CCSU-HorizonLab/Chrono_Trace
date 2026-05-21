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
            for fact_index, fact in enumerate(self.segmenter.build_fact_memories(segment), 1):
                fact_metadata = self._metadata(
                    segment,
                    source_kind="historical",
                    summary_method="rules",
                    extra={
                        "fact_source_id": fact.get("source_id"),
                        "subject": fact.get("subject"),
                        "topics": fact.get("topics") or segment.topics,
                        "entities": fact.get("entities") or segment.entities,
                    },
                )
                docs.append(
                    self._doc_payload(
                        redactor,
                        account_wxid,
                        conversation_id,
                        "fact_memory",
                        f"时间：{segment.time_label}\n{fact['content']}",
                        "messages",
                        f"fact:{index}:{fact_index}:{fact.get('source_id')}",
                        int(fact.get("source_ts") or segment.end_ts),
                        sensitivity="sensitive" if self._looks_sensitive(fact["content"]) else "normal",
                        metadata=fact_metadata,
                    )
                )

        self_messages = [
            self._compact_content(msg.get("content"))
            for msg in messages
            if int(msg.get("is_sender") or 0) and self._is_style_sample(msg.get("content"))
        ][: self.SELF_STYLE_LIMIT]
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
                        extra={"style_sample": True},
                    ),
                )
            )

        style_lines = [self._compact_content(msg.get("content")) for msg in messages if int(msg.get("is_sender") or 0)]
        if style_lines:
            communication_style = "用户常见表达样例：" + " / ".join(style_lines[:8])
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
                        extra={"style_sample": True},
                    ),
                )
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
        return 1 <= len(text) <= 80 and not self._looks_sensitive(text)

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
