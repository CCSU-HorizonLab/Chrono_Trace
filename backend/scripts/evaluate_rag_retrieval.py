"""Evaluate contact-scoped memory retrieval and release-gate metrics.

The evaluator never turns missing runtime logs into a zero-quality claim. It
reports no-RAG, document-RAG, and fact-path tracks separately. Faithfulness is
an offline judge input: pass de-identified NLI labels with ``--answers``.
"""

from __future__ import annotations

import argparse
import json
import random
import sqlite3
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable


TRACKS = ("no_rag", "document_rag", "fact_path")
JUDGE_VERSION = "nli-external-required-v1"
JUDGE_PROMPT_VERSION = "rag-v4-faithfulness-v1"


def _json(value: Any, default: Any) -> Any:
    try:
        parsed = json.loads(value) if value else default
    except (TypeError, ValueError, json.JSONDecodeError):
        return default
    return parsed


def load_gold(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, dict):
        payload = payload.get("items") or payload.get("cases") or []
    return [item for item in payload if isinstance(item, dict)]


def load_answers(path: Path | None) -> list[dict[str, Any]]:
    if not path:
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, dict):
        payload = payload.get("items") or payload.get("answers") or []
    return [item for item in payload if isinstance(item, dict)]


def _track(row: sqlite3.Row) -> str:
    source = str(row["retrieval_source"] or "").strip().lower()
    strategy = str(row["rag_strategy"] or "").strip().lower()
    if not int(row["rag_enabled"] or 0) or source == "none":
        return "no_rag"
    if source == "fact" or strategy == "facts":
        return "fact_path"
    return "document_rag"


def _ids(row: sqlite3.Row, track: str) -> list[str]:
    if track == "fact_path":
        fact_ids = _json(row["fact_ids_json"], [])
        if fact_ids:
            return [str(item) for item in fact_ids]
    return [str(item) for item in _json(row["document_ids_json"], [])]


def _gold_ids(case: dict[str, Any], track: str) -> set[str]:
    keys = ("gold_fact_ids", "gold_ids", "gold_document_ids") if track == "fact_path" else (
        "gold_document_ids", "gold_ids", "gold_fact_ids"
    )
    for key in keys:
        values = case.get(key)
        if values:
            return {str(item) for item in values}
    return set()


def _bootstrap_ci(values: Iterable[float], seed: int = 41, rounds: int = 1000) -> dict[str, float] | None:
    values = list(values)
    if not values:
        return None
    if len(values) == 1:
        value = float(values[0])
        return {"lower": value, "upper": value}
    rng = random.Random(seed)
    samples = []
    for _ in range(rounds):
        sample = [values[rng.randrange(len(values))] for _ in values]
        samples.append(sum(sample) / len(sample))
    samples.sort()
    return {"lower": samples[int(rounds * 0.025)], "upper": samples[int(rounds * 0.975) - 1]}


def _answer_faithfulness(answers: list[dict[str, Any]], track: str) -> dict[str, Any]:
    labels = [
        str(item.get("nli_label") or item.get("label") or "").lower()
        for item in answers
        if str(item.get("track") or "") in {"", track}
    ]
    usable = [label for label in labels if label in {"entailed", "contradicted", "unknown"}]
    return {
        "score": sum(label == "entailed" for label in usable) / len(usable) if usable else None,
        "cases": len(usable),
        "judge_version": JUDGE_VERSION,
        "prompt_version": JUDGE_PROMPT_VERSION,
        "status": "ready" if usable else "pending_runtime_data",
    }


def _evaluate_track(
    rows: list[sqlite3.Row],
    gold: list[dict[str, Any]],
    track_name: str,
    answers: list[dict[str, Any]],
) -> dict[str, Any]:
    by_query: dict[str, list[sqlite3.Row]] = defaultdict(list)
    for row in rows:
        by_query[str(row["query_text"] or "")].append(row)

    results: list[dict[str, Any]] = []
    for case in gold:
        query = str(case.get("query_text") or case.get("id") or "")
        row = (by_query.get(query) or [None])[0]
        track = _track(row) if row else "missing"
        retrieved = _ids(row, track) if row else []
        expected = _gold_ids(case, track if track != "missing" else "fact_path")
        rank = next((index for index, item in enumerate(retrieved, 1) if item in expected), None)
        decision = str(row["rag_gate_decision"] or "missing") if row else "missing"
        expected_retrieve = bool(case.get("expected_retrieve", bool(expected)))
        blocked = bool(case.get("sensitive_block") or case.get("expected_blocked"))
        correct_reject = bool(row) and (not expected_retrieve or blocked) and decision in {"skip", "no_hit"}
        false_reject = expected_retrieve and not blocked and decision in {"skip", "no_hit"}
        scope_expected = case.get("expected_scope") or case.get("query_scope")
        scope_actual = str(row["query_scope"] or "") if row else ""
        results.append(
            {
                "id": case.get("id") or query,
                "query_text": query,
                "category": case.get("category") or "uncategorized",
                "found": bool(rank),
                "rank": rank,
                "recall_at_5": bool(rank and rank <= 5),
                "mrr": 1.0 / rank if rank else 0.0,
                "gate_decision": decision,
                "gate_reason": str(row["rag_gate_reason"] or "") if row else "missing_log",
                "matched_log": bool(row),
                "retrieved_ids": retrieved,
                "expected_ids": sorted(expected),
                "correct_reject": correct_reject,
                "false_reject": false_reject,
                "scope_expected": scope_expected,
                "scope_actual": scope_actual,
                "scope_correct": bool(scope_expected and scope_actual == scope_expected),
            }
        )

    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in results:
        grouped[item["category"]].append(item)

    def average(items: list[dict[str, Any]], key: str) -> float | None:
        return sum(float(item[key]) for item in items) / len(items) if items else None

    found_values = [float(item["recall_at_5"]) for item in results]
    mrr_values = [float(item["mrr"]) for item in results]
    expected_scope_items = [item for item in results if item["scope_expected"]]
    matched_count = sum(item["matched_log"] for item in results)
    has_runtime_data = matched_count > 0
    summary = {
        "cases": len(results),
        "matched_logs": matched_count,
        "metrics_status": "ready" if has_runtime_data else "pending_runtime_data",
        "recall_at_5": average(results, "recall_at_5") if has_runtime_data else None,
        "recall_at_5_ci": _bootstrap_ci(found_values) if has_runtime_data else None,
        "mrr": average(results, "mrr") if has_runtime_data else None,
        "mrr_ci": _bootstrap_ci(mrr_values) if has_runtime_data else None,
        "gate_skip_rate": sum(item["gate_decision"] == "skip" for item in results) / len(results) if has_runtime_data else None,
        "gate_no_hit_rate": sum(item["gate_decision"] == "no_hit" for item in results) / len(results) if has_runtime_data else None,
        "false_reject_rate": sum(item["false_reject"] for item in results) / len(results) if has_runtime_data else None,
        "correct_reject_rate": sum(item["correct_reject"] for item in results) / len(results) if has_runtime_data else None,
        "query_scope_accuracy": sum(item["scope_correct"] for item in expected_scope_items) / len(expected_scope_items)
        if has_runtime_data and expected_scope_items else None,
        "gate_reason_distribution": dict(Counter(item["gate_reason"] for item in results)),
    }
    by_category = {
        category: {
            "cases": len(items),
            "matched_logs": sum(item["matched_log"] for item in items),
            "recall_at_5": average(items, "recall_at_5") if any(item["matched_log"] for item in items) else None,
            "mrr": average(items, "mrr") if any(item["matched_log"] for item in items) else None,
            "skip_rate": sum(item["gate_decision"] == "skip" for item in items) / len(items)
            if any(item["matched_log"] for item in items) else None,
            "no_hit_rate": sum(item["gate_decision"] == "no_hit" for item in items) / len(items)
            if any(item["matched_log"] for item in items) else None,
        }
        for category, items in grouped.items()
    }
    return {
        "summary": summary,
        "by_category": by_category,
        "faithfulness": _answer_faithfulness(answers, track_name),
        "items": results,
    }


def evaluate(conn: sqlite3.Connection, gold: list[dict[str, Any]], answers: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Return a three-track report for callers and tests."""
    rows = conn.execute("SELECT * FROM rag_retrieval_logs ORDER BY created_at ASC, id ASC").fetchall()
    grouped: dict[str, list[sqlite3.Row]] = defaultdict(list)
    for row in rows:
        grouped[_track(row)].append(row)
    answers = answers or []
    tracks = {track: _evaluate_track(grouped.get(track, []), gold, track, answers) for track in TRACKS}
    doc = tracks["document_rag"]["summary"]
    fact = tracks["fact_path"]["summary"]
    doc_faith = tracks["document_rag"]["faithfulness"].get("score")
    fact_faith = tracks["fact_path"]["faithfulness"].get("score")
    comparable = all(doc.get(name) is not None and fact.get(name) is not None for name in ("recall_at_5", "mrr"))
    comparable = comparable and doc_faith is not None and fact_faith is not None
    metrics_not_regressed = comparable and all(
        fact[name] >= doc[name] for name in ("recall_at_5", "mrr")
    ) and fact_faith >= doc_faith
    return {
        "version": 2,
        "generated_at": int(time.time()),
        "tracks": tracks,
        "release_gate": {
            "status": "pass" if metrics_not_regressed else "pending_runtime_data",
            "comparable": comparable,
            "fact_not_below_document": metrics_not_regressed if comparable else None,
            "compared_metrics": ["recall_at_5", "mrr", "faithfulness"],
            "safety_and_identity": "pending_runtime_data",
            "notes": "先冻结 no-RAG/document-RAG 基线，再按分层 bootstrap 下界设定阈值。",
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", required=True, help="SQLite database containing rag_retrieval_logs")
    parser.add_argument("--gold", required=True, help="JSON list of query cases and gold fact/document IDs")
    parser.add_argument("--answers", help="Optional de-identified NLI judge labels JSON")
    parser.add_argument("--out", help="Optional JSON report path")
    args = parser.parse_args()
    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    report = evaluate(conn, load_gold(Path(args.gold)), load_answers(Path(args.answers) if args.answers else None))
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
