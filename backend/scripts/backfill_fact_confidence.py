"""Backfill calibrated confidence onto existing shadow_semantic facts.

P0.4 存量回填：旧 confidence 直接等于 embedding 余弦相似度（分布塌缩在
0.5~0.7）。本脚本用 calibrate_fact_confidence 按旧值（作为语义分量输入）、
证据消息数与 memory_kind 重算。llm_shadow 事实的 confidence 来自 LLM 自报，
不在回填范围。

默认 dry-run 只输出分布对比；--apply 才写入。

Usage (from repository root)::

    python backend/scripts/backfill_fact_confidence.py            # dry-run
    python backend/scripts/backfill_fact_confidence.py --apply    # 写入
    python backend/scripts/backfill_fact_confidence.py --db copy.db --apply
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app.services.realtime.rag.semantic_memory import calibrate_fact_confidence  # noqa: E402

DEFAULT_DB = ROOT / "backend" / "data" / "chrono_trace.db"


def _bucket(value: float) -> str:
    if value < 0.50:
        return "<0.50"
    if value < 0.60:
        return "[0.50,0.60)"
    if value < 0.70:
        return "[0.60,0.70)"
    if value < 0.80:
        return "[0.70,0.80)"
    if value < 0.95:
        return "[0.80,0.95)"
    return ">=0.95"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default=str(DEFAULT_DB))
    parser.add_argument("--apply", action="store_true", help="写入回填（默认 dry-run）")
    args = parser.parse_args()

    uri = f"file:{Path(args.db).as_posix()}?mode={'rw' if args.apply else 'ro'}"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """
        SELECT id, confidence, kind, evidence_message_ids_json, summary_method
        FROM rag_facts
        WHERE status = 'active' AND enabled = 1
        """
    ).fetchall()
    if not rows:
        print("no active facts")
        return 1

    updates: list[tuple[float, int]] = []
    old_hist: Counter[str] = Counter()
    new_hist: Counter[str] = Counter()
    skipped = 0
    for row in rows:
        if str(row["summary_method"] or "") == "llm_shadow":
            skipped += 1
            continue
        try:
            evidence_ids = json.loads(row["evidence_message_ids_json"] or "[]")
        except Exception:
            evidence_ids = []
        evidence_count = len([v for v in evidence_ids if isinstance(v, int)])
        old = float(row["confidence"] or 0.0)
        new = calibrate_fact_confidence(
            old,
            evidence_count=evidence_count,
            memory_kind=str(row["kind"] or ""),
        )
        old_hist[_bucket(old)] += 1
        new_hist[_bucket(new)] += 1
        if abs(new - old) > 1e-6:
            updates.append((new, int(row["id"])))

    print(f"total active facts: {len(rows)} (llm_shadow skipped: {skipped})")
    print(f"{'bucket':>12} {'old':>6} {'new':>6}")
    for bucket in ("<0.50", "[0.50,0.60)", "[0.60,0.70)", "[0.70,0.80)", "[0.80,0.95)", ">=0.95"):
        print(f"{bucket:>12} {old_hist[bucket]:>6} {new_hist[bucket]:>6}")

    if not args.apply:
        print(f"\ndry-run: {len(updates)} rows would be updated. Re-run with --apply to write.")
        return 0

    started = time.time()
    conn.executemany(
        "UPDATE rag_facts SET confidence = ?, updated_at = ? WHERE id = ?",
        [(c, int(time.time()), fid) for c, fid in updates],
    )
    conn.commit()
    print(f"\napplied {len(updates)} updates in {time.time() - started:.1f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
