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
        expected_account = payload.get("account_wxid") or payload.get("expected_account_wxid")
        expected_conversation = payload.get("conversation_id") or payload.get("expected_conversation_id")
        items = payload.get("items") or payload.get("cases") or []
        return [
            dict(
                item,
                **({"expected_account_wxid": expected_account} if expected_account is not None and "expected_account_wxid" not in item else {}),
                **({"expected_conversation_id": expected_conversation} if expected_conversation is not None and "expected_conversation_id" not in item else {}),
            )
            for item in items if isinstance(item, dict)
        ]
    return [item for item in payload if isinstance(item, dict)]


def load_answers(path: Path | None) -> list[dict[str, Any]]:
    if not path:
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, dict):
        payload = payload.get("items") or payload.get("answers") or []
    return [item for item in payload if isinstance(item, dict)]


def load_gold_mapping(path: Path | None) -> dict[str, Any]:
    if not path:
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def _usable_gold_mapping(mapping: dict[str, Any]) -> dict[str, Any]:
    return {
        str(key): value
        for key, value in mapping.items()
        if not str(key).startswith("_") and value not in (None, "")
    }


def resolve_gold_ids(gold: list[dict[str, Any]], mapping: dict[str, Any]) -> list[dict[str, Any]]:
    if not mapping:
        return gold
    resolved: list[dict[str, Any]] = []
    for case in gold:
        item = dict(case)
        for key in ("gold_fact_ids", "gold_document_ids", "gold_ids"):
            values = item.get(key)
            if isinstance(values, list):
                item[key] = [
                    mapping.get(str(value))
                    if mapping.get(str(value)) not in (None, "")
                    else value
                    for value in values
                ]
        resolved.append(item)
    return resolved


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


def _gold_mapping_pending(gold: list[dict[str, Any]]) -> bool:
    """Symbolic labels must be mapped to runtime fact/document IDs before recall is valid."""
    for case in gold:
        for key in ("gold_fact_ids", "gold_document_ids", "gold_ids"):
            for value in case.get(key) or []:
                if str(value).startswith(("fact_", "gold_")):
                    return True
    return False


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
    values = [float(label == "entailed") for label in usable]
    return {
        "score": sum(values) / len(values) if values else None,
        "score_ci": _bootstrap_ci(values) if values else None,
        "cases": len(usable),
        "judge_version": JUDGE_VERSION,
        "prompt_version": JUDGE_PROMPT_VERSION,
        "status": "ready" if usable else "pending_runtime_data",
    }


def _sensitive_block_metrics(results: list[dict[str, Any]]) -> dict[str, Any]:
    """Measure whether cases labelled as sensitive were blocked.

    The gold set marks sensitive cases with ``sensitive_block`` or
    ``expected_blocked``.  A ``skip``/``no_hit`` decision is considered a
    block; an injected result is a false negative.  When the gold set has no
    sensitive labels the metric is explicitly not applicable.
    """
    sensitive = [item for item in results if item.get("sensitive_expected")]
    predicted = [item for item in results if item.get("blocked_predicted")]
    true_positive = sum(
        bool(item.get("sensitive_expected")) and bool(item.get("blocked_predicted"))
        for item in results
    )
    if not sensitive:
        return {
            "status": "not_applicable",
            "cases": 0,
            "blocked_cases": len(predicted),
            "true_positive": 0,
            "precision": None,
            "recall": None,
        }
    return {
        "status": "ready" if all(item.get("matched_log") for item in sensitive) else "pending_runtime_data",
        "cases": len(sensitive),
        "blocked_cases": len(predicted),
        "true_positive": true_positive,
        "precision": true_positive / len(predicted) if predicted else 0.0,
        "recall": true_positive / len(sensitive),
    }


def _identity_isolation_metrics(results: list[dict[str, Any]]) -> dict[str, Any]:
    """Validate optional account/conversation labels on a gold case.

    Gold cases may provide ``account_wxid``/``conversation_id`` (or the
    ``expected_*`` aliases).  Without those labels the evaluator reports
    ``not_applicable`` instead of guessing that a single-contact replay is
    proof of isolation.
    """
    labelled = [item for item in results if item.get("identity_expected")]
    if not labelled:
        return {
            "status": "not_applicable",
            "cases": 0,
            "matched": 0,
            "isolation_rate": None,
        }
    matched = sum(bool(item.get("identity_match")) for item in labelled)
    return {
        "status": "ready" if all(item.get("matched_log") for item in labelled) else "pending_runtime_data",
        "cases": len(labelled),
        "matched": matched,
        "isolation_rate": matched / len(labelled),
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
    gold_queries = {
        str(case.get("query_text") or case.get("id") or "")
        for case in gold
    }

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
        expected_account = case.get("account_wxid") or case.get("expected_account_wxid")
        expected_conversation = case.get("conversation_id") or case.get("expected_conversation_id")
        identity_expected = expected_account is not None or expected_conversation is not None
        identity_match = bool(row) and (
            expected_account is None or str(row["account_wxid"] or "") == str(expected_account)
        ) and (
            expected_conversation is None or int(row["conversation_id"] or 0) == int(expected_conversation)
        )
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
                "expected_retrieve": expected_retrieve,
                "metric_eligible": bool(expected_retrieve and not blocked),
                "sensitive_expected": blocked,
                "blocked_predicted": decision in {"skip", "no_hit"},
                "identity_expected": identity_expected,
                "identity_match": identity_match,
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

    # A case whose gold is intentionally blocked is evaluated by the safety
    # metric, not by retrieval Recall/MRR.  Keeping it in the denominator
    # would turn a correct privacy block into a fabricated recall regression.
    metric_items = [item for item in results if item["metric_eligible"]]
    found_values = [float(item["recall_at_5"]) for item in metric_items]
    mrr_values = [float(item["mrr"]) for item in metric_items]
    expected_scope_items = [item for item in results if item["scope_expected"]]
    matched_count = sum(item["matched_log"] for item in results)
    has_runtime_data = matched_count > 0
    mapping_pending = _gold_mapping_pending(gold)
    metrics_ready = has_runtime_data and not mapping_pending
    summary = {
        "cases": len(results),
        "matched_logs": matched_count,
        "unmatched_runtime_logs": sum(
            1 for row in rows if str(row["query_text"] or "") not in gold_queries
        ),
        "gold_mapping_status": "pending_symbolic_labels" if mapping_pending else "ready",
        "metrics_status": "ready" if metrics_ready else (
            "pending_gold_id_mapping" if mapping_pending else "pending_runtime_data"
        ),
        "recall_at_5": average(metric_items, "recall_at_5") if metrics_ready and metric_items else None,
        "recall_at_5_ci": _bootstrap_ci(found_values) if metrics_ready else None,
        "mrr": average(metric_items, "mrr") if metrics_ready and metric_items else None,
        "mrr_ci": _bootstrap_ci(mrr_values) if metrics_ready else None,
        "gate_skip_rate": sum(item["gate_decision"] == "skip" for item in results) / len(results) if has_runtime_data else None,
        "gate_no_hit_rate": sum(item["gate_decision"] == "no_hit" for item in results) / len(results) if has_runtime_data else None,
        "false_reject_rate": sum(item["false_reject"] for item in results) / len(results) if has_runtime_data else None,
        "correct_reject_rate": sum(item["correct_reject"] for item in results) / len(results) if has_runtime_data else None,
        "query_scope_accuracy": sum(item["scope_correct"] for item in expected_scope_items) / len(expected_scope_items)
        if has_runtime_data and expected_scope_items else None,
        "sensitive_block": _sensitive_block_metrics(results),
        "identity_isolation": _identity_isolation_metrics(results),
        "gate_reason_distribution": dict(Counter(item["gate_reason"] for item in results)),
    }
    by_category = {
        category: {
            "cases": len(items),
            "matched_logs": sum(item["matched_log"] for item in items),
            "recall_at_5": average([item for item in items if item["metric_eligible"]], "recall_at_5") if metrics_ready else None,
            "mrr": average([item for item in items if item["metric_eligible"]], "mrr") if metrics_ready else None,
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


def evaluate(
    conn: sqlite3.Connection,
    gold: list[dict[str, Any]],
    answers: list[dict[str, Any]] | None = None,
    gold_mapping: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return a three-track report for callers and tests."""
    usable_mapping = _usable_gold_mapping(gold_mapping or {})
    gold = resolve_gold_ids(gold, usable_mapping)
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
    metric_names = ("recall_at_5", "mrr")
    comparable = all(doc.get(name) is not None and fact.get(name) is not None for name in metric_names)
    comparable = comparable and doc_faith is not None and fact_faith is not None

    def _lower(summary: dict[str, Any], name: str) -> float | None:
        ci = summary.get(f"{name}_ci")
        if isinstance(ci, dict) and ci.get("lower") is not None:
            return float(ci["lower"])
        value = summary.get(name)
        return float(value) if value is not None else None

    fact_faith_ci = tracks["fact_path"]["faithfulness"].get("score_ci") or {}
    doc_faith_ci = tracks["document_rag"]["faithfulness"].get("score_ci") or {}
    metric_comparisons = {
        name: {
            "fact_lower": _lower(fact, name),
            "document_lower": _lower(doc, name),
        }
        for name in metric_names
    }
    metric_comparisons["faithfulness"] = {
        "fact_lower": fact_faith_ci.get("lower", fact_faith),
        "document_lower": doc_faith_ci.get("lower", doc_faith),
    }
    metrics_not_regressed = comparable and all(
        value["fact_lower"] is not None
        and value["document_lower"] is not None
        and value["fact_lower"] >= value["document_lower"]
        for value in metric_comparisons.values()
    )

    fact_safety = tracks["fact_path"]["summary"]["sensitive_block"]
    doc_safety = tracks["document_rag"]["summary"]["sensitive_block"]
    fact_identity = tracks["fact_path"]["summary"]["identity_isolation"]
    doc_identity = tracks["document_rag"]["summary"]["identity_isolation"]

    def _safety_not_regressed() -> bool:
        if fact_safety["status"] != "ready" or doc_safety["status"] != "ready":
            return False
        return all(
            fact_safety[name] >= doc_safety[name]
            for name in ("precision", "recall")
        )

    def _identity_not_regressed() -> bool:
        if fact_identity["status"] != "ready" or doc_identity["status"] != "ready":
            return False
        return fact_identity["isolation_rate"] >= doc_identity["isolation_rate"]

    safety_and_identity = "pass" if _safety_not_regressed() and _identity_not_regressed() else "pending_runtime_data"
    return {
        "version": 2,
        "generated_at": int(time.time()),
        "gold_mapping_entries": len(usable_mapping),
        "tracks": tracks,
        "release_gate": {
            "status": "pass" if metrics_not_regressed and safety_and_identity == "pass" else "pending_runtime_data",
            "comparable": comparable,
            "fact_not_below_document": metrics_not_regressed if comparable else None,
            "compared_metrics": ["recall_at_5", "mrr", "faithfulness"],
            "safety_and_identity": safety_and_identity,
            "metric_lower_bounds": metric_comparisons,
            "notes": "先冻结 no-RAG/document-RAG 基线，再按分层 bootstrap 下界设定阈值。",
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", required=True, help="SQLite database containing rag_retrieval_logs")
    parser.add_argument("--gold", required=True, help="JSON list of query cases and gold fact/document IDs")
    parser.add_argument("--answers", help="Optional de-identified NLI judge labels JSON")
    parser.add_argument("--gold-map", help="Optional JSON mapping symbolic gold IDs to runtime IDs")
    parser.add_argument("--out", help="Optional JSON report path")
    args = parser.parse_args()
    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    report = evaluate(
        conn,
        load_gold(Path(args.gold)),
        load_answers(Path(args.answers) if args.answers else None),
        load_gold_mapping(Path(args.gold_map) if args.gold_map else None),
    )
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
