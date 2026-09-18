"""Structured fact extraction boundary used by the shadow memory pipeline.

The LLM adapter is deliberately injected. This keeps extraction testable and
allows local/remote engines to share the same validation and quarantine rules.
"""

from __future__ import annotations

import json
from typing import Any, Callable


class FactExtractionError(ValueError):
    """Raised when an extractor response cannot be safely used as a fact."""


class StructuredFactExtractor:
    ALLOWED_STATUS = {"active", "superseded", "uncertain"}
    REQUIRED = {"subject", "kind", "content"}

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
