"""Backfill vectors for legacy active facts in one contact scope."""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "backend") not in sys.path:
    sys.path.insert(0, str(ROOT / "backend"))

from app.services.realtime.rag.indexer import RagIndexer
from app.services.realtime.rag.store import RagStore


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--account-wxid", required=True)
    parser.add_argument("--conversation-id", type=int, required=True)
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument("--manifest", type=Path)
    args = parser.parse_args()

    conn = sqlite3.connect(str(args.db))
    conn.row_factory = sqlite3.Row
    result = RagIndexer(store=RagStore(conn)).backfill_fact_embeddings(
        account_wxid=args.account_wxid,
        conversation_id=args.conversation_id,
        batch_size=max(1, args.batch_size),
    )
    conn.close()
    rendered = json.dumps(result, ensure_ascii=False, indent=2)
    if args.manifest:
        args.manifest.parent.mkdir(parents=True, exist_ok=True)
        args.manifest.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 1 if result["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
