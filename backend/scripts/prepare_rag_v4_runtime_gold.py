"""Build a contact-scoped numeric gold set from active, non-sensitive facts."""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Callable


BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.services.realtime.privacy_redactor import PrivacyRedactor  # noqa: E402
from app.services.realtime.rag_store import RagStore  # noqa: E402


def _parse_json(text: str) -> dict[str, Any]:
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", str(text or "").strip(), flags=re.I)
    for candidate in (cleaned, cleaned[cleaned.find("{"):cleaned.rfind("}") + 1]):
        if not candidate:
            continue
        try:
            payload = json.loads(candidate)
            if isinstance(payload, dict):
                return payload
        except (TypeError, ValueError, json.JSONDecodeError):
            pass
    return {}


def select_facts(
    conn: sqlite3.Connection,
    *,
    account_wxid: str,
    conversation_id: int,
    count: int,
) -> list[dict[str, Any]]:
    conn.row_factory = sqlite3.Row
    store = RagStore(conn)
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    redactor = PrivacyRedactor(None)
    for fact in store.list_facts(account_wxid, conversation_id):
        if str(fact.get("sensitivity") or "normal") != "normal":
            continue
        try:
            evidence_ids = json.loads(fact.get("evidence_message_ids_json") or "[]")
        except (TypeError, ValueError, json.JSONDecodeError):
            evidence_ids = []
        if not evidence_ids:
            continue
        content = str(fact.get("content") or "").strip()
        evidence = store.list_fact_evidence_text(evidence_ids)
        source = evidence or content
        if not source:
            continue
        redacted = redactor.redact(source, mode="balanced").redacted_text[:360]
        grouped[str(fact.get("kind") or "unknown")].append({
            "fact_id": int(fact["id"]),
            "kind": str(fact.get("kind") or "unknown"),
            "subject": str(fact.get("subject") or ""),
            "confidence": float(fact.get("confidence") or 0.0),
            "redacted_fact": redacted,
        })
    for values in grouped.values():
        values.sort(key=lambda item: item["confidence"], reverse=True)
    selected: list[dict[str, Any]] = []
    kinds = sorted(grouped, key=lambda key: (-len(grouped[key]), key))
    offset = 0
    while len(selected) < count and kinds:
        remaining = []
        for kind in kinds:
            values = grouped[kind]
            if offset < len(values):
                selected.append(values[offset])
                remaining.append(kind)
                if len(selected) >= count:
                    break
        kinds = remaining
        offset += 1
    return selected


def generate_questions(
    facts: list[dict[str, Any]],
    llm_call: Callable[[list[dict[str, str]]], str],
    *,
    batch_size: int = 8,
) -> list[dict[str, Any]]:
    questions: dict[int, str] = {}
    for offset in range(0, len(facts), max(1, batch_size)):
        chunk = facts[offset:offset + max(1, batch_size)]
        payload = [{key: item[key] for key in ("fact_id", "kind", "subject", "redacted_fact")} for item in chunk]
        messages = [
            {"role": "system", "content": "根据每条脱敏事实生成一个自然、简短、可由该事实回答的中文记忆问句。不要在问题中直接泄露答案。只返回 JSON：{\"items\":[{\"fact_id\":1,\"query\":\"...\"}]}。"},
            {"role": "user", "content": json.dumps({"items": payload}, ensure_ascii=False)},
        ]
        try:
            parsed = _parse_json(llm_call(messages))
        except Exception:
            parsed = {}
        for item in parsed.get("items") or []:
            try:
                fact_id = int(item.get("fact_id"))
            except (TypeError, ValueError):
                continue
            query = str(item.get("query") or "").strip()
            if query:
                questions[fact_id] = query
        for fact in chunk:
            if fact["fact_id"] in questions:
                continue
            single_messages = [
                {"role": "system", "content": "根据脱敏事实生成一个自然、简短、可由该事实回答的中文记忆问句。不要在问题中直接泄露答案。只返回 JSON：{\"query\":\"...\"}。"},
                {"role": "user", "content": json.dumps({key: fact[key] for key in ("fact_id", "kind", "subject", "redacted_fact")}, ensure_ascii=False)},
            ]
            try:
                single = _parse_json(llm_call(single_messages))
            except Exception:
                single = {}
            query = str(single.get("query") or "").strip()
            if query:
                questions[fact["fact_id"]] = query
    output = []
    for index, fact in enumerate(facts, 1):
        query = questions.get(fact["fact_id"])
        if not query:
            continue
        output.append({
            "id": f"runtime_fact_{index:02d}",
            "category": fact["kind"],
            "query_text": query,
            "gold_fact_ids": [fact["fact_id"]],
            "expected_retrieve": True,
            "expected_scope": "all",
        })
    return output


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--account-wxid", required=True)
    parser.add_argument("--conversation-id", type=int, required=True)
    parser.add_argument("--count", type=int, default=36)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    conn = sqlite3.connect(str(args.db))
    facts = select_facts(conn, account_wxid=args.account_wxid, conversation_id=args.conversation_id, count=max(1, args.count))
    conn.close()

    from app.services.realtime.llm_engine import LLMSuggestionEngine
    engine = LLMSuggestionEngine(timeout=90)
    model = engine._get_active_model()
    if not model:
        raise SystemExit("未配置激活模型")

    def call(messages: list[dict[str, str]]) -> str:
        return engine._call_api_with_messages(model, messages, max_tokens=1536, temperature=0.0, request_tag="analysis", use_json_mode=True)

    items = generate_questions(facts, call)
    payload = {
        "version": "runtime-numeric-v1",
        "origin": "llm-generated-from-redacted-active-facts",
        "account_wxid": args.account_wxid,
        "conversation_id": args.conversation_id,
        "requested_cases": max(1, args.count),
        "generated_cases": len(items),
        "items": items,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"generated": len(items), "out": str(args.out)}, ensure_ascii=False))
    return 0 if len(items) >= min(30, max(1, args.count)) else 1


if __name__ == "__main__":
    raise SystemExit(main())
