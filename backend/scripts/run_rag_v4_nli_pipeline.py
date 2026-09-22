"""Generate de-identified replay answers and judge their evidence support.

This CLI only sends the already prepared ``query`` and ``evidence`` fields to
the configured OpenAI-compatible model.  It supports two explicit stages so a
different model/configuration can be used for judging if desired.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Callable


VALID_LABELS = {"entailed", "contradicted", "unknown"}


def _load(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {"items": []}


def _parse_json(text: str) -> dict[str, Any]:
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", str(text or "").strip(), flags=re.I)
    try:
        payload = json.loads(cleaned)
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _answer_messages(item: dict[str, Any]) -> list[dict[str, str]]:
    evidence = item.get("evidence") if isinstance(item.get("evidence"), list) else []
    payload = {"query": str(item.get("query") or ""), "evidence": [str(value) for value in evidence]}
    return [
        {"role": "system", "content": "仅根据给定 evidence 回答 query。证据不足时明确回答证据不足。只返回 JSON：{\"answer\":\"...\"}。"},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
    ]


def _judge_messages(item: dict[str, Any]) -> list[dict[str, str]]:
    evidence = item.get("evidence") if isinstance(item.get("evidence"), list) else []
    payload = {
        "query": str(item.get("query") or ""),
        "answer": str(item.get("answer") or ""),
        "evidence": [str(value) for value in evidence],
    }
    return [
        {"role": "system", "content": "判断 answer 是否被 evidence 支持。label 只能是 entailed、contradicted、unknown。只返回 JSON：{\"label\":\"...\",\"reason\":\"...\"}。"},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
    ]


def run_stage(
    payload: dict[str, Any],
    *,
    stage: str,
    llm_call: Callable[[list[dict[str, str]]], str],
    limit: int | None = None,
) -> dict[str, Any]:
    items = [dict(item) for item in payload.get("items") or [] if isinstance(item, dict)]
    processed = 0
    for item in items:
        if limit is not None and processed >= limit:
            break
        if stage == "answer":
            if str(item.get("answer") or "").strip():
                continue
            parsed = _parse_json(llm_call(_answer_messages(item)))
            answer = str(parsed.get("answer") or "").strip()
            if answer:
                item["answer"] = answer
                processed += 1
        elif stage == "judge":
            if not str(item.get("answer") or "").strip():
                continue
            current = str(item.get("nli_label") or "").lower()
            if current in {"entailed", "contradicted"}:
                continue
            parsed = _parse_json(llm_call(_judge_messages(item)))
            label = str(parsed.get("label") or "").lower()
            item["nli_label"] = label if label in VALID_LABELS else "unknown"
            item["judge_reason"] = str(parsed.get("reason") or "")[:500]
            processed += 1
        else:
            raise ValueError(f"unsupported stage: {stage}")
    result = dict(payload)
    result["items"] = items
    result["last_stage"] = stage
    result["last_stage_processed"] = processed
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--stage", choices=("answer", "judge"), required=True)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--timeout", type=int, default=90)
    args = parser.parse_args()

    backend_root = str(Path(__file__).resolve().parents[1])
    if backend_root not in sys.path:
        sys.path.insert(0, backend_root)
    from app.services.realtime.llm_engine import LLMSuggestionEngine

    engine = LLMSuggestionEngine(timeout=max(10, args.timeout))
    model_config = engine._get_active_model()
    if not model_config:
        raise SystemExit("未配置激活模型，不能运行 NLI pipeline")

    def call(messages: list[dict[str, str]]) -> str:
        return engine._call_api_with_messages(
            model_config,
            messages,
            max_tokens=512,
            temperature=0.0,
            request_tag="analysis",
            use_json_mode=True,
        )

    source = args.out if args.out.exists() else args.input
    result = run_stage(_load(source), stage=args.stage, llm_call=call, limit=args.limit)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"stage": args.stage, "processed": result["last_stage_processed"], "out": str(args.out)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
