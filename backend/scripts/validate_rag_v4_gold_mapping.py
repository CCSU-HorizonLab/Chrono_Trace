"""Validate a reviewed v4 gold-ID mapping without exposing fact content."""

from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path
from typing import Any


def load_mapping(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def _numeric_id(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        result = int(str(value).strip())
    except (TypeError, ValueError):
        return None
    return result if result > 0 else None


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=? LIMIT 1",
        (table,),
    ).fetchone()
    return bool(row)


def validate_mapping(
    conn: sqlite3.Connection,
    mapping: dict[str, Any],
    *,
    account_wxid: str | None = None,
    conversation_id: int | None = None,
) -> dict[str, Any]:
    """Return a content-free validation result for a reviewed mapping."""
    errors: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    mapped: dict[str, int] = {}
    seen: dict[int, str] = {}
    for label, raw_value in mapping.items():
        label = str(label)
        if label.startswith("_") or raw_value in (None, ""):
            continue
        value = _numeric_id(raw_value)
        if value is None:
            errors.append({"label": label, "reason": "non_positive_numeric_id"})
            continue
        if value in seen:
            errors.append({"label": label, "reason": "duplicate_runtime_id", "other_label": seen[value]})
        else:
            seen[value] = label
        mapped[label] = value

        table = "rag_facts" if label.startswith("fact_") else None
        if table is None:
            if _table_exists(conn, "rag_facts"):
                table = "rag_facts"
            elif _table_exists(conn, "rag_documents"):
                table = "rag_documents"
        if table is None:
            errors.append({"label": label, "reason": "runtime_table_missing"})
            continue

        row = conn.execute(
            f"SELECT account_wxid, conversation_id, "
            f"{ 'status, enabled' if table == 'rag_facts' else 'enabled, superseded_by' } "
            f"FROM {table} WHERE id=? LIMIT 1",
            (value,),
        ).fetchone()
        if not row:
            errors.append({"label": label, "reason": "runtime_id_missing"})
            continue
        account = str(row[0] or "")
        conversation = int(row[1] or 0)
        if account_wxid is not None and account != str(account_wxid):
            errors.append({"label": label, "reason": "account_scope_mismatch"})
        if conversation_id is not None and conversation != int(conversation_id):
            errors.append({"label": label, "reason": "conversation_scope_mismatch"})
        if table == "rag_facts":
            if str(row[2] or "") != "active":
                errors.append({"label": label, "reason": "fact_not_active"})
            if not int(row[3] or 0):
                errors.append({"label": label, "reason": "fact_disabled"})
        elif not int(row[2] or 0) or row[3] is not None:
            errors.append({"label": label, "reason": "document_not_active"})

    if account_wxid is None or conversation_id is None:
        warnings.append({"reason": "mapping_scope_not_fully_constrained"})
    valid = not errors
    release_ready = valid and bool(mapped) and account_wxid is not None and conversation_id is not None
    return {
        "valid": valid,
        "release_ready": release_ready,
        "status": "ready" if release_ready else ("invalid" if errors else "pending_scope_or_entries"),
        "mapped_entries": len(mapped),
        "errors": errors,
        "warnings": warnings,
        "checked_ids": sorted(set(mapped.values())),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--mapping", type=Path, required=True)
    parser.add_argument("--account-wxid")
    parser.add_argument("--conversation-id", type=int)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    conn = sqlite3.connect(str(args.db))
    try:
        result = validate_mapping(
            conn,
            load_mapping(args.mapping),
            account_wxid=args.account_wxid,
            conversation_id=args.conversation_id,
        )
    finally:
        conn.close()
    rendered = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0 if result["release_ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
