"""Validate a de-identified NLI answer file before release-gate evaluation.

The validator is deliberately content-agnostic: it never reads the source
database and never attempts to infer a label.  It only proves that every
prepared (case, track) input has one well-formed judge result.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


VALID_LABELS = {"entailed", "contradicted", "unknown"}


def _items(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, dict):
        payload = payload.get("items") or payload.get("answers") or []
    return [item for item in payload if isinstance(item, dict)]


def validate_answers(input_path: Path, answers_path: Path) -> dict[str, Any]:
    prepared = _items(input_path)
    answers = _items(answers_path)
    expected_keys = {(str(item.get("id") or ""), str(item.get("track") or "")) for item in prepared}
    seen: set[tuple[str, str]] = set()
    errors: list[dict[str, Any]] = []
    for item in answers:
        key = (str(item.get("id") or ""), str(item.get("track") or ""))
        if key in seen:
            errors.append({"key": list(key), "reason": "duplicate_answer"})
        seen.add(key)
        if key not in expected_keys:
            errors.append({"key": list(key), "reason": "unknown_input"})
        label = str(item.get("nli_label") or item.get("label") or "").lower()
        if label not in VALID_LABELS:
            errors.append({"key": list(key), "reason": "invalid_label"})
        if not isinstance(item.get("answer"), str):
            errors.append({"key": list(key), "reason": "answer_must_be_string"})
        elif not str(item.get("answer") or "").strip():
            errors.append({"key": list(key), "reason": "answer_required"})
        evidence = item.get("evidence")
        if not isinstance(evidence, list) or not all(isinstance(value, str) for value in evidence):
            errors.append({"key": list(key), "reason": "evidence_must_be_string_list"})
    missing = sorted(expected_keys - seen)
    for key in missing:
        errors.append({"key": list(key), "reason": "missing_answer"})
    labels = {str(item.get("nli_label") or item.get("label") or "").lower() for item in answers}
    return {
        "status": "ready" if not errors and bool(prepared) else ("pending" if not prepared else "invalid"),
        "prepared_cases": len(prepared),
        "answer_cases": len(answers),
        "missing_cases": len(missing),
        "label_counts": {label: sum(1 for item in answers if str(item.get("nli_label") or item.get("label") or "").lower() == label) for label in sorted(VALID_LABELS)},
        "errors": errors,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--answers", type=Path, required=True)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    result = validate_answers(args.input, args.answers)
    rendered = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0 if result["status"] == "ready" else 1


if __name__ == "__main__":
    raise SystemExit(main())
