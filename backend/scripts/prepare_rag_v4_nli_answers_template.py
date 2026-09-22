"""Create a content-free NLI answer skeleton from prepared judge inputs."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def _items(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, dict):
        payload = payload.get("items") or []
    return [item for item in payload if isinstance(item, dict)]


def build_template(input_path: Path) -> dict[str, Any]:
    items = []
    for source in _items(input_path):
        items.append({
            "id": str(source.get("id") or ""),
            "track": str(source.get("track") or ""),
            "answer": "",
            "evidence": [],
            "nli_label": "unknown",
            "judge_version": str(source.get("judge_version") or "nli-external-required-v1"),
            "prompt_version": str(source.get("prompt_version") or "rag-v4-faithfulness-v1"),
        })
    return {
        "_instructions": "由 judge 填写脱敏 answer/evidence，并将 nli_label 设为 entailed、contradicted 或 unknown；空答案不会通过发布校验。",
        "items": items,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    payload = build_template(args.input)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {args.out} for {len(payload['items'])} judge items")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
