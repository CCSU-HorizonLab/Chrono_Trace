"""Data access layer for contact-scoped realtime suggestion RAG."""

from __future__ import annotations

import json
import pickle
import time
from typing import Any

from ....db.connection import get_db
from .config import RAG_DEFAULTS
from .semantic_memory import CONFIDENCE_CEILING, CONFIRMATION_STEP


INDEX_STATUSES = {"pending", "indexing", "ready", "stale", "failed"}
RAG_INDEX_VERSION = "rag_v3"
_UNSET = object()


def _now() -> int:
    return int(time.time())


class RagStore:
    """Small SQLite-backed store for RAG documents, vectors, status and logs."""

    def rag_data_stamp(self, account_wxid: str, conversation_id: int) -> tuple:
        """范围数据版本戳（供检索向量缓存判定新鲜度）。

        覆盖文档/事实/两侧向量的行数与最近更新时间——任何未被显式失效
        钩子覆盖的突变也会改变戳，缓存自然失效。两条轻量聚合查询。
        """
        row = self.conn.execute(
            """
            SELECT
              (SELECT COUNT(*) FROM rag_documents
                 WHERE account_wxid = ? AND conversation_id = ?),
              (SELECT COALESCE(SUM(updated_at + id), 0) FROM rag_documents
                 WHERE account_wxid = ? AND conversation_id = ?),
              (SELECT COALESCE(SUM(LENGTH(content)), 0) FROM rag_documents
                 WHERE account_wxid = ? AND conversation_id = ?),
              (SELECT COUNT(*) FROM rag_facts
                 WHERE account_wxid = ? AND conversation_id = ?),
              (SELECT COALESCE(SUM(updated_at + id), 0) FROM rag_facts
                 WHERE account_wxid = ? AND conversation_id = ?),
              (SELECT COALESCE(SUM(LENGTH(content)), 0) FROM rag_facts
                 WHERE account_wxid = ? AND conversation_id = ?),
              (SELECT COUNT(*) FROM rag_embeddings
                 WHERE account_wxid = ? AND conversation_id = ?),
              (SELECT COALESCE(SUM(id), 0) FROM rag_embeddings
                 WHERE account_wxid = ? AND conversation_id = ?),
              (SELECT COALESCE(SUM(LENGTH(vector_blob)), 0) FROM rag_embeddings
                 WHERE account_wxid = ? AND conversation_id = ?),
              (SELECT COUNT(*) FROM rag_fact_embeddings
                 WHERE account_wxid = ? AND conversation_id = ?),
              (SELECT COALESCE(SUM(id), 0) FROM rag_fact_embeddings
                 WHERE account_wxid = ? AND conversation_id = ?),
              (SELECT COALESCE(SUM(LENGTH(vector_blob)), 0) FROM rag_fact_embeddings
                 WHERE account_wxid = ? AND conversation_id = ?)
            """,
            tuple([account_wxid, int(conversation_id)]) * 12,
        ).fetchone()
        return tuple(int(v or 0) for v in row)

    def prune_retrieval_logs(self, days: int = 90) -> int:
        """清理过期检索审计日志（append-only 表无界增长治理），返回删除行数。"""
        try:
            cutoff = int(time.time()) - int(days) * 86400
            cur = self.conn.execute(
                "DELETE FROM rag_retrieval_logs WHERE created_at < ?", (cutoff,)
            )
            self.conn.commit()
            return cur.rowcount if cur.rowcount and cur.rowcount > 0 else 0
        except Exception as exc:
            logger.debug("[RAG] retrieval logs prune skipped: %s", exc)
            return 0

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
                index_version TEXT DEFAULT 'v1',
                source_kind TEXT DEFAULT 'historical',
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
                fact_read_mode TEXT DEFAULT 'inherit',
                index_version TEXT DEFAULT 'v1',
                updated_at INTEGER NOT NULL,
                UNIQUE(account_wxid, conversation_id)
            )
            """
        )
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS rag_facts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                account_wxid TEXT NOT NULL,
                conversation_id INTEGER NOT NULL,
                subject TEXT NOT NULL DEFAULT '',
                kind TEXT NOT NULL,
                content TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'active',
                as_of INTEGER,
                valid_from INTEGER,
                valid_to INTEGER,
                confidence REAL DEFAULT 0,
                sensitivity TEXT DEFAULT 'normal',
                enabled INTEGER NOT NULL DEFAULT 1,
                evidence_message_ids_json TEXT,
                source_window_json TEXT,
                summary_method TEXT DEFAULT 'shadow',
                supersedes_fact_id INTEGER,
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL,
                UNIQUE(account_wxid, conversation_id, kind, content)
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
                memory_intent_mode TEXT,
                memory_intent_confidence REAL DEFAULT 0,
                memory_intent_query TEXT,
                memory_intent_reason TEXT,
                rag_enabled INTEGER DEFAULT 0,
                rag_retrieved INTEGER DEFAULT 0,
                rag_hit_count INTEGER DEFAULT 0,
                rag_injection_mode TEXT DEFAULT 'none',
                rag_no_hit_guard INTEGER DEFAULT 0,
                rag_latency_ms INTEGER DEFAULT 0,
                rag_degraded_reason TEXT,
                rag_gate_decision TEXT,
                rag_gate_reason TEXT,
                rag_top_score REAL DEFAULT 0,
                rag_strategy TEXT,
                index_version TEXT,
                selected_doc_types_json TEXT,
                top_doc_time_label TEXT,
                query_expanded_terms_json TEXT,
                no_hit_reason TEXT,
                task_relevance_score REAL DEFAULT 0,
                off_topic_rejected_count INTEGER DEFAULT 0,
                semantic_fact_count INTEGER DEFAULT 0,
                style_sample_count INTEGER DEFAULT 0,
                rerank_reason TEXT,
                retrieval_source TEXT,
                fact_ids_json TEXT,
                evidence_ids_json TEXT,
                query_scope TEXT,
                supersession_decision TEXT,
                run_provenance TEXT DEFAULT 'production',
                candidate_ids_json TEXT,
                injected_item_ids_json TEXT,
                hot_context_only INTEGER DEFAULT 0,
                prompt_context_hash TEXT,
                policy_ids_json TEXT,
                created_at INTEGER NOT NULL
            )
            """
        )
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS rag_fact_embeddings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                fact_id INTEGER NOT NULL,
                account_wxid TEXT NOT NULL,
                conversation_id INTEGER NOT NULL,
                embedding_model TEXT NOT NULL,
                embedding_dim INTEGER NOT NULL,
                embedding_provider TEXT DEFAULT 'local',
                vector_blob BLOB NOT NULL,
                created_at INTEGER NOT NULL,
                UNIQUE(fact_id, embedding_model, embedding_dim)
            )
            """
        )
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS rag_fact_user_feedback (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                account_wxid TEXT NOT NULL,
                conversation_id INTEGER,
                fact_id INTEGER NOT NULL,
                action TEXT NOT NULL,
                reason TEXT,
                created_at INTEGER NOT NULL,
                UNIQUE(fact_id)
            )
            """
        )
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS rag_relationship_state (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                account_wxid TEXT NOT NULL,
                conversation_id INTEGER NOT NULL,
                stage TEXT NOT NULL,
                closeness_band TEXT NOT NULL,
                initiative_pattern TEXT NOT NULL,
                boundary_summary TEXT,
                communication_tips TEXT,
                relationship_note TEXT,
                evidence_hash TEXT,
                evidence_fact_ids_json TEXT,
                evidence_message_ids_json TEXT,
                confidence REAL DEFAULT 0.0,
                sensitivity TEXT DEFAULT 'normal',
                policy_version TEXT NOT NULL,
                summary_method TEXT DEFAULT 'derived_shadow',
                valid_from INTEGER,
                valid_to INTEGER,
                supersedes_state_id INTEGER,
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL
            )
            """
        )
        self.conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_rag_relationship_state_scope
            ON rag_relationship_state(account_wxid, conversation_id, created_at DESC)
            """
        )
        # 审计大宽表（53 列 append-only）：按范围查/清都走这个索引
        self.conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_rag_retrieval_logs_scope
            ON rag_retrieval_logs(account_wxid, conversation_id, created_at DESC)
            """
        )
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS rag_contact_preferences (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                account_wxid TEXT NOT NULL,
                conversation_id INTEGER NOT NULL,
                slot_key TEXT NOT NULL,
                slot_kind TEXT NOT NULL,
                summary TEXT NOT NULL,
                evidence_hash TEXT,
                evidence_fact_ids_json TEXT,
                evidence_message_ids_json TEXT,
                support_count INTEGER DEFAULT 1,
                confidence REAL DEFAULT 0.0,
                sensitivity TEXT DEFAULT 'normal',
                policy_version TEXT NOT NULL,
                valid_from INTEGER,
                valid_to INTEGER,
                supersedes_pref_id INTEGER,
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL
            )
            """
        )
        self.conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_rag_contact_preferences_scope
            ON rag_contact_preferences(account_wxid, conversation_id, created_at DESC)
            """
        )
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS rag_feedback_policy_signals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                account_wxid TEXT NOT NULL,
                conversation_id INTEGER,
                fact_id INTEGER,
                suggestion_id INTEGER,
                action TEXT NOT NULL,
                signal_kind TEXT NOT NULL DEFAULT 'fact_feedback',
                affected_policy_ids_json TEXT,
                outcome TEXT,
                retrieval_log_id INTEGER,
                detail_json TEXT,
                created_at INTEGER NOT NULL
            )
            """
        )
        self.conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_rag_feedback_policy_signals_scope
            ON rag_feedback_policy_signals(account_wxid, conversation_id, created_at DESC)
            """
        )
        self._ensure_document_columns()
        self._ensure_status_columns()
        self._ensure_retrieval_log_columns()

    def _ensure_document_columns(self) -> None:
        existing = set()
        for row in self.conn.execute("PRAGMA table_info(rag_documents)").fetchall():
            try:
                existing.add(str(row["name"]))
            except Exception:
                existing.add(str(row[1]))
        columns = {
            "index_version": "TEXT DEFAULT 'v1'",
            "source_kind": "TEXT DEFAULT 'historical'",
        }
        for name, definition in columns.items():
            if name not in existing:
                self.conn.execute(f"ALTER TABLE rag_documents ADD COLUMN {name} {definition}")
        fact_columns = set()
        for row in self.conn.execute("PRAGMA table_info(rag_facts)").fetchall():
            try:
                fact_columns.add(str(row["name"]))
            except Exception:
                fact_columns.add(str(row[1]))
        if "enabled" not in fact_columns:
            self.conn.execute("ALTER TABLE rag_facts ADD COLUMN enabled INTEGER NOT NULL DEFAULT 1")

    def _ensure_status_columns(self) -> None:
        existing = set()
        for row in self.conn.execute("PRAGMA table_info(rag_index_status)").fetchall():
            try:
                existing.add(str(row["name"]))
            except Exception:
                existing.add(str(row[1]))
        columns = {
            "index_version": "TEXT DEFAULT 'v1'",
            "fact_read_mode": "TEXT DEFAULT 'inherit'",
            # P1.5 断点续抽段级进度：最后成功处理（含零事实）的段末时间戳，
            # 及抽取 prompt 版本（版本变化时水位失效全量重抽）
            "fact_extract_watermark_ts": "INTEGER",
            "fact_extract_prompt_version": "TEXT",
            # 文档/语义嵌入的消息级水位（真增量：只处理新增消息，不重嵌旧段）
            "message_watermark_ts": "INTEGER",
        }
        for name, definition in columns.items():
            if name not in existing:
                self.conn.execute(f"ALTER TABLE rag_index_status ADD COLUMN {name} {definition}")

    def set_fact_extract_progress(
        self,
        account_wxid: str,
        conversation_id: int,
        *,
        watermark_ts: int,
        prompt_version: str,
    ) -> None:
        """Persist per-segment LLM extraction progress (P1.5).

        只更新进度两列，不触碰索引状态本体；调用方随事务提交。
        """
        self.conn.execute(
            """
            UPDATE rag_index_status
               SET fact_extract_watermark_ts = ?,
                   fact_extract_prompt_version = ?,
                   updated_at = ?
             WHERE account_wxid = ? AND conversation_id = ?
            """,
            (int(watermark_ts), str(prompt_version), _now(), account_wxid, int(conversation_id)),
        )

    def _ensure_retrieval_log_columns(self) -> None:
        existing = set()
        for row in self.conn.execute("PRAGMA table_info(rag_retrieval_logs)").fetchall():
            try:
                existing.add(str(row["name"]))
            except Exception:
                existing.add(str(row[1]))
        columns = {
            "memory_intent_mode": "TEXT",
            "memory_intent_confidence": "REAL DEFAULT 0",
            "memory_intent_query": "TEXT",
            "memory_intent_reason": "TEXT",
            "rag_enabled": "INTEGER DEFAULT 0",
            "rag_retrieved": "INTEGER DEFAULT 0",
            "rag_hit_count": "INTEGER DEFAULT 0",
            "rag_injection_mode": "TEXT DEFAULT 'none'",
            "rag_no_hit_guard": "INTEGER DEFAULT 0",
            "rag_latency_ms": "INTEGER DEFAULT 0",
            "rag_degraded_reason": "TEXT",
            "rag_gate_decision": "TEXT",
            "rag_gate_reason": "TEXT",
            "rag_top_score": "REAL DEFAULT 0",
            "rag_strategy": "TEXT",
            "index_version": "TEXT",
            "selected_doc_types_json": "TEXT",
            "top_doc_time_label": "TEXT",
            "query_expanded_terms_json": "TEXT",
            "no_hit_reason": "TEXT",
            "task_relevance_score": "REAL DEFAULT 0",
            "off_topic_rejected_count": "INTEGER DEFAULT 0",
            "semantic_fact_count": "INTEGER DEFAULT 0",
            "style_sample_count": "INTEGER DEFAULT 0",
            "rerank_reason": "TEXT",
            "retrieval_source": "TEXT",
            "fact_ids_json": "TEXT",
            "evidence_ids_json": "TEXT",
            "query_scope": "TEXT",
            "supersession_decision": "TEXT",
            "run_provenance": "TEXT DEFAULT 'production'",
            "candidate_ids_json": "TEXT",
            "injected_item_ids_json": "TEXT",
            "hot_context_only": "INTEGER DEFAULT 0",
            "prompt_context_hash": "TEXT",
            "policy_ids_json": "TEXT",
            "contact_preference_ids_json": "TEXT",
            # P0.1 漏斗完整性：触发段（ambient/manual_request/direct_reply）
            "trigger_type": "TEXT",
        }
        for name, definition in columns.items():
            if name not in existing:
                self.conn.execute(f"ALTER TABLE rag_retrieval_logs ADD COLUMN {name} {definition}")

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
        dirty_since: int | None | object = _UNSET,
        last_error: str | None | object = _UNSET,
        enabled: bool | None = None,
        fact_read_mode: str | None = None,
        index_version: str | None = None,
    ) -> None:
        if status not in INDEX_STATUSES:
            raise ValueError(f"invalid RAG index status: {status}")
        current = self.get_status(account_wxid, conversation_id) or {}
        model = embedding_model or current.get("embedding_model") or RAG_DEFAULTS["rag_embedding_model"]
        dim = int(embedding_dim or current.get("embedding_dim") or RAG_DEFAULTS["rag_embedding_dim"])
        mode = privacy_mode or current.get("privacy_mode") or RAG_DEFAULTS["rag_privacy_mode"]
        resolved_dirty_since = current.get("dirty_since") if dirty_since is _UNSET else dirty_since
        resolved_last_error = current.get("last_error") if last_error is _UNSET else last_error
        resolved_fact_read_mode = fact_read_mode or current.get("fact_read_mode") or "inherit"
        if resolved_fact_read_mode not in {"inherit", "facts", "documents"}:
            raise ValueError(f"invalid fact read mode: {resolved_fact_read_mode}")
        now = _now()
        self.conn.execute(
            """
            INSERT INTO rag_index_status
            (account_wxid, conversation_id, status, embedding_model, embedding_dim, privacy_mode,
             document_count, vector_count, dirty_since, last_indexed_at, last_error, storage_bytes,
             enabled, fact_read_mode, index_version, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                fact_read_mode = excluded.fact_read_mode,
                index_version = excluded.index_version,
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
                resolved_dirty_since,
                now if status == "ready" else current.get("last_indexed_at"),
                resolved_last_error,
                self.estimate_storage_bytes(account_wxid, conversation_id),
                int(enabled if enabled is not None else current.get("enabled", 1)),
                resolved_fact_read_mode,
                index_version or current.get("index_version") or "v1",
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
        index_version: str | None = None,
    ) -> int:
        version_clause = " OR index_version != ?" if index_version else ""
        params: tuple[Any, ...]
        if index_version:
            params = (
                _now(),
                _now(),
                account_wxid,
                embedding_model,
                int(embedding_dim),
                privacy_mode,
                index_version,
            )
        else:
            params = (_now(), _now(), account_wxid, embedding_model, int(embedding_dim), privacy_mode)
        cursor = self.conn.execute(
            f"""
            UPDATE rag_index_status
            SET status = 'stale', updated_at = ?, dirty_since = COALESCE(dirty_since, ?)
            WHERE account_wxid = ?
              AND status = 'ready'
              AND (embedding_model != ? OR embedding_dim != ? OR privacy_mode != ?{version_clause})
            """,
            params,
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
        index_version: str = "v1",
        source_kind: str = "historical",
    ) -> int:
        now = _now()
        cursor = self.conn.execute(
            """
            INSERT INTO rag_documents
            (account_wxid, conversation_id, doc_type, source_table, source_id, source_ts,
             content, redacted_content, entity_map_json, pii_flags_json, metadata_json,
             sensitivity, enabled, index_version, source_kind, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                index_version = excluded.index_version,
                source_kind = excluded.source_kind,
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
                index_version,
                source_kind,
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
        safe_vector = [float(item) for item in vector]
        if len(safe_vector) != int(embedding_dim):
            raise ValueError(
                f"embedding dimension mismatch: vector={len(safe_vector)} configured={embedding_dim}"
            )
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

    def upsert_fact_embedding(
        self,
        *,
        fact_id: int,
        account_wxid: str,
        conversation_id: int,
        embedding_model: str,
        embedding_dim: int,
        vector: list[float],
        embedding_provider: str = "local",
    ) -> None:
        safe_vector = [float(item) for item in vector]
        if len(safe_vector) != int(embedding_dim):
            raise ValueError(
                f"fact embedding dimension mismatch: vector={len(safe_vector)} configured={embedding_dim}"
            )
        self.conn.execute(
            """
            INSERT INTO rag_fact_embeddings
            (fact_id, account_wxid, conversation_id, embedding_model, embedding_dim,
             embedding_provider, vector_blob, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(fact_id, embedding_model, embedding_dim) DO UPDATE SET
                vector_blob = excluded.vector_blob,
                embedding_provider = excluded.embedding_provider,
                created_at = excluded.created_at
            """,
            (
                int(fact_id), account_wxid, int(conversation_id), embedding_model,
                int(embedding_dim), embedding_provider, pickle.dumps(safe_vector), _now(),
            ),
        )

    def list_facts_with_vectors(
        self,
        account_wxid: str,
        conversation_id: int,
        *,
        embedding_model: str,
        embedding_dim: int,
    ) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            """
            SELECT f.*, e.vector_blob
            FROM rag_facts f
            INNER JOIN rag_fact_embeddings e ON e.fact_id = f.id
            WHERE f.account_wxid = ? AND f.conversation_id = ?
              AND f.status = 'active' AND f.enabled = 1
              AND e.embedding_model = ? AND e.embedding_dim = ?
            ORDER BY f.confidence DESC, f.updated_at DESC
            """,
            (account_wxid, int(conversation_id), embedding_model, int(embedding_dim)),
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

    def count_active_facts(self, account_wxid: str, conversation_id: int) -> int:
        row = self.conn.execute(
            """
            SELECT COUNT(*) AS count
            FROM rag_facts
            WHERE account_wxid=? AND conversation_id=?
              AND status='active' AND enabled=1
            """,
            (account_wxid, int(conversation_id)),
        ).fetchone()
        return int(row["count"] if row else 0)

    def count_fact_embeddings(
        self,
        account_wxid: str,
        conversation_id: int,
        *,
        embedding_model: str,
        embedding_dim: int,
    ) -> int:
        row = self.conn.execute(
            """
            SELECT COUNT(*) AS count
            FROM rag_fact_embeddings
            WHERE account_wxid=? AND conversation_id=?
              AND embedding_model=? AND embedding_dim=?
            """,
            (account_wxid, int(conversation_id), embedding_model, int(embedding_dim)),
        ).fetchone()
        return int(row["count"] if row else 0)

    def count_active_fact_embeddings(
        self,
        account_wxid: str,
        conversation_id: int,
        *,
        embedding_model: str,
        embedding_dim: int,
    ) -> int:
        """G5：只数活跃事实的向量，与 count_active_facts 口径对齐。

        旧口径把 superseded/uncertain/禁用事实遗留的向量也算进来，活跃
        事实缺向量时 vectors>=facts 会让回填判定误判"已齐"而跳过。
        """
        row = self.conn.execute(
            """
            SELECT COUNT(*) AS count
            FROM rag_fact_embeddings e
            INNER JOIN rag_facts f ON f.id = e.fact_id
            WHERE e.account_wxid=? AND e.conversation_id=?
              AND e.embedding_model=? AND e.embedding_dim=?
              AND f.status='active' AND f.enabled=1
            """,
            (account_wxid, int(conversation_id), embedding_model, int(embedding_dim)),
        ).fetchone()
        return int(row["count"] if row else 0)

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

    def delete_auto_documents(
        self,
        account_wxid: str,
        conversation_id: int,
        *,
        index_version: str = RAG_INDEX_VERSION,
        source_kinds: tuple[str, ...] = ("historical", "realtime"),
    ) -> int:
        # G2：删除不过滤 index_version——读侧（list_documents*）本就不区分版本，
        # 若只删当前版本，v1/v2 时期遗留的文档+向量会在升级后永久残留并被
        # 重复召回。index_version 参数保留以兼容既有调用方，但不再约束范围。
        placeholders = ",".join("?" for _ in source_kinds)
        rows = self.conn.execute(
            f"""
            SELECT id
            FROM rag_documents
            WHERE account_wxid = ?
              AND conversation_id = ?
              AND source_kind IN ({placeholders})
            """,
            (account_wxid, conversation_id, *source_kinds),
        ).fetchall()
        ids = [int(row["id"]) for row in rows]
        if not ids:
            return 0
        id_placeholders = ",".join("?" for _ in ids)
        self.conn.execute(f"DELETE FROM rag_embeddings WHERE document_id IN ({id_placeholders})", ids)
        cursor = self.conn.execute(f"DELETE FROM rag_documents WHERE id IN ({id_placeholders})", ids)
        return int(cursor.rowcount or 0)

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

    def set_fact_read_mode(self, account_wxid: str, conversation_id: int, mode: str) -> None:
        """Set a per-contact read-side rollout/rollback override.

        ``facts`` prefers active facts with document evidence fallback;
        ``documents`` rolls only this contact back to the legacy document path;
        ``inherit`` follows the global setting.  Fact writes are unaffected.
        """
        mode = str(mode or "").strip().lower()
        if mode not in {"inherit", "facts", "documents"}:
            raise ValueError(f"invalid fact read mode: {mode}")
        current = self.get_status(account_wxid, conversation_id) or {}
        self.upsert_status(
            account_wxid,
            conversation_id,
            status=str(current.get("status") or "pending"),
            fact_read_mode=mode,
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
             remote_model, memory_intent_mode, memory_intent_confidence,
             memory_intent_query, memory_intent_reason, rag_enabled, rag_retrieved,
             rag_hit_count, rag_injection_mode, rag_no_hit_guard, rag_latency_ms,
             rag_degraded_reason, rag_gate_decision, rag_gate_reason, rag_top_score,
             rag_strategy, index_version, selected_doc_types_json, top_doc_time_label,
             query_expanded_terms_json, no_hit_reason, task_relevance_score,
             off_topic_rejected_count, semantic_fact_count, style_sample_count,
             rerank_reason, retrieval_source, fact_ids_json, evidence_ids_json,
             query_scope, supersession_decision, run_provenance, candidate_ids_json,
             injected_item_ids_json, hot_context_only, prompt_context_hash,
             policy_ids_json, contact_preference_ids_json, trigger_type, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                payload.get("memory_intent_mode"),
                float(payload.get("memory_intent_confidence") or 0.0),
                payload.get("memory_intent_query"),
                payload.get("memory_intent_reason"),
                int(bool(payload.get("rag_enabled"))),
                int(bool(payload.get("rag_retrieved"))),
                int(payload.get("rag_hit_count") or 0),
                payload.get("rag_injection_mode") or "none",
                int(bool(payload.get("rag_no_hit_guard"))),
                int(payload.get("rag_latency_ms") or payload.get("elapsed_ms") or 0),
                payload.get("rag_degraded_reason") or payload.get("degrade_reason"),
                payload.get("rag_gate_decision"),
                payload.get("rag_gate_reason"),
                float(payload.get("rag_top_score") or 0.0),
                payload.get("rag_strategy"),
                payload.get("index_version"),
                json.dumps(payload.get("selected_doc_types") or [], ensure_ascii=False),
                payload.get("top_doc_time_label"),
                json.dumps(payload.get("query_expanded_terms") or [], ensure_ascii=False),
                payload.get("no_hit_reason"),
                float(payload.get("task_relevance_score") or 0.0),
                int(payload.get("off_topic_rejected_count") or 0),
                int(payload.get("semantic_fact_count") or 0),
                int(payload.get("style_sample_count") or 0),
                payload.get("rerank_reason"),
                payload.get("retrieval_source"),
                json.dumps(payload.get("fact_ids") or [], ensure_ascii=False),
                json.dumps(payload.get("evidence_ids") or [], ensure_ascii=False),
                payload.get("query_scope"),
                payload.get("supersession_decision"),
                payload.get("run_provenance") or "production",
                json.dumps(payload.get("candidate_ids") or [], ensure_ascii=False),
                json.dumps(payload.get("injected_item_ids") or [], ensure_ascii=False),
                int(bool(payload.get("hot_context_only"))),
                payload.get("prompt_context_hash"),
                json.dumps(payload.get("policy_ids") or [], ensure_ascii=False),
                json.dumps(payload.get("contact_preference_ids") or [], ensure_ascii=False),
                payload.get("trigger_type"),
                _now(),
            ),
        )
        return int(cursor.lastrowid)

    def upsert_fact(self, **payload: Any) -> int:
        now = _now()
        # 重扫 upsert 不得复活已被维护循环退役的事实：superseded（演变链）
        # 与 uncertain（质量隔离）是终态维护状态，同 content 重扫只允许
        # 刷新 active 行的元数据——否则语义路径每轮重建都会把 LLM 融合
        # UPDATE 退役的旧事实改回 active，演变链被静默抹掉。
        self.conn.execute(
            """
            INSERT INTO rag_facts
            (account_wxid, conversation_id, subject, kind, content, status, as_of,
             valid_from, valid_to, confidence, sensitivity, enabled, evidence_message_ids_json,
             source_window_json, summary_method, supersedes_fact_id, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(account_wxid, conversation_id, kind, content) DO UPDATE SET
              subject=excluded.subject,
              status=CASE WHEN rag_facts.status IN ('superseded', 'uncertain')
                      THEN rag_facts.status ELSE excluded.status END,
              as_of=excluded.as_of,
              valid_from=excluded.valid_from, valid_to=excluded.valid_to,
              confidence=excluded.confidence, sensitivity=excluded.sensitivity,
              enabled=CASE WHEN rag_facts.status IN ('superseded', 'uncertain')
                      THEN rag_facts.enabled ELSE excluded.enabled END,
              evidence_message_ids_json=excluded.evidence_message_ids_json,
              source_window_json=excluded.source_window_json,
              summary_method=excluded.summary_method,
              supersedes_fact_id=COALESCE(excluded.supersedes_fact_id, rag_facts.supersedes_fact_id),
              updated_at=excluded.updated_at
            """,
            (
                payload.get("account_wxid") or "",
                payload.get("conversation_id"),
                payload.get("subject") or "",
                payload.get("kind") or "unknown",
                payload.get("content") or "",
                payload.get("status") or "active",
                payload.get("as_of"), payload.get("valid_from"), payload.get("valid_to"),
                float(payload.get("confidence") or 0.0),
                payload.get("sensitivity") or "normal",
                int(bool(payload.get("enabled", True))),
                json.dumps(payload.get("evidence_message_ids") or [], ensure_ascii=False),
                json.dumps(payload.get("source_window") or {}, ensure_ascii=False),
                payload.get("summary_method") or "shadow",
                payload.get("supersedes_fact_id"), now, now,
            ),
        )
        row = self.conn.execute(
            "SELECT id FROM rag_facts WHERE account_wxid=? AND conversation_id=? AND kind=? AND content=?",
            (payload.get("account_wxid") or "", payload.get("conversation_id"), payload.get("kind") or "unknown", payload.get("content") or ""),
        ).fetchone()
        if not row:
            return 0
        try:
            fact_id = int(row["id"])
        except (TypeError, KeyError, IndexError):
            fact_id = int(row[0])
        # 用户显式标记过「不准确/忘记」的事实是墓碑：重扫导致的 upsert
        # 不得把 enabled 复位（否则被删除的记忆会“诈尸”重新参与建议）。
        tombstone = self.conn.execute(
            "SELECT 1 FROM rag_fact_user_feedback WHERE fact_id = ?", (fact_id,)
        ).fetchone()
        if tombstone:
            self.conn.execute(
                "UPDATE rag_facts SET enabled = 0, updated_at = ? WHERE id = ?",
                (now, fact_id),
            )
        return fact_id

    def list_facts(self, account_wxid: str, conversation_id: int) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            """
            SELECT * FROM rag_facts
            WHERE account_wxid = ? AND conversation_id = ?
              AND status = 'active' AND enabled = 1
            ORDER BY confidence DESC, updated_at DESC
            """,
            (account_wxid, conversation_id),
        ).fetchall()
        return [dict(row) for row in rows]

    def quarantine_low_quality_shadow_facts(
        self,
        account_wxid: str,
        conversation_id: int,
    ) -> dict[str, Any]:
        """Hide legacy semantic fragments while preserving an audit row.

        Older indexes wrote every prototype match as an active fact.  Quality
        quarantine is deliberately limited to those rows; structured LLM facts
        and user feedback tombstones are left untouched.
        """
        from .fact_quality import fact_quality_reason

        rows = self.conn.execute(
            """
            SELECT id, kind, content
            FROM rag_facts
            WHERE account_wxid = ? AND conversation_id = ?
              AND summary_method = 'shadow_semantic_embedding'
              AND status = 'active' AND enabled = 1
            """,
            (account_wxid, int(conversation_id)),
        ).fetchall()
        to_quarantine: list[tuple[int, str]] = []
        reasons: dict[str, int] = {}
        for row in rows:
            reason = fact_quality_reason(row["kind"], row["content"])
            if reason is None:
                continue
            to_quarantine.append((int(row["id"]), reason))
            reasons[reason] = reasons.get(reason, 0) + 1
        if to_quarantine:
            now = _now()
            # 批量 UPDATE（此前逐行执行 N 次）
            self.conn.executemany(
                """
                UPDATE rag_facts
                   SET status = 'uncertain', enabled = 0,
                       summary_method = 'quarantined_quality', updated_at = ?
                 WHERE id = ?
                """,
                [(now, fact_id) for fact_id, _ in to_quarantine],
            )
        return {"scanned": len(rows), "quarantined": len(to_quarantine), "reasons": reasons}

    def list_fact_evidence_text(self, evidence_message_ids: list[int] | tuple[int, ...]) -> str:
        """Return local evidence text for ranking without replacing fact content.

        Some legacy imports stored the canonical fact text after a lossy decode,
        while the original ``messages.content`` BLOB is still valid UTF-8.  The
        retriever may use this text as a keyword/embedding hint, but callers
        must continue to expose the fact and evidence IDs as the auditable
        output.  Missing tables, malformed IDs, and decode failures are safe
        no-ops for test databases and partial imports.
        """
        ids: list[int] = []
        for value in evidence_message_ids or []:
            try:
                parsed = int(value)
            except (TypeError, ValueError):
                continue
            if parsed > 0:
                ids.append(parsed)
        if not ids:
            return ""
        try:
            placeholders = ",".join("?" for _ in ids)
            rows = self.conn.execute(
                f"SELECT CAST(content AS BLOB) AS content FROM messages WHERE id IN ({placeholders})",
                ids,
            ).fetchall()
        except Exception:
            return ""
        texts: list[str] = []
        for row in rows:
            value = row[0]
            if isinstance(value, bytes):
                texts.append(value.decode("utf-8", errors="replace"))
            elif value:
                texts.append(str(value))
        return "\n".join(texts)

    def list_active_facts_by_subject_kind(
        self,
        account_wxid: str,
        conversation_id: int,
        subject: str,
        kind: str,
    ) -> list[dict[str, Any]]:
        """Return only maintenance candidates for one subject and fact kind."""
        rows = self.conn.execute(
            """
            SELECT * FROM rag_facts
            WHERE account_wxid = ? AND conversation_id = ?
              AND subject = ? AND kind = ?
              AND status = 'active' AND enabled = 1
            ORDER BY confidence DESC, updated_at DESC, id DESC
            """,
            (account_wxid, int(conversation_id), subject, kind),
        ).fetchall()
        return [dict(row) for row in rows]

    def merge_fact_evidence(
        self,
        fact_id: int,
        *,
        confidence: float,
        evidence_message_ids: list[int],
    ) -> None:
        """Merge duplicate evidence without changing the canonical fact text.

        重复确认是强信号：每次合并把置信度抬一个台阶（+0.06，封顶 0.95），
        而不是旧实现的 max(old, new) —— 那会让反复确认的事实与单窗口事实
        永远同分。
        """
        row = self.conn.execute(
            "SELECT confidence, evidence_message_ids_json FROM rag_facts WHERE id = ?",
            (int(fact_id),),
        ).fetchone()
        if not row:
            return
        try:
            current_evidence = json.loads(row["evidence_message_ids_json"] or "[]")
        except (TypeError, ValueError, json.JSONDecodeError):
            current_evidence = []
        merged_evidence = sorted({int(value) for value in current_evidence + list(evidence_message_ids)})
        old_confidence = float(row["confidence"] or 0.0)
        merged_confidence = round(
            min(
                CONFIDENCE_CEILING,
                max(old_confidence, float(confidence or 0.0)) + CONFIRMATION_STEP,
            ),
            4,
        )
        self.conn.execute(
            """
            UPDATE rag_facts
            SET confidence = ?, evidence_message_ids_json = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                merged_confidence,
                json.dumps(merged_evidence, ensure_ascii=False),
                _now(),
                int(fact_id),
            ),
        )

    def supersede_fact(self, old_fact_id: int, new_fact_id: int) -> None:
        """Retire an old fact and retain the new-to-old audit relationship."""
        # 注意：supersedes_fact_id 是单值列，多旧一新时循环调用会把指针
        # 覆盖成最后一个旧 id——完整链请配合 record_supersede_batch 留档。
        self.conn.execute(
            "UPDATE rag_facts SET status='superseded', enabled=0, updated_at=? WHERE id=?",
            (_now(), int(old_fact_id)),
        )
        self.conn.execute(
            "UPDATE rag_facts SET supersedes_fact_id=?, updated_at=? WHERE id=?",
            (int(old_fact_id), _now(), int(new_fact_id)),
        )

    def record_supersede_batch(self, new_fact_id: int, old_fact_ids: list[int]) -> None:
        """G3：一次融合"多旧一新"时留档完整被退役列表，补齐审计链。

        表结构限制：supersedes_fact_id 只有一格，supersede_fact 循环覆盖
        后只剩最后一个旧 id，其余旧→新的关系凭空丢失。rag_facts 没有专用
        备注列（不宜为此 ALTER），source_window_json 目前仅作落库留痕、
        无任何读取方，故把完整 old_ids 合并写入其 "superseded_fact_ids"
        键；同时把单链指针钉在最早落库的旧事实上，保证演变链至少不断
        在最早一环（与循环覆盖的"最后一个"相比可复现，不依赖调用顺序）。
        """
        ids = sorted({int(value) for value in old_fact_ids if int(value) != int(new_fact_id)})
        if not ids:
            return
        row = self.conn.execute(
            "SELECT source_window_json FROM rag_facts WHERE id = ?",
            (int(new_fact_id),),
        ).fetchone()
        if row is None:
            return
        try:
            window = json.loads(row["source_window_json"] or "{}")
        except (TypeError, ValueError, json.JSONDecodeError):
            window = {}
        if not isinstance(window, dict):
            window = {}
        recorded = {int(value) for value in window.get("superseded_fact_ids") or []}
        recorded |= set(ids)
        window["superseded_fact_ids"] = sorted(recorded)
        placeholders = ",".join("?" for _ in ids)
        anchor_row = self.conn.execute(
            f"""
            SELECT id FROM rag_facts
            WHERE id IN ({placeholders})
            ORDER BY COALESCE(valid_from, created_at) ASC, id ASC
            LIMIT 1
            """,
            ids,
        ).fetchone()
        anchor = int(anchor_row["id"]) if anchor_row else None
        self.conn.execute(
            """
            UPDATE rag_facts
            SET source_window_json=?, supersedes_fact_id=COALESCE(?, supersedes_fact_id),
                updated_at=?
            WHERE id=?
            """,
            (json.dumps(window, ensure_ascii=False), anchor, _now(), int(new_fact_id)),
        )

    def set_fact_enabled(self, fact_id: int, enabled: bool) -> None:
        self.conn.execute(
            "UPDATE rag_facts SET enabled=?, updated_at=? WHERE id=?",
            (int(bool(enabled)), _now(), int(fact_id)),
        )

    def set_fact_user_feedback(
        self, fact_id: int, action: str, reason: str = ""
    ) -> dict[str, Any]:
        """Mark a fact as user-rejected (inaccurate/forget) with a tombstone.

        墓碑保证增量索引重扫不会把该事实重新启用；同时立即退出检索。
        """
        if action not in {"inaccurate", "forget"}:
            return {"ok": False, "error": "invalid_action"}
        row = self.conn.execute(
            "SELECT account_wxid, conversation_id FROM rag_facts WHERE id = ?",
            (int(fact_id),),
        ).fetchone()
        if row is None:
            return {"ok": False, "error": "fact_not_found"}
        self.conn.execute(
            """
            INSERT INTO rag_fact_user_feedback
            (account_wxid, conversation_id, fact_id, action, reason, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(fact_id) DO UPDATE SET
              action=excluded.action, reason=excluded.reason, created_at=excluded.created_at
            """,
            (
                row["account_wxid"],
                row["conversation_id"],
                int(fact_id),
                action,
                reason or "",
                _now(),
            ),
        )
        self.set_fact_enabled(int(fact_id), False)
        return {"ok": True, "fact_id": int(fact_id), "action": action}

    def restore_fact(self, fact_id: int) -> dict[str, Any]:
        """Remove the tombstone and re-enable a user-rejected fact."""
        row = self.conn.execute(
            "SELECT id FROM rag_facts WHERE id = ?", (int(fact_id),)
        ).fetchone()
        if row is None:
            return {"ok": False, "error": "fact_not_found"}
        self.conn.execute(
            "DELETE FROM rag_fact_user_feedback WHERE fact_id = ?", (int(fact_id),)
        )
        self.set_fact_enabled(int(fact_id), True)
        return {"ok": True, "fact_id": int(fact_id), "action": "restore"}

    def list_fact_user_feedback(
        self, account_wxid: str, conversation_id: int
    ) -> dict[int, str]:
        rows = self.conn.execute(
            """
            SELECT fact_id, action FROM rag_fact_user_feedback
            WHERE account_wxid = ? AND conversation_id = ?
            """,
            (account_wxid, int(conversation_id)),
        ).fetchall()
        return {int(r["fact_id"]): str(r["action"]) for r in rows}

    # ---- P1.1 关系状态影子层 ----

    def upsert_relationship_state(self, **payload: Any) -> dict[str, Any]:
        """ADD-only 影子写入：新版本追加行并关闭旧版本 valid_to。

        evidence_hash 相同视为无变化，不产生新版本（避免每次重建索引抖动）。
        """
        account_wxid = payload.get("account_wxid") or ""
        conversation_id = int(payload.get("conversation_id") or 0)
        evidence_hash = str(payload.get("evidence_hash") or "")
        latest = self.get_latest_relationship_state(account_wxid, conversation_id)
        if latest and latest["evidence_hash"] == evidence_hash:
            return {"ok": True, "state_id": latest["id"], "changed": False}

        now = _now()
        old_id = int(latest["id"]) if latest else None
        if old_id:
            self.conn.execute(
                "UPDATE rag_relationship_state SET valid_to = ?, updated_at = ? WHERE id = ?",
                (now, now, old_id),
            )
        cursor = self.conn.execute(
            """
            INSERT INTO rag_relationship_state
            (account_wxid, conversation_id, stage, closeness_band, initiative_pattern,
             boundary_summary, communication_tips, relationship_note, evidence_hash,
             evidence_fact_ids_json, evidence_message_ids_json, confidence, sensitivity,
             policy_version, summary_method, valid_from, valid_to, supersedes_state_id,
             created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                account_wxid,
                conversation_id,
                str(payload.get("stage") or "unknown"),
                str(payload.get("closeness_band") or "unknown"),
                str(payload.get("initiative_pattern") or "unknown"),
                payload.get("boundary_summary"),
                payload.get("communication_tips"),
                payload.get("relationship_note"),
                evidence_hash,
                json.dumps(payload.get("evidence_fact_ids") or [], ensure_ascii=False),
                json.dumps(payload.get("evidence_message_ids") or [], ensure_ascii=False),
                float(payload.get("confidence") or 0.0),
                payload.get("sensitivity") or "normal",
                f"rs-v1-{now}",
                payload.get("summary_method") or "derived_shadow",
                now,
                None,
                old_id,
                now,
                now,
            ),
        )
        return {"ok": True, "state_id": int(cursor.lastrowid), "changed": True}

    def get_latest_relationship_state(
        self, account_wxid: str, conversation_id: int
    ) -> dict[str, Any] | None:
        row = self.conn.execute(
            """
            SELECT * FROM rag_relationship_state
            WHERE account_wxid = ? AND conversation_id = ? AND valid_to IS NULL
            ORDER BY id DESC LIMIT 1
            """,
            (account_wxid, int(conversation_id)),
        ).fetchone()
        return dict(row) if row else None

    def count_relationship_states(
        self, account_wxid: str, conversation_id: int
    ) -> int:
        row = self.conn.execute(
            """
            SELECT COUNT(*) AS n FROM rag_relationship_state
            WHERE account_wxid = ? AND conversation_id = ?
            """,
            (account_wxid, int(conversation_id)),
        ).fetchone()
        return int(row["n"]) if row else 0

    # ---- P1.2 对方偏好策略影子层 ----

    def upsert_contact_preference(self, **payload: Any) -> dict[str, Any]:
        """槽位级 ADD-only 版本写入：evidence_hash 未变化不产生新版本。

        同一 slot_key 的活跃版本存在且 hash 相同 → 跳过；hash 变化 →
        关闭旧版本 valid_to 并追加新行（supersedes 链保留审计）。
        """
        account_wxid = payload.get("account_wxid") or ""
        conversation_id = int(payload.get("conversation_id") or 0)
        slot_key = str(payload.get("slot_key") or "")
        if not account_wxid or conversation_id <= 0 or not slot_key:
            return {"ok": False, "error": "missing_slot_scope"}
        evidence_hash = str(payload.get("evidence_hash") or "")
        current = self.conn.execute(
            """
            SELECT id, evidence_hash FROM rag_contact_preferences
            WHERE account_wxid = ? AND conversation_id = ? AND slot_key = ?
              AND valid_to IS NULL
            ORDER BY id DESC LIMIT 1
            """,
            (account_wxid, conversation_id, slot_key),
        ).fetchone()
        if current and current["evidence_hash"] == evidence_hash:
            return {"ok": True, "pref_id": int(current["id"]), "changed": False}

        now = _now()
        old_id = int(current["id"]) if current else None
        if old_id:
            self.conn.execute(
                "UPDATE rag_contact_preferences SET valid_to = ?, updated_at = ? WHERE id = ?",
                (now, now, old_id),
            )
        cursor = self.conn.execute(
            """
            INSERT INTO rag_contact_preferences
            (account_wxid, conversation_id, slot_key, slot_kind, summary,
             evidence_hash, evidence_fact_ids_json, evidence_message_ids_json,
             support_count, confidence, sensitivity, policy_version,
             valid_from, valid_to, supersedes_pref_id, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                account_wxid,
                conversation_id,
                slot_key,
                str(payload.get("slot_kind") or "preference"),
                str(payload.get("summary") or ""),
                evidence_hash,
                json.dumps(payload.get("evidence_fact_ids") or [], ensure_ascii=False),
                json.dumps(payload.get("evidence_message_ids") or [], ensure_ascii=False),
                int(payload.get("support_count") or 1),
                float(payload.get("confidence") or 0.0),
                payload.get("sensitivity") or "normal",
                f"cp-v1-{now}",
                now,
                None,
                old_id,
                now,
                now,
            ),
        )
        return {"ok": True, "pref_id": int(cursor.lastrowid), "changed": True}

    def list_contact_preferences(
        self, account_wxid: str, conversation_id: int
    ) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            """
            SELECT * FROM rag_contact_preferences
            WHERE account_wxid = ? AND conversation_id = ? AND valid_to IS NULL
            ORDER BY confidence DESC, id DESC
            """,
            (account_wxid, int(conversation_id)),
        ).fetchall()
        return [dict(row) for row in rows]

    def count_contact_preferences(
        self, account_wxid: str, conversation_id: int
    ) -> int:
        row = self.conn.execute(
            """
            SELECT COUNT(*) AS n FROM rag_contact_preferences
            WHERE account_wxid = ? AND conversation_id = ?
            """,
            (account_wxid, int(conversation_id)),
        ).fetchone()
        return int(row["n"]) if row else 0

    # ---- P2.1 反馈策略信号影子层 ----

    def record_feedback_policy_signal(self, **payload: Any) -> int:
        """Append-only 影子信号：反馈/建议终态对策略层的影响审计。

        只记录不决策——信号积累到量后才驱动 accepted/rewritten 生成
        新策略候选（P2.1 后半程），本轮先保证可追溯。
        """
        cursor = self.conn.execute(
            """
            INSERT INTO rag_feedback_policy_signals
            (account_wxid, conversation_id, fact_id, suggestion_id, action,
             signal_kind, affected_policy_ids_json, outcome, retrieval_log_id,
             detail_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                payload.get("account_wxid") or "",
                payload.get("conversation_id"),
                payload.get("fact_id"),
                payload.get("suggestion_id"),
                str(payload.get("action") or ""),
                str(payload.get("signal_kind") or "fact_feedback"),
                json.dumps(payload.get("affected_policy_ids") or [], ensure_ascii=False),
                payload.get("outcome"),
                payload.get("retrieval_log_id"),
                json.dumps(payload.get("detail") or {}, ensure_ascii=False),
                _now(),
            ),
        )
        return int(cursor.lastrowid)

    def list_feedback_policy_signals(
        self,
        account_wxid: str,
        conversation_id: int,
        *,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            """
            SELECT * FROM rag_feedback_policy_signals
            WHERE account_wxid = ? AND conversation_id = ?
            ORDER BY id DESC LIMIT ?
            """,
            (account_wxid, int(conversation_id), max(1, int(limit))),
        ).fetchall()
        return [dict(row) for row in rows]

    def attach_log_to_suggestion(self, log_id: int | None, suggestion_id: int) -> None:
        if not log_id:
            return
        self.conn.execute(
            "UPDATE rag_retrieval_logs SET suggestion_id = ? WHERE id = ?",
            (int(suggestion_id), int(log_id)),
        )
