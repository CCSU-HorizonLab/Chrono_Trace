"""Structured fact extraction boundary used by the shadow memory pipeline.

The LLM adapter is deliberately injected. This keeps extraction testable and
allows local/remote engines to share the same validation and quarantine rules.
"""

from __future__ import annotations

import json
from typing import Any, Callable


class FactExtractionError(ValueError):
    """Raised when an extractor response cannot be safely used as a fact."""


CANONICAL_FACT_KINDS = {
    "preference",
    "plan",
    "promise",
    "personal_fact",
    "event",
    "boundary",
    "mood",
    "relation_state",
}

_KIND_ALIASES = {
    "preference_like": "preference",
    "preference_dislike": "preference",
    "food_or_place": "preference",
    "hobby_or_game": "preference",
    "plan_or_appointment": "plan",
    "promise_or_commitment": "promise",
    "personal_profile": "personal_fact",
    "relationship_boundary": "boundary",
    "relationship_state": "relation_state",
    "recurring_habit": "personal_fact",
    "shared_memory": "event",
    "marker_fallback": "event",
}


def normalize_fact_kind(kind: Any) -> str:
    """Collapse extractor and legacy labels into stable maintenance buckets."""
    normalized = str(kind or "").strip().lower().replace("-", "_").replace(" ", "_")
    if normalized in CANONICAL_FACT_KINDS:
        return normalized
    return _KIND_ALIASES.get(normalized, "event")


class StructuredFactExtractor:
    ALLOWED_STATUS = {"active", "superseded", "uncertain"}
    REQUIRED = {"subject", "kind", "content"}
    FUSION_ACTIONS = {"ADD", "UPDATE", "INVALIDATE", "MERGE", "NOOP", "DENY"}

    def __init__(self, llm_call: Callable[[str], Any] | None = None):
        self.llm_call = llm_call

    def extract(self, prompt: str) -> list[dict[str, Any]]:
        if self.llm_call is None:
            return []
        raw = self.llm_call(prompt)
        if isinstance(raw, str):
            try:
                raw = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise FactExtractionError("fact extractor returned invalid JSON") from exc
        if isinstance(raw, dict):
            raw = raw.get("facts") or []
        if not isinstance(raw, list):
            raise FactExtractionError("fact extractor response must be a JSON array")
        facts: list[dict[str, Any]] = []
        for item in raw:
            facts.append(self.validate(item))
        return facts

    def validate(self, item: Any) -> dict[str, Any]:
        if not isinstance(item, dict) or not self.REQUIRED.issubset(item):
            raise FactExtractionError("fact requires subject, kind and content")
        content = str(item.get("content") or "").strip()
        if not content or len(content) > 500:
            raise FactExtractionError("fact content must be 1..500 characters")
        status = str(item.get("status") or "active")
        if status not in self.ALLOWED_STATUS:
            raise FactExtractionError(f"invalid fact status: {status}")
        try:
            confidence = float(item.get("confidence") or 0.0)
        except (TypeError, ValueError) as exc:
            raise FactExtractionError("invalid fact confidence") from exc
        if not 0.0 <= confidence <= 1.0:
            raise FactExtractionError("fact confidence must be between 0 and 1")
        evidence = item.get("evidence_message_ids") or []
        if not isinstance(evidence, list) or any(not str(value).isdigit() for value in evidence):
            raise FactExtractionError("evidence_message_ids must contain numeric ids")
        return {
            "subject": str(item.get("subject") or "").strip()[:80],
            "kind": str(item.get("kind") or "unknown").strip()[:80],
            "content": content,
            "status": status,
            "as_of": item.get("as_of"),
            "valid_from": item.get("valid_from"),
            "valid_to": item.get("valid_to"),
            "confidence": confidence,
            "sensitivity": str(item.get("sensitivity") or "normal"),
            "evidence_message_ids": [int(value) for value in evidence],
            "source_window": item.get("source_window") or {},
        }

    def decide_fusion(
        self,
        prompt: str,
        *,
        candidate_ids: set[int],
        denied_ids: set[int] = frozenset(),
        strict_batch: bool = True,
    ) -> list[dict[str, Any]]:
        """Ask the injected model how one incoming fact relates to old facts.

        This intentionally validates a much narrower contract than extraction.
        Callers treat any parsing or validation problem as ADD, because an
        accidental supersede loses useful active memory from the read side.

        denied_ids 是用户标记「不准确」的事实：它们不在 active 候选里，
        唯一合法的动作是 DENY（新事实是对已否认说法的重述，丢弃新事实）。

        strict_batch：任一决策条目非法即抛错废整批（调用方整批回退
        ADD）——普通融合路径的防幻觉护栏：id 脱靶/动作越界说明模型在
        瞎编，同批幸存的 UPDATE 同样不可信，整批作废才安全。带
        denied_refs 的纠错路径传 False：逐条跳过（该事实回落 ADD），
        保住同批合法 DENY——整批作废会让换措辞的否认重述趁虚复活。
        """
        if self.llm_call is None:
            raise FactExtractionError("fact fusion requires an llm_call")

        def _reject(reason: str) -> None:
            if strict_batch:
                raise FactExtractionError(reason)

        raw = self.llm_call(prompt)
        if isinstance(raw, str):
            try:
                raw = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise FactExtractionError("fact fusion returned invalid JSON") from exc
        if not isinstance(raw, dict):
            raise FactExtractionError("fact fusion response must be an object")
        decisions = raw.get("decisions")
        if not isinstance(decisions, list):
            raise FactExtractionError("fact fusion response requires decisions")
        validated: list[dict[str, Any]] = []
        seen: set[int] = set()
        for item in decisions:
            if not isinstance(item, dict):
                _reject("fact fusion decision is not an object")
                continue
            try:
                fact_id = int(item.get("fact_id"))
            except (TypeError, ValueError):
                _reject("fact fusion decision has invalid fact_id")
                continue
            action = str(item.get("action") or "").upper()
            if fact_id in seen:
                _reject(f"duplicate fact fusion decision for #{fact_id}")
                continue
            if fact_id in denied_ids:
                # 否认事实只能被 DENY 引用——它已 disabled，不是维护对象
                if action != "DENY":
                    _reject(f"denied fact #{fact_id} only accepts DENY")
                    continue
            elif fact_id in candidate_ids:
                # DENY 只指向否认事实；对 active 候选输出 DENY 是模型混淆
                if action == "DENY":
                    _reject(f"DENY targets active candidate #{fact_id}")
                    continue
                if action not in self.FUSION_ACTIONS:
                    _reject(f"unknown fact fusion action {action!r} for #{fact_id}")
                    continue
            else:
                _reject(f"fact fusion decision targets unknown fact #{fact_id}")
                continue
            seen.add(fact_id)
            validated.append(
                {
                    "fact_id": fact_id,
                    "action": action,
                    "reason": str(item.get("reason") or "").strip()[:200],
                }
            )
        return validated
