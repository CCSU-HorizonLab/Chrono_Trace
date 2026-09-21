"""Replay the same gold queries through the three retrieval tracks.

This is a component-level replay runner. It copies the source SQLite database
to a caller-provided output database, clears only the copied retrieval logs,
and writes one log per (case, track). The source database is never mutated.
Answer generation and NLI judging remain separate concerns handled by the
evaluation report script.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "backend") not in sys.path:
    sys.path.insert(0, str(ROOT / "backend"))

from app.services.realtime import rag_retriever as rag_retriever_module  # noqa: E402
from app.services.realtime.rag_config import load_rag_settings  # noqa: E402
from app.services.realtime.rag_retriever import RagRetriever  # noqa: E402
from app.services.realtime.rag_store import RagStore  # noqa: E402


TRACKS = ("no_rag", "document_rag", "fact_path")


def load_gold(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, dict):
        payload = payload.get("items") or payload.get("cases") or []
    return [item for item in payload if isinstance(item, dict)]


def _copy_database(source_path: Path, output_path: Path) -> sqlite3.Connection:
    if source_path.resolve() == output_path.resolve():
        raise ValueError("replay output database must differ from source database")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    source = sqlite3.connect(str(source_path))
    output = sqlite3.connect(str(output_path))
    source.backup(output)
    source.close()
    output.row_factory = sqlite3.Row
    output.execute("DELETE FROM rag_retrieval_logs")
    output.commit()
    return output


def _write_track_log(
    store: RagStore,
    *,
    account_wxid: str,
    conversation_id: int,
    query: str,
    track: str,
    result: dict[str, Any] | None,
    query_scope: str,
) -> None:
    if track == "no_rag":
        store.insert_retrieval_log(
            account_wxid=account_wxid,
            conversation_id=conversation_id,
            query_text=query,
            rag_enabled=False,
            rag_retrieved=False,
            rag_gate_decision="no_hit",
            rag_gate_reason="rag_disabled",
            rag_strategy="none",
            retrieval_source="none",
            query_scope=query_scope,
        )
        return
    result = result or {}
    items = list(result.get("items") or [])
    document_ids = [int(item.get("document_id")) for item in items if item.get("document_id") is not None]
    fact_ids = document_ids if track == "fact_path" else []
    scores = {
        str(item.get("document_id")): float(item.get("score") or 0.0)
        for item in items
        if item.get("document_id") is not None
    }
    decision = "inject" if items else "no_hit"
    store.insert_retrieval_log(
        account_wxid=account_wxid,
        conversation_id=conversation_id,
        query_text=query,
        document_ids=document_ids,
        fact_ids=fact_ids,
        retrieval_scores=scores,
        index_status=(result.get("status") or {}).get("status"),
        elapsed_ms=int(result.get("elapsed_ms") or 0),
        timed_out=bool(result.get("timed_out")),
        degraded=bool(result.get("degraded")),
        degrade_reason=result.get("degrade_reason"),
        rag_enabled=True,
        rag_retrieved=bool(items),
        rag_hit_count=len(items),
        rag_gate_decision=decision,
        rag_gate_reason="replay_retrieval_result",
        rag_top_score=float(items[0].get("score") or 0.0) if items else 0.0,
        rag_strategy=result.get("strategy"),
        retrieval_source="fact" if track == "fact_path" else "document",
        semantic_fact_count=len(items) if track == "fact_path" else 0,
        query_scope=query_scope,
    )


def replay(
    source_db: Path,
    output_db: Path,
    gold: list[dict[str, Any]],
    *,
    account_wxid: str,
    conversation_id: int,
    retriever: Any | None = None,
) -> dict[str, Any]:
    """Run all tracks and return a replay manifest."""
    conn = _copy_database(source_db, output_db)
    store = RagStore(conn)
    retriever = retriever or RagRetriever(store=store)
    original_loader = rag_retriever_module.load_rag_settings
    base_settings = dict(load_rag_settings())
    counts = {track: 0 for track in TRACKS}
    errors: list[dict[str, Any]] = []
    try:
        for case in gold:
            query = str(case.get("query_text") or case.get("id") or "").strip()
            if not query:
                continue
            scope = str(case.get("expected_scope") or base_settings.get("rag_query_scope") or "latest_turn")
            for track in TRACKS:
                counts[track] += 1
                if track == "no_rag":
                    _write_track_log(
                        store,
                        account_wxid=account_wxid,
                        conversation_id=conversation_id,
                        query=query,
                        track=track,
                        result=None,
                        query_scope=scope,
                    )
                    continue
                settings = dict(base_settings)
                settings["rag_enabled"] = True
                settings["rag_fact_read_enabled"] = track == "fact_path"
                rag_retriever_module.load_rag_settings = lambda settings=settings: settings
                try:
                    result = retriever.retrieve(
                        account_wxid=account_wxid,
                        conversation_id=conversation_id,
                        query=query,
                    )
                    _write_track_log(
                        store,
                        account_wxid=account_wxid,
                        conversation_id=conversation_id,
                        query=query,
                        track=track,
                        result=result,
                        query_scope=scope,
                    )
                except Exception as exc:  # replay must preserve a per-case failure
                    errors.append({"id": case.get("id") or query, "track": track, "error": str(exc)})
                    _write_track_log(
                        store,
                        account_wxid=account_wxid,
                        conversation_id=conversation_id,
                        query=query,
                        track=track,
                        result={"items": [], "strategy": track, "degraded": True, "degrade_reason": "replay_error"},
                        query_scope=scope,
                    )
        conn.commit()
    finally:
        rag_retriever_module.load_rag_settings = original_loader
        conn.close()
    return {
        "version": 1,
        "source_db": str(source_db),
        "output_db": str(output_db),
        "cases": len(gold),
        "tracks": TRACKS,
        "rows_written": sum(counts.values()),
        "rows_by_track": counts,
        "errors": errors,
        "generated_at": int(time.time()),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, required=True, help="Source SQLite database; never modified")
    parser.add_argument("--out-db", type=Path, required=True, help="Copied SQLite database receiving replay logs")
    parser.add_argument("--gold", type=Path, required=True)
    parser.add_argument("--account-wxid", required=True)
    parser.add_argument("--conversation-id", type=int, required=True)
    parser.add_argument("--manifest", type=Path)
    args = parser.parse_args()
    manifest = replay(
        args.db,
        args.out_db,
        load_gold(args.gold),
        account_wxid=args.account_wxid,
        conversation_id=args.conversation_id,
    )
    rendered = json.dumps(manifest, ensure_ascii=False, indent=2)
    if args.manifest:
        args.manifest.parent.mkdir(parents=True, exist_ok=True)
        args.manifest.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 1 if manifest["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
