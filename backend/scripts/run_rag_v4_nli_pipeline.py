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
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start < 0 or end <= start:
            return {}
        try:
            payload = json.loads(cleaned[start:end + 1])
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


def _batch_messages(items: list[dict[str, Any]], stage: str) -> list[dict[str, str]]:
    if stage == "answer":
        records = [{
            "id": str(item.get("id") or ""),
            "query": str(item.get("query") or ""),
            "evidence": [str(value) for value in item.get("evidence") or []],
        } for item in items]
        instruction = "逐条仅根据 evidence 回答 query；证据不足时明确说证据不足。只返回 JSON：{\"items\":[{\"id\":\"...\",\"answer\":\"...\"}]}。"
    else:
        records = [{
            "id": str(item.get("id") or ""),
            "query": str(item.get("query") or ""),
            "answer": str(item.get("answer") or ""),
            "evidence": [str(value) for value in item.get("evidence") or []],
        } for item in items]
        instruction = "逐条判断 answer 是否被 evidence 支持。label 只能是 entailed、contradicted、unknown。只返回 JSON：{\"items\":[{\"id\":\"...\",\"label\":\"...\",\"reason\":\"...\"}]}。"
    return [
        {"role": "system", "content": instruction},
        {"role": "user", "content": json.dumps({"items": records}, ensure_ascii=False)},
    ]


def run_stage(
    payload: dict[str, Any],
    *,
    stage: str,
    llm_call: Callable[[list[dict[str, str]]], str],
    limit: int | None = None,
    batch_size: int = 1,
    safe_fallback: bool = False,
) -> dict[str, Any]:
    items = [dict(item) for item in payload.get("items") or [] if isinstance(item, dict)]
    processed = 0
    if stage not in {"answer", "judge"}:
        raise ValueError(f"unsupported stage: {stage}")
    candidates = [
        item for item in items
        if (
            stage == "answer" and not str(item.get("answer") or "").strip()
        ) or (
            stage == "judge"
            and str(item.get("answer") or "").strip()
            and str(item.get("judge_status") or "") != "complete"
            and str(item.get("nli_label") or "").lower() not in {"entailed", "contradicted"}
        )
    ]
    if limit is not None:
        candidates = candidates[:max(0, limit)]
    size = max(1, int(batch_size))
    for offset in range(0, len(candidates), size):
        chunk = candidates[offset:offset + size]
        if len(chunk) == 1:
            parsed = _parse_json(llm_call(_answer_messages(chunk[0]) if stage == "answer" else _judge_messages(chunk[0])))
            responses = [dict(parsed, id=str(chunk[0].get("id") or ""))]
        else:
            parsed = _parse_json(llm_call(_batch_messages(chunk, stage)))
            responses = [value for value in parsed.get("items") or [] if isinstance(value, dict)]
        by_id = {str(value.get("id") or ""): value for value in responses}
        for item in chunk:
            item_id = str(item.get("id") or "")
            response = by_id.get(item_id, {})
            # Some reasoning/mixed-output models truncate or wrap a batch even
            # when single JSON responses are reliable. Retry only the missing
            # entries so completed batch items are never paid for twice.
            if not response and len(chunk) > 1:
                retry = _parse_json(
                    llm_call(_answer_messages(item) if stage == "answer" else _judge_messages(item))
                )
                response = dict(retry, id=item_id)
            if stage == "answer":
                answer = str(response.get("answer") or response.get("response") or response.get("content") or "").strip()
                if answer:
                    item["answer"] = answer
                    processed += 1
                elif safe_fallback:
                    item["answer"] = "证据不足，无法根据当前证据回答。"
                    item["answer_status"] = "degraded_model_output"
                    item["nli_label"] = "unknown"
                    processed += 1
            else:
                label = str(response.get("label") or "").lower()
                item["nli_label"] = label if label in VALID_LABELS else "unknown"
                item["judge_reason"] = str(response.get("reason") or "")[:500]
                item["judge_status"] = "complete"
                processed += 1
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
    parser.add_argument("--batch-size", type=int, default=8)
    parser.add_argument("--safe-fallback", action="store_true")
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
    result = run_stage(
        _load(source), stage=args.stage, llm_call=call,
        limit=args.limit, batch_size=max(1, args.batch_size), safe_fallback=args.safe_fallback,
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"stage": args.stage, "processed": result["last_stage_processed"], "out": str(args.out)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
