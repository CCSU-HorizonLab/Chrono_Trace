"""Read-only, privacy-preserving audit of the v4 runtime RAG database.

This script intentionally emits aggregates only.  It never prints query text,
fact/document content, account identifiers, names, or message identifiers.
SQLite is opened with mode=ro, query_only=ON, and a single read transaction so
WAL changes cannot produce a mixed snapshot.

Usage (from repository root)::

    python backend/scripts/audit_rag_v4_post_eval.py
    python backend/scripts/audit_rag_v4_post_eval.py --db backend/data/chrono_trace.db \
        --out docs/analysis/rag-v4-post-eval-runtime-stats.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB = ROOT / "backend" / "data" / "chrono_trace.db"
DEFAULT_OUT = ROOT / "docs" / "analysis" / "rag-v4-post-eval-runtime-stats.json"


def _epoch_range(rows: list[tuple[Any, ...]], index: int = 0) -> dict[str, Any]:
    values = [int(row[index]) for row in rows if row[index] is not None]
    if not values:
        return {"min": None, "max": None, "min_utc": None, "max_utc": None}

    def iso(value: int) -> str:
        return datetime.fromtimestamp(value, tz=timezone.utc).isoformat()

    return {"min": min(values), "max": max(values), "min_utc": iso(min(values)), "max_utc": iso(max(values))}


def _group(cur: sqlite3.Cursor, table: str, column: str) -> dict[str, int]:
    # Columns are constants in this script, not user input.
    rows = cur.execute(
        f"SELECT COALESCE(CAST({column} AS TEXT), '<NULL>'), COUNT(*) FROM {table} GROUP BY {column} ORDER BY COUNT(*) DESC"
    ).fetchall()
    return {str(key): int(value) for key, value in rows}


def _safe_json_count(cur: sqlite3.Cursor, column: str, table: str, key: str) -> dict[str, int]:
    """Count a JSON-array field without exposing array members."""
    rows = cur.execute(f"SELECT {column} FROM {table}").fetchall()
    counts = Counter()
    malformed = 0
    for (raw,) in rows:
        try:
            value = json.loads(raw) if raw else []
            counts[key if isinstance(value, list) and value else "empty"] += 1
        except Exception:
            malformed += 1
    if malformed:
        counts["malformed"] = malformed
    return dict(counts)


def audit(db_path: Path) -> dict[str, Any]:
    stat = db_path.stat()
    uri = f"file:{db_path.resolve().as_posix()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    try:
        conn.execute("PRAGMA query_only=ON")
        conn.execute("BEGIN")
        cur = conn.cursor()

        tables = {
            row[0]
            for row in cur.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }
        required = {
            "rag_retrieval_logs",
            "rag_facts",
            "rag_documents",
            "rag_index_status",
            "realtime_suggestions",
            "suggestion_observations",
            "suggestion_feedback_attributions",
        }
        missing = sorted(required - tables)
        if missing:
            return {
                "schema_available": False,
                "missing_tables": missing,
                "database": {"path": str(db_path), "bytes": stat.st_size},
            }

        log_count = int(cur.execute("SELECT COUNT(*) FROM rag_retrieval_logs").fetchone()[0])
        log_times = cur.execute("SELECT created_at FROM rag_retrieval_logs").fetchall()
        hit_hist = _group(cur, "rag_retrieval_logs", "rag_hit_count")
        pseudo_rows = cur.execute(
            "SELECT COUNT(*) FROM rag_retrieval_logs WHERE instr(COALESCE(document_ids_json,''), '-1') > 0"
        ).fetchone()[0]
        fact_source_rows = int(cur.execute("SELECT COUNT(*) FROM rag_retrieval_logs WHERE retrieval_source='fact'").fetchone()[0])
        document_source_rows = int(cur.execute("SELECT COUNT(*) FROM rag_retrieval_logs WHERE retrieval_source='document'").fetchone()[0])
        suggestion_linked = int(cur.execute("SELECT COUNT(*) FROM rag_retrieval_logs WHERE suggestion_id IS NOT NULL").fetchone()[0])
        conv_count = int(cur.execute("SELECT COUNT(DISTINCT conversation_id) FROM rag_retrieval_logs").fetchone()[0])

        logs = {
            "rows": log_count,
            "time": _epoch_range(log_times),
            "distinct_conversations": conv_count,
            "intent_mode": _group(cur, "rag_retrieval_logs", "memory_intent_mode"),
            "index_status": _group(cur, "rag_retrieval_logs", "index_status"),
            "rag_enabled": _group(cur, "rag_retrieval_logs", "rag_enabled"),
            "rag_retrieved": _group(cur, "rag_retrieval_logs", "rag_retrieved"),
            "hit_count": hit_hist,
            "injection_mode": _group(cur, "rag_retrieval_logs", "rag_injection_mode"),
            "gate_decision": _group(cur, "rag_retrieval_logs", "rag_gate_decision"),
            "gate_reason": _group(cur, "rag_retrieval_logs", "rag_gate_reason"),
            "strategy": _group(cur, "rag_retrieval_logs", "rag_strategy"),
            "retrieval_source": _group(cur, "rag_retrieval_logs", "retrieval_source"),
            "no_hit_reason": _group(cur, "rag_retrieval_logs", "no_hit_reason"),
            "degrade_reason": _group(cur, "rag_retrieval_logs", "rag_degraded_reason"),
            "query_scope": _group(cur, "rag_retrieval_logs", "query_scope"),
            "redaction_status": _group(cur, "rag_retrieval_logs", "redaction_status"),
            "sensitive_pseudo_hit_candidate_document_id_minus_one": int(pseudo_rows),
            "source_row_counts": {"fact": fact_source_rows, "document": document_source_rows},
            "suggestion_id_non_null": suggestion_linked,
            "suggestion_id_null": log_count - suggestion_linked,
            "json_field_presence": {
                "fact_ids": _safe_json_count(cur, "fact_ids_json", "rag_retrieval_logs", "nonempty"),
                "evidence_ids": _safe_json_count(cur, "evidence_ids_json", "rag_retrieval_logs", "nonempty"),
            },
        }

        facts = {
            "rows": int(cur.execute("SELECT COUNT(*) FROM rag_facts").fetchone()[0]),
            "kind_status_sensitivity_enabled": [
                {"kind": kind, "status": status, "sensitivity": sensitivity, "enabled": int(enabled), "count": int(count)}
                for kind, status, sensitivity, enabled, count in cur.execute(
                    "SELECT kind,status,sensitivity,enabled,COUNT(*) FROM rag_facts GROUP BY kind,status,sensitivity,enabled ORDER BY COUNT(*) DESC"
                )
            ],
            "status": _group(cur, "rag_facts", "status"),
            "sensitivity": _group(cur, "rag_facts", "sensitivity"),
            "enabled": _group(cur, "rag_facts", "enabled"),
            "supersedes_fact_id_non_null": int(cur.execute("SELECT COUNT(*) FROM rag_facts WHERE supersedes_fact_id IS NOT NULL").fetchone()[0]),
            "confidence_bins": {
                "lt_0_30": int(cur.execute("SELECT COUNT(*) FROM rag_facts WHERE confidence < .3").fetchone()[0]),
                "0_30_to_lt_0_50": int(cur.execute("SELECT COUNT(*) FROM rag_facts WHERE confidence >= .3 AND confidence < .5").fetchone()[0]),
                "0_50_to_lt_0_70": int(cur.execute("SELECT COUNT(*) FROM rag_facts WHERE confidence >= .5 AND confidence < .7").fetchone()[0]),
                "0_70_to_lt_0_90": int(cur.execute("SELECT COUNT(*) FROM rag_facts WHERE confidence >= .7 AND confidence < .9").fetchone()[0]),
                "ge_0_90": int(cur.execute("SELECT COUNT(*) FROM rag_facts WHERE confidence >= .9").fetchone()[0]),
            },
            "updated_time": _epoch_range(cur.execute("SELECT updated_at FROM rag_facts").fetchall()),
        }

        relationship_types = ("relationship_state", "contact_preference", "communication_style")
        docs = {
            "rows": int(cur.execute("SELECT COUNT(*) FROM rag_documents").fetchone()[0]),
            "doc_type": _group(cur, "rag_documents", "doc_type"),
            "relationship_doc_counts": {
                doc_type: int(cur.execute("SELECT COUNT(*) FROM rag_documents WHERE doc_type=?", (doc_type,)).fetchone()[0])
                for doc_type in relationship_types
            },
            "relationship_doc_enabled": {
                doc_type: _group(cur, "(SELECT enabled FROM rag_documents WHERE doc_type='" + doc_type + "')", "enabled")
                if False else {
                    str(enabled): int(count)
                    for enabled, count in cur.execute("SELECT enabled,COUNT(*) FROM rag_documents WHERE doc_type=? GROUP BY enabled", (doc_type,))
                }
                for doc_type in relationship_types
            },
            "sensitivity": _group(cur, "rag_documents", "sensitivity"),
            "superseded_by_non_null": int(cur.execute("SELECT COUNT(*) FROM rag_documents WHERE superseded_by IS NOT NULL").fetchone()[0]),
            "updated_time": _epoch_range(cur.execute("SELECT updated_at FROM rag_documents").fetchall()),
        }

        index = {
            "rows": int(cur.execute("SELECT COUNT(*) FROM rag_index_status").fetchone()[0]),
            "status_and_fact_read_mode": [
                {"status": status, "fact_read_mode": mode, "count": int(count)}
                for status, mode, count in cur.execute(
                    "SELECT status,fact_read_mode,COUNT(*) FROM rag_index_status GROUP BY status,fact_read_mode ORDER BY COUNT(*) DESC"
                )
            ],
            "embedding_dimensions": _group(cur, "rag_index_status", "embedding_dim"),
        }

        suggestions = {
            "rows": int(cur.execute("SELECT COUNT(*) FROM realtime_suggestions").fetchone()[0]),
            "trigger_type": _group(cur, "realtime_suggestions", "trigger_type"),
            "status": _group(cur, "realtime_suggestions", "status"),
            "engine_type": _group(cur, "realtime_suggestions", "engine_type"),
            "time": _epoch_range(cur.execute("SELECT created_at FROM realtime_suggestions").fetchall()),
            "observation_events": _group(cur, "suggestion_observations", "event_type"),
            "feedback_attribution_rows": int(cur.execute("SELECT COUNT(*) FROM suggestion_feedback_attributions").fetchone()[0]),
            "feedback_attribution_types": _group(cur, "suggestion_feedback_attributions", "attribution_type"),
            "feedback_writeback_document_non_null": int(cur.execute("SELECT COUNT(*) FROM suggestion_feedback_attributions WHERE writeback_document_id IS NOT NULL").fetchone()[0]),
        }

        return {
            "schema_available": True,
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "database": {
                "path": str(db_path.resolve()),
                "bytes": stat.st_size,
                "sha256": hashlib.sha256(db_path.read_bytes()).hexdigest(),
                "snapshot": "sqlite mode=ro + PRAGMA query_only=ON + BEGIN (WAL-consistent read transaction)",
            },
            "logs": logs,
            "facts": facts,
            "documents": docs,
            "index": index,
            "suggestions_and_feedback": suggestions,
            "limitations": [
                "The production database contains seven retrieval rows spanning one account and one conversation; it cannot estimate population-level trigger or recall rates.",
                "All seven retrieval rows have a NULL suggestion_id, so retrieval-to-suggestion joins and causal attribution are unavailable; time proximity must not be treated as a join.",
                "The schema has no explicit eval/test provenance flag. Production-vs-replay contamination cannot be separated from this database by SQL alone.",
                "The two document_id=-1 rows are hot_context candidates with retrieval_source=document and rag_degraded_reason=hot_context_only; they are counted as candidates only and no longer represent a valid historical hit after the hot-context fix.",
                "Counts are aggregates; raw query/fact/document/message content is intentionally omitted to prevent personal-data disclosure.",
            ],
        }
    finally:
        conn.rollback()
        conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    result = audit(args.db)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {args.out} (schema_available={result.get('schema_available')})")


if __name__ == "__main__":
    main()
