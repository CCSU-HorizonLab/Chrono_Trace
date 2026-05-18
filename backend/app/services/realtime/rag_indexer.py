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
from .rag_store import RagStore


logger = logging.getLogger(__name__)


class RagIndexer:
    """Build a minimal but useful per-contact RAG index."""

    MAX_MESSAGES = 240
    DIALOGUE_CHUNK_SIZE = 8
    SELF_STYLE_LIMIT = 24

    def __init__(
        self,
        store: RagStore | None = None,
        embedding_service: RagEmbeddingService | None = None,
    ):
        self.store = store or RagStore()
        self.embedding_service = embedding_service or RagEmbeddingService()

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
        )
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
        )
        try:
            conversation = self._load_conversation(account_wxid, conversation_id)
            messages = self._load_messages(conversation_id)
            if not conversation or not messages:
                self.store.upsert_status(
                    account_wxid,
                    conversation_id,
                    status="ready",
                    document_count=0,
                    vector_count=0,
                    dirty_since=None,
                )
                self.store.conn.commit()
                return self.store.get_status(account_wxid, conversation_id) or {}

            docs = self._build_documents(account_wxid, conversation_id, conversation, messages)
            if not docs:
                self.store.upsert_status(
                    account_wxid,
                    conversation_id,
                    status="ready",
                    document_count=0,
                    vector_count=0,
                    dirty_since=None,
                )
                self.store.conn.commit()
                return self.store.get_status(account_wxid, conversation_id) or {}

            vectors = self.embedding_service.embed_texts([doc["content"] for doc in docs])
            for doc, vector in zip(docs, vectors):
                document_id = self.store.upsert_document(**doc)
                self.store.upsert_embedding(
                    document_id=document_id,
                    account_wxid=account_wxid,
                    conversation_id=conversation_id,
                    embedding_model=model,
                    embedding_dim=dim,
                    vector=vector,
                    embedding_provider="local",
                )

            self.store.upsert_status(
                account_wxid,
                conversation_id,
                status="ready",
                embedding_model=model,
                embedding_dim=dim,
                privacy_mode=privacy_mode,
                document_count=len(docs),
                vector_count=len(vectors),
                dirty_since=None,
                last_error=None,
            )
            self.store.conn.commit()
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
            ORDER BY timestamp DESC, id DESC
            LIMIT ?
            """,
            (conversation_id, self.MAX_MESSAGES),
        ).fetchall()
        return [dict(row) for row in reversed(rows)]

    def _build_documents(
        self,
        account_wxid: str,
        conversation_id: int,
        conversation: dict[str, Any],
        messages: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        redactor = PrivacyRedactor(self.store.conn)
        docs: list[dict[str, Any]] = []
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
                metadata={"display_name": display_name},
            )
        )

        for chunk_index, chunk in enumerate(self._chunks(messages, self.DIALOGUE_CHUNK_SIZE), 1):
            rendered = []
            for msg in chunk:
                sender = "我" if int(msg.get("is_sender") or 0) else "对方"
                content = self._compact_content(msg.get("content"))
                if content:
                    rendered.append(f"{sender}: {content}")
            if not rendered:
                continue
            content = "\n".join(rendered)
            sensitivity = "sensitive" if self._looks_sensitive(content) else "normal"
            docs.append(
                self._doc_payload(
                    redactor,
                    account_wxid,
                    conversation_id,
                    "dialogue_turn",
                    content,
                    "messages",
                    f"chunk:{chunk_index}:{chunk[0]['id']}:{chunk[-1]['id']}",
                    int(chunk[-1].get("timestamp") or 0),
                    sensitivity=sensitivity,
                    metadata={"message_ids": [int(item["id"]) for item in chunk]},
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
                    metadata={"style_sample": True},
                )
            )

        memory_docs = self._extract_shared_memories(messages)
        for index, memory in enumerate(memory_docs, 1):
            docs.append(
                self._doc_payload(
                    redactor,
                    account_wxid,
                    conversation_id,
                    "shared_memory",
                    memory["content"],
                    "messages",
                    f"memory:{index}:{memory['source_id']}",
                    int(memory["source_ts"]),
                    sensitivity=memory["sensitivity"],
                    metadata={
                        "confidence": memory["confidence"],
                        "subject": memory["subject"],
                        "object": memory["object"],
                    },
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
            "metadata": metadata or {},
            "sensitivity": sensitivity,
        }

    def _chunks(self, messages: list[dict[str, Any]], size: int) -> list[list[dict[str, Any]]]:
        return [messages[index:index + size] for index in range(0, len(messages), size)]

    def _compact_content(self, content: Any) -> str:
        text = re.sub(r"\s+", " ", str(content or "")).strip()
        return text[:180]

    def _is_style_sample(self, content: Any) -> bool:
        text = self._compact_content(content)
        return 1 <= len(text) <= 80 and not self._looks_sensitive(text)

    def _looks_sensitive(self, text: str) -> bool:
        keywords = ("秘密", "保密", "身份证", "银行卡", "密码", "密钥", "住址", "地址", "电话")
        return any(keyword in str(text or "") for keyword in keywords)

    def _extract_shared_memories(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        memories: list[dict[str, Any]] = []
        memory_markers = ("记得", "上次", "那次", "一起", "说好", "答应", "喜欢", "不喜欢")
        for msg in messages:
            content = self._compact_content(msg.get("content"))
            if not content or not any(marker in content for marker in memory_markers):
                continue
            memories.append(
                {
                    "content": content,
                    "source_id": msg.get("id"),
                    "source_ts": msg.get("timestamp") or 0,
                    "sensitivity": "sensitive" if self._looks_sensitive(content) else "normal",
                    "confidence": 0.55,
                    "subject": "我" if int(msg.get("is_sender") or 0) else "对方",
                    "object": "对方" if int(msg.get("is_sender") or 0) else "我",
                }
            )
            if len(memories) >= 12:
                break
        return memories


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
