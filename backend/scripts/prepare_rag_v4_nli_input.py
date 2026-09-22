"""Build a de-identified NLI-judge input package from replay logs.

The source database is read-only.  The output contains query/evidence pairs
for each gold case and track, but leaves ``answer`` and ``nli_label`` for an
external human/LLM judge.  Sensitive evidence is represented by its ID only.
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from pathlib import Path
from typing import Any

# Allow direct execution from the repository root, matching the other v4
# scripts.  The source database itself remains read-only.
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "backend") not in sys.path:
    sys.path.insert(0, str(ROOT / "backend"))

from app.services.realtime.privacy_redactor import PrivacyRedactor


TRACKS = ("no_rag", "document_rag", "fact_path")
JUDGE_VERSION = "nli-external-required-v1"
PROMPT_VERSION = "rag-v4-faithfulness-v1"


def load_gold(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, dict):
        payload = payload.get("items") or payload.get("cases") or []
    return [item for item in payload if isinstance(item, dict)]


def _json(value: Any, default: Any) -> Any:
    try:
        parsed = json.loads(value) if value else default
    except (TypeError, ValueError, json.JSONDecodeError):
        return default
    return parsed


def _track(row: sqlite3.Row) -> str:
    source = str(row["retrieval_source"] or "").lower()
    strategy = str(row["rag_strategy"] or "").lower()
    if not int(row["rag_enabled"] or 0) or source == "none":
        return "no_rag"
    if source == "fact" or strategy == "facts":
        return "fact_path"
    return "document_rag"


def _safe_text(redactor: PrivacyRedactor, text: Any, *, account: str, conversation: int) -> str:
    result = redactor.redact(
        str(text or ""),
        account_wxid=account,
        conversation_id=conversation,
        source_table="nli_export",
        mode="balanced",
    )
    return re.sub(r"\s+", " ", result.redacted_text).strip()[:500]


def _evidence_for_row(
    conn: sqlite3.Connection,
    row: sqlite3.Row,
    *,
    redactor: PrivacyRedactor,
) -> list[dict[str, Any]]:
    account = str(row["account_wxid"] or "")
    conversation = int(row["conversation_id"] or 0)
    track = _track(row)
    ids_key = "fact_ids_json" if track == "fact_path" else "document_ids_json"
    ids = [int(item) for item in _json(row[ids_key], []) if str(item).lstrip("-").isdigit()]
    if not ids or track == "no_rag":
        return []
    if track == "fact_path":
        placeholders = ",".join("?" for _ in ids)
        rows = conn.execute(
            f"SELECT id, kind, content, sensitivity, evidence_message_ids_json "
            f"FROM rag_facts WHERE account_wxid=? AND conversation_id=? AND id IN ({placeholders})",
            [account, conversation, *ids],
        ).fetchall()
    else:
        placeholders = ",".join("?" for _ in ids)
        rows = conn.execute(
            f"SELECT id, doc_type, content, redacted_content, sensitivity "
            f"FROM rag_documents WHERE account_wxid=? AND conversation_id=? AND id IN ({placeholders})",
            [account, conversation, *ids],
        ).fetchall()
    by_id = {int(item["id"]): item for item in rows}
    evidence: list[dict[str, Any]] = []
    for item_id in ids:
        item = by_id.get(item_id)
        if not item:
            continue
        sensitivity = str(item["sensitivity"] or "normal")
        rendered: dict[str, Any] = {
            "id": item_id,
            "sensitivity": sensitivity,
            "content": "[敏感证据已隐藏]" if sensitivity == "sensitive" else _safe_text(
                redactor,
                item["content"],
                account=account,
                conversation=conversation,
            ),
        }
        if track == "fact_path":
            rendered["kind"] = item["kind"]
            rendered["evidence_message_ids"] = _json(item["evidence_message_ids_json"], [])
        else:
            rendered["doc_type"] = item["doc_type"]
        evidence.append(rendered)
    return evidence


def build_nli_input(conn: sqlite3.Connection, gold: list[dict[str, Any]]) -> dict[str, Any]:
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT * FROM rag_retrieval_logs ORDER BY created_at ASC, id ASC").fetchall()
    by_key: dict[tuple[str, str], sqlite3.Row] = {}
    for row in rows:
        by_key.setdefault((_track(row), str(row["query_text"] or "")), row)
    redactor = PrivacyRedactor(None)
    items: list[dict[str, Any]] = []
    for case in gold:
        query = str(case.get("query_text") or case.get("id") or "")
        for track in TRACKS:
            row = by_key.get((track, query))
            evidence = _evidence_for_row(conn, row, redactor=redactor) if row else []
            account = str(row["account_wxid"] or "") if row else ""
            conversation = int(row["conversation_id"] or 0) if row else 0
            items.append({
                "id": f"{case.get('id') or query}:{track}",
                "case_id": case.get("id") or query,
                "track": track,
                "query": _safe_text(redactor, query, account=account, conversation=conversation),
                "answer": "",
                "evidence": evidence,
                "evidence_ids": [item["id"] for item in evidence],
                "nli_label": "unknown",
                "judge_version": JUDGE_VERSION,
                "prompt_version": PROMPT_VERSION,
            })
    return {
        "version": 1,
        "deidentified": True,
        "judge_version": JUDGE_VERSION,
        "prompt_version": PROMPT_VERSION,
        "items": items,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--gold", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    conn = sqlite3.connect(str(args.db))
    try:
        payload = build_nli_input(conn, load_gold(args.gold))
    finally:
        conn.close()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {args.out} with {len(payload['items'])} judge items")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
