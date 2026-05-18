"""Prepare fixed RAG v1 evaluation cases for manual no-RAG vs RAG comparison."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def load_samples(path: Path) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8"))


def build_empty_report(samples: list[dict]) -> dict:
    return {
        "version": 1,
        "instructions": (
            "For each sample, generate one output with RAG disabled and one with RAG enabled. "
            "RAG must not be worse on strategy, privacy safety, or identity separation."
        ),
        "items": [
            {
                "id": sample["id"],
                "category": sample["category"],
                "manual_check": sample.get("manual_check", []),
                "no_rag_output": "",
                "rag_output": "",
                "strategy_pass": None,
                "memory_pass": None,
                "style_pass": None,
                "privacy_pass": None,
                "identity_pass": None,
                "notes": "",
            }
            for sample in samples
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--samples",
        default="docs/goals/rag-v1-eval-samples.json",
        help="Path to anonymized RAG v1 evaluation samples.",
    )
    parser.add_argument(
        "--out",
        default="docs/goals/rag-v1-eval-report.template.json",
        help="Where to write the manual comparison report template.",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Validate samples and print the number of cases without writing a report.",
    )
    args = parser.parse_args()

    samples_path = Path(args.samples)
    out_path = Path(args.out)
    samples = load_samples(samples_path)
    if args.check:
        print(f"loaded {len(samples)} cases from {samples_path}")
        return 0
    report = build_empty_report(samples)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {out_path} ({len(report['items'])} cases)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
