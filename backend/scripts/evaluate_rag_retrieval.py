"""Evaluate contact-scoped retrieval logs against a small gold set.

The script intentionally does not invent thresholds. It reports Recall@5, MRR,
skip/no-hit rates, and per-category aggregates so a baseline can be frozen first.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from collections import defaultdict
from pathlib import Path
from typing import Any


def _json(value: Any, default: Any) -> Any:
    try:
        return json.loads(value) if value else default
    except (TypeError, ValueError, json.JSONDecodeError):
        return default


def load_gold(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, dict):
        payload = payload.get("items") or payload.get("cases") or []
    return [item for item in payload if isinstance(item, dict)]


def evaluate(conn: sqlite3.Connection, gold: list[dict[str, Any]]) -> dict[str, Any]:
    rows = conn.execute(
        "SELECT * FROM rag_retrieval_logs ORDER BY created_at ASC, id ASC"
    ).fetchall()
    by_key: dict[str, list[sqlite3.Row]] = defaultdict(list)
    for row in rows:
        query = str(row["query_text"] or "")
        by_key[query].append(row)

    results: list[dict[str, Any]] = []
    for case in gold:
        query = str(case.get("query_text") or case.get("id") or "")
        candidates = by_key.get(query) or []
        row = candidates[0] if candidates else None
        retrieved = _json(row["document_ids_json"], []) if row else []
        expected = {str(item) for item in (case.get("gold_document_ids") or case.get("gold_ids") or [])}
        rank = next((index for index, item in enumerate(retrieved, 1) if str(item) in expected), None)
        decision = str(row["rag_gate_decision"] or "missing") if row else "missing"
        results.append(
            {
                "id": case.get("id") or query,
                "category": case.get("category") or "uncategorized",
                "found": bool(rank),
                "rank": rank,
                "recall_at_5": bool(rank and rank <= 5),
                "mrr": 1.0 / rank if rank else 0.0,
                "gate_decision": decision,
                "matched_log": bool(row),
            }
        )

    count = len(results)
    summary = {
        "cases": count,
        "matched_logs": sum(item["matched_log"] for item in results),
        "recall_at_5": sum(item["recall_at_5"] for item in results) / count if count else 0.0,
        "mrr": sum(item["mrr"] for item in results) / count if count else 0.0,
        "gate_skip_rate": sum(item["gate_decision"] == "skip" for item in results) / count if count else 0.0,
        "gate_no_hit_rate": sum(item["gate_decision"] == "no_hit" for item in results) / count if count else 0.0,
    }
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in results:
        grouped[item["category"]].append(item)
    by_category = {
        category: {
            "cases": len(items),
            "recall_at_5": sum(i["recall_at_5"] for i in items) / len(items),
            "mrr": sum(i["mrr"] for i in items) / len(items),
            "skip_rate": sum(i["gate_decision"] == "skip" for i in items) / len(items),
        }
        for category, items in grouped.items()
    }
    return {"summary": summary, "by_category": by_category, "items": results}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", required=True, help="SQLite database containing rag_retrieval_logs")
    parser.add_argument("--gold", required=True, help="JSON list of query cases and gold ids")
    parser.add_argument("--out", help="Optional JSON report path")
    args = parser.parse_args()
    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    report = evaluate(conn, load_gold(Path(args.gold)))
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    if args.out:
        Path(args.out).write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
