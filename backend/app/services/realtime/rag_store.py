"""Data access layer for contact-scoped realtime suggestion RAG."""

from __future__ import annotations

import json
import pickle
import time
from typing import Any

from ...db.connection import get_db
from .rag_config import RAG_DEFAULTS


INDEX_STATUSES = {"pending", "indexing", "ready", "stale", "failed"}


def _now() -> int:
    return int(time.time())


class RagStore:
    """Small SQLite-backed store for RAG documents, vectors, status and logs."""

    def __init__(self, conn: Any | None = None):
        self.conn = conn or get_db()
        self.ensure_schema()

    def ensure_schema(self) -> None:
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS rag_documents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                account_wxid TEXT NOT NULL,
                conversation_id INTEGER NOT NULL,
                doc_type TEXT NOT NULL,
                source_table TEXT,
                source_id TEXT,
                source_ts INTEGER,
                content TEXT NOT NULL,
                redacted_content TEXT,
                entity_map_json TEXT,
                pii_flags_json TEXT,
                metadata_json TEXT,
                sensitivity TEXT DEFAULT 'normal',
                enabled INTEGER DEFAULT 1,
                superseded_by INTEGER,
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL,
                UNIQUE(account_wxid, conversation_id, doc_type, source_table, source_id)
            )
            """
        )
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS rag_embeddings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                document_id INTEGER NOT NULL,
                account_wxid TEXT NOT NULL,
                conversation_id INTEGER NOT NULL,
                embedding_model TEXT NOT NULL,
                embedding_dim INTEGER NOT NULL,
                embedding_provider TEXT DEFAULT 'local',
                vector_blob BLOB NOT NULL,
                created_at INTEGER NOT NULL,
                UNIQUE(document_id, embedding_model, embedding_dim)
            )
            """
        )
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS rag_index_status (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                account_wxid TEXT NOT NULL,
                conversation_id INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                embedding_model TEXT NOT NULL,
                embedding_dim INTEGER NOT NULL,
                privacy_mode TEXT NOT NULL DEFAULT 'balanced',
                document_count INTEGER DEFAULT 0,
                vector_count INTEGER DEFAULT 0,
                dirty_since INTEGER,
                last_indexed_at INTEGER,
                last_error TEXT,
                storage_bytes INTEGER DEFAULT 0,
                enabled INTEGER DEFAULT 1,
                updated_at INTEGER NOT NULL,
                UNIQUE(account_wxid, conversation_id)
            )
            """
        )
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS rag_retrieval_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                account_wxid TEXT NOT NULL,
                conversation_id INTEGER,
                suggestion_id INTEGER,
                query_text TEXT,
                document_ids_json TEXT,
                retrieval_scores_json TEXT,
                index_status TEXT,
                elapsed_ms INTEGER DEFAULT 0,
                timed_out INTEGER DEFAULT 0,
                degraded INTEGER DEFAULT 0,
                degrade_reason TEXT,
                redaction_status TEXT DEFAULT 'redacted',
                redaction_disabled INTEGER DEFAULT 0,
                redaction_fallback INTEGER DEFAULT 0,
                remote_model INTEGER DEFAULT 0,
                created_at INTEGER NOT NULL
            )
            """
        )

    def get_status(self, account_wxid: str, conversation_id: int) -> dict[str, Any] | None:
        row = self.conn.execute(
            """
            SELECT *
            FROM rag_index_status
            WHERE account_wxid = ? AND conversation_id = ?
            LIMIT 1
            """,
            (account_wxid, conversation_id),
        ).fetchone()
        return dict(row) if row else None

    def upsert_status(
        self,
        account_wxid: str,
        conversation_id: int,
        *,
        status: str,
        embedding_model: str | None = None,
        embedding_dim: int | None = None,
        privacy_mode: str | None = None,
        document_count: int | None = None,
        vector_count: int | None = None,
        dirty_since: int | None = None,
        last_error: str | None = None,
        enabled: bool | None = None,
    ) -> None:
        if status not in INDEX_STATUSES:
            raise ValueError(f"invalid RAG index status: {status}")
        current = self.get_status(account_wxid, conversation_id) or {}
        model = embedding_model or current.get("embedding_model") or RAG_DEFAULTS["rag_embedding_model"]
        dim = int(embedding_dim or current.get("embedding_dim") or RAG_DEFAULTS["rag_embedding_dim"])
        mode = privacy_mode or current.get("privacy_mode") or RAG_DEFAULTS["rag_privacy_mode"]
        now = _now()
        self.conn.execute(
            """
            INSERT INTO rag_index_status
            (account_wxid, conversation_id, status, embedding_model, embedding_dim, privacy_mode,
             document_count, vector_count, dirty_since, last_indexed_at, last_error, storage_bytes, enabled, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(account_wxid, conversation_id) DO UPDATE SET
                status = excluded.status,
                embedding_model = excluded.embedding_model,
                embedding_dim = excluded.embedding_dim,
                privacy_mode = excluded.privacy_mode,
                document_count = COALESCE(excluded.document_count, rag_index_status.document_count),
                vector_count = COALESCE(excluded.vector_count, rag_index_status.vector_count),
                dirty_since = excluded.dirty_since,
                last_indexed_at = excluded.last_indexed_at,
                last_error = excluded.last_error,
                storage_bytes = excluded.storage_bytes,
                enabled = excluded.enabled,
                updated_at = excluded.updated_at
            """,
            (
                account_wxid,
                conversation_id,
                status,
                model,
                dim,
                mode,
                document_count if document_count is not None else current.get("document_count"),
                vector_count if vector_count is not None else current.get("vector_count"),
                dirty_since,
                now if status == "ready" else current.get("last_indexed_at"),
                last_error,
                self.estimate_storage_bytes(account_wxid, conversation_id),
                int(enabled if enabled is not None else current.get("enabled", 1)),
                now,
            ),
        )

    def mark_stale_for_config_change(
        self,
        account_wxid: str,
        *,
        embedding_model: str,
        embedding_dim: int,
        privacy_mode: str,
    ) -> int:
        cursor = self.conn.execute(
            """
            UPDATE rag_index_status
            SET status = 'stale', updated_at = ?, dirty_since = COALESCE(dirty_since, ?)
            WHERE account_wxid = ?
              AND status = 'ready'
              AND (embedding_model != ? OR embedding_dim != ? OR privacy_mode != ?)
            """,
            (_now(), _now(), account_wxid, embedding_model, int(embedding_dim), privacy_mode),
        )
        return int(cursor.rowcount or 0)

    def mark_dirty(self, account_wxid: str, conversation_id: int) -> None:
        current = self.get_status(account_wxid, conversation_id)
        status = "stale" if current and current.get("status") in {"ready", "stale"} else "pending"
        self.upsert_status(
            account_wxid,
            conversation_id,
            status=status,
            dirty_since=_now(),
            enabled=bool((current or {}).get("enabled", 1)),
        )

    def upsert_document(
        self,
        *,
        account_wxid: str,
        conversation_id: int,
        doc_type: str,
        content: str,
        source_table: str = "runtime",
        source_id: str = "",
        source_ts: int | None = None,
        redacted_content: str | None = None,
        entity_map_json: str | None = None,
        pii_flags_json: str | None = None,
        metadata: dict[str, Any] | None = None,
        sensitivity: str = "normal",
        enabled: bool = True,
    ) -> int:
        now = _now()
        cursor = self.conn.execute(
            """
            INSERT INTO rag_documents
            (account_wxid, conversation_id, doc_type, source_table, source_id, source_ts,
             content, redacted_content, entity_map_json, pii_flags_json, metadata_json,
             sensitivity, enabled, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(account_wxid, conversation_id, doc_type, source_table, source_id)
            DO UPDATE SET
                source_ts = excluded.source_ts,
                content = excluded.content,
                redacted_content = excluded.redacted_content,
                entity_map_json = excluded.entity_map_json,
                pii_flags_json = excluded.pii_flags_json,
                metadata_json = excluded.metadata_json,
                sensitivity = excluded.sensitivity,
                enabled = excluded.enabled,
                updated_at = excluded.updated_at
            """,
            (
                account_wxid,
                conversation_id,
                doc_type,
                source_table,
                str(source_id),
                source_ts,
                content,
                redacted_content,
                entity_map_json,
                pii_flags_json,
                json.dumps(metadata or {}, ensure_ascii=False, sort_keys=True),
                sensitivity,
                int(enabled),
                now,
                now,
            ),
        )
        if cursor.lastrowid:
            return int(cursor.lastrowid)
        row = self.conn.execute(
            """
            SELECT id FROM rag_documents
            WHERE account_wxid = ? AND conversation_id = ? AND doc_type = ?
              AND source_table = ? AND source_id = ?
            LIMIT 1
            """,
            (account_wxid, conversation_id, doc_type, source_table, str(source_id)),
        ).fetchone()
        return int(row["id"])

    def upsert_embedding(
        self,
        *,
        document_id: int,
        account_wxid: str,
        conversation_id: int,
        embedding_model: str,
        embedding_dim: int,
        vector: list[float],
        embedding_provider: str = "local",
    ) -> None:
        safe_vector = [float(item) for item in vector[:embedding_dim]]
        if len(safe_vector) < embedding_dim:
            safe_vector.extend([0.0] * (embedding_dim - len(safe_vector)))
        self.conn.execute(
            """
            INSERT INTO rag_embeddings
            (document_id, account_wxid, conversation_id, embedding_model, embedding_dim,
             embedding_provider, vector_blob, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(document_id, embedding_model, embedding_dim) DO UPDATE SET
                vector_blob = excluded.vector_blob,
                embedding_provider = excluded.embedding_provider,
                created_at = excluded.created_at
            """,
            (
                document_id,
                account_wxid,
                conversation_id,
                embedding_model,
                int(embedding_dim),
                embedding_provider,
                pickle.dumps(safe_vector),
                _now(),
            ),
        )

    def list_documents(self, account_wxid: str, conversation_id: int) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            """
            SELECT *
            FROM rag_documents
            WHERE account_wxid = ? AND conversation_id = ?
              AND enabled = 1
              AND superseded_by IS NULL
            ORDER BY source_ts DESC, updated_at DESC
            """,
            (account_wxid, conversation_id),
        ).fetchall()
        return [dict(row) for row in rows]

    def list_documents_with_vectors(
        self,
        account_wxid: str,
        conversation_id: int,
        *,
        embedding_model: str,
        embedding_dim: int,
    ) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            """
            SELECT d.*, e.vector_blob
            FROM rag_documents d
            INNER JOIN rag_embeddings e ON e.document_id = d.id
            WHERE d.account_wxid = ? AND d.conversation_id = ?
              AND e.embedding_model = ? AND e.embedding_dim = ?
              AND d.enabled = 1
              AND d.superseded_by IS NULL
            ORDER BY d.source_ts DESC, d.updated_at DESC
            """,
            (account_wxid, conversation_id, embedding_model, int(embedding_dim)),
        ).fetchall()
        items = []
        for row in rows:
            item = dict(row)
            try:
                item["vector"] = pickle.loads(item.pop("vector_blob"))
            except Exception:
                item["vector"] = []
            items.append(item)
        return items

    def clear_conversation(self, account_wxid: str, conversation_id: int) -> int:
        self.conn.execute(
            "DELETE FROM rag_embeddings WHERE account_wxid = ? AND conversation_id = ?",
            (account_wxid, conversation_id),
        )
        cursor = self.conn.execute(
            "DELETE FROM rag_documents WHERE account_wxid = ? AND conversation_id = ?",
            (account_wxid, conversation_id),
        )
        self.conn.execute(
            "DELETE FROM rag_index_status WHERE account_wxid = ? AND conversation_id = ?",
            (account_wxid, conversation_id),
        )
        return int(cursor.rowcount or 0)

    def set_conversation_enabled(self, account_wxid: str, conversation_id: int, enabled: bool) -> None:
        current = self.get_status(account_wxid, conversation_id)
        self.upsert_status(
            account_wxid,
            conversation_id,
            status=str((current or {}).get("status") or "pending"),
            enabled=enabled,
        )

    def estimate_storage_bytes(self, account_wxid: str, conversation_id: int) -> int:
        row = self.conn.execute(
            """
            SELECT
                COALESCE(SUM(LENGTH(content)), 0)
                + COALESCE(SUM(LENGTH(redacted_content)), 0)
                + (
                    SELECT COALESCE(SUM(LENGTH(vector_blob)), 0)
                    FROM rag_embeddings e
                    WHERE e.account_wxid = ? AND e.conversation_id = ?
                  ) AS bytes
            FROM rag_documents
            WHERE account_wxid = ? AND conversation_id = ?
            """,
            (account_wxid, conversation_id, account_wxid, conversation_id),
        ).fetchone()
        return int(row["bytes"] if row else 0)

    def insert_retrieval_log(self, **payload: Any) -> int:
        cursor = self.conn.execute(
            """
            INSERT INTO rag_retrieval_logs
            (account_wxid, conversation_id, suggestion_id, query_text, document_ids_json,
             retrieval_scores_json, index_status, elapsed_ms, timed_out, degraded,
             degrade_reason, redaction_status, redaction_disabled, redaction_fallback,
             remote_model, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                payload.get("account_wxid") or "",
                payload.get("conversation_id"),
                payload.get("suggestion_id"),
                payload.get("query_text"),
                json.dumps(payload.get("document_ids") or [], ensure_ascii=False),
                json.dumps(payload.get("retrieval_scores") or {}, ensure_ascii=False, sort_keys=True),
                payload.get("index_status"),
                int(payload.get("elapsed_ms") or 0),
                int(bool(payload.get("timed_out"))),
                int(bool(payload.get("degraded"))),
                payload.get("degrade_reason"),
                payload.get("redaction_status") or "redacted",
                int(bool(payload.get("redaction_disabled"))),
                int(bool(payload.get("redaction_fallback"))),
                int(bool(payload.get("remote_model"))),
                _now(),
            ),
        )
        return int(cursor.lastrowid)

    def attach_log_to_suggestion(self, log_id: int | None, suggestion_id: int) -> None:
        if not log_id:
            return
        self.conn.execute(
            "UPDATE rag_retrieval_logs SET suggestion_id = ? WHERE id = ?",
            (int(suggestion_id), int(log_id)),
        )
