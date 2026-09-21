"""Export privacy-aware fact candidates for reviewing a v4 gold-ID mapping.

The source database is read-only. Candidate JSON is intended for the local
runtime directory and contains no sensitive fact content; the reviewer maps
stable ``fact_*`` labels to actual IDs in the template afterwards.
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
from pathlib import Path
from typing import Any


def load_gold(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, dict):
        payload = payload.get("items") or payload.get("cases") or []
    return [item for item in payload if isinstance(item, dict)]


def _tokens(text: Any) -> set[str]:
    compact = re.sub(r"\s+", "", str(text or ""))
    chars = [char for char in compact if "\u4e00" <= char <= "\u9fff" or char.isalnum()]
    return set(chars) | {"".join(chars[index:index + 2]) for index in range(max(0, len(chars) - 1))}


def _preview(fact: sqlite3.Row) -> str:
    if str(fact["sensitivity"] or "normal") != "normal":
        return "[敏感事实内容已隐藏]"
    content = re.sub(r"\s+", " ", str(fact["content"] or "")).strip()
    return content[:160] + ("…" if len(content) > 160 else "")


def build_candidates(
    conn: sqlite3.Connection,
    gold: list[dict[str, Any]],
    *,
    account_wxid: str,
    conversation_id: int,
    limit: int = 8,
) -> dict[str, Any]:
    conn.row_factory = sqlite3.Row
    facts = conn.execute(
        """
        SELECT id, subject, kind, content, status, as_of, confidence, sensitivity,
               evidence_message_ids_json
        FROM rag_facts
        WHERE account_wxid=? AND conversation_id=? AND status='active' AND enabled=1
        """,
        (account_wxid, conversation_id),
    ).fetchall()
    rendered_cases: list[dict[str, Any]] = []
    for case in gold:
        query = str(case.get("query_text") or case.get("id") or "")
        query_tokens = _tokens(query)
        ranked: list[tuple[float, sqlite3.Row]] = []
        for fact in facts:
            fact_tokens = _tokens(fact["content"])
            overlap = len(query_tokens & fact_tokens)
            score = overlap / max(1, min(len(query_tokens), len(fact_tokens)))
            if score:
                ranked.append((score, fact))
        ranked.sort(key=lambda item: (item[0], float(item[1]["confidence"] or 0.0)), reverse=True)
        candidates = []
        for score, fact in ranked[:limit]:
            try:
                evidence_ids = json.loads(fact["evidence_message_ids_json"] or "[]")
            except (TypeError, ValueError, json.JSONDecodeError):
                evidence_ids = []
            candidates.append({
                "fact_id": int(fact["id"]),
                "lexical_score": round(score, 4),
                "subject": fact["subject"],
                "kind": fact["kind"],
                "as_of": fact["as_of"],
                "confidence": fact["confidence"],
                "sensitivity": fact["sensitivity"],
                "evidence_message_ids": evidence_ids,
                "content_preview": _preview(fact),
            })
        rendered_cases.append({
            "id": case.get("id") or query,
            "query_text": query,
            "gold_labels": case.get("gold_fact_ids") or case.get("gold_document_ids") or [],
            "candidates": candidates,
        })
    return {
        "version": 1,
        "account_wxid": account_wxid,
        "conversation_id": conversation_id,
        "facts_considered": len(facts),
        "cases": rendered_cases,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--gold", type=Path, required=True)
    parser.add_argument("--account-wxid", required=True)
    parser.add_argument("--conversation-id", type=int, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=8)
    args = parser.parse_args()
    conn = sqlite3.connect(str(args.db))
    payload = build_candidates(
        conn,
        load_gold(args.gold),
        account_wxid=args.account_wxid,
        conversation_id=args.conversation_id,
        limit=max(1, args.limit),
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {args.out} for {len(payload['cases'])} gold cases")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
