"""P0.4 shadow verification: recompute fact confidence distribution on a copy.

Read-only against the real DB (or a copy path passed via --db).  Prints old vs
new histograms to prove the calibration actually separates the distribution
before any backfill/switch decision.

Usage (from repository root)::

    python backend/scripts/shadow_verify_confidence.py
    python backend/scripts/shadow_verify_confidence.py --db path/to/copy.db
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app.services.realtime.rag.semantic_memory import calibrate_fact_confidence  # noqa: E402

DEFAULT_DB = ROOT / "backend" / "data" / "chrono_trace.db"

BUCKETS = [0.2, 0.3, 0.4, 0.45, 0.5, 0.55, 0.6, 0.65, 0.7, 0.75, 0.8, 0.85, 0.9, 0.95, 1.0]


def _bucket(value: float) -> str:
    prev = 0.0
    for b in BUCKETS:
        if value < b:
            return f"[{prev:.2f},{b:.2f})"
        prev = b
    return f"[{BUCKETS[-1]:.2f},1]"


def _histogram(values: list[float], title: str) -> None:
    counter = Counter(_bucket(v) for v in values)
    print(f"\n== {title} (n={len(values)}) ==")
    for bucket in (_bucket(b - 1e-9) for b in BUCKETS):
        count = counter.get(bucket, 0)
        bar = "#" * min(60, count)
        print(f"{bucket:>14} {count:5d} {bar}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default=str(DEFAULT_DB))
    args = parser.parse_args()

    conn = sqlite3.connect(f"file:{Path(args.db).as_posix()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """
        SELECT confidence, kind, evidence_message_ids_json
        FROM rag_facts
        WHERE status = 'active' AND enabled = 1
        """
    ).fetchall()
    conn.close()
    if not rows:
        print("no active facts found")
        return 1

    old_values: list[float] = []
    new_values: list[float] = []
    marker_count = 0
    multi_evidence = 0
    for row in rows:
        try:
            evidence_ids = json.loads(row["evidence_message_ids_json"] or "[]")
        except Exception:
            evidence_ids = []
        evidence_count = len([v for v in evidence_ids if isinstance(v, int)])
        kind = str(row["kind"] or "")
        if kind == "marker_fallback":
            marker_count += 1
        if evidence_count >= 2:
            multi_evidence += 1
        old = float(row["confidence"] or 0.0)
        new = calibrate_fact_confidence(
            old,
            evidence_count=evidence_count,
            memory_kind=kind,
        )
        old_values.append(old)
        new_values.append(new)

    _histogram(old_values, "旧分布（confidence=余弦相似度）")
    _histogram(new_values, "新分布（校准后）")

    high = [v for v in new_values if v >= 0.80]
    quarantine = [v for v in new_values if v < 0.45]
    mid = len(new_values) - len(high) - len(quarantine)
    print("\n== 分层（校准后） ==")
    print(f"高置信 >=0.80: {len(high)} 条")
    print(f"中间带:        {mid} 条")
    print(f"低置信 <0.45:  {len(quarantine)} 条")
    print(f"marker_fallback: {marker_count} 条（已封顶 0.55）")
    print(f"多证据 >=2 条:  {multi_evidence} 条")

    ok = bool(high) and bool(quarantine)
    print(f"\n验收（高置信与低置信集合均非空）: {'PASS' if ok else 'FAIL'}")
    return 0 if ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
