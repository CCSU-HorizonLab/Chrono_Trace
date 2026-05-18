"""Shared privacy redaction for remote AI/RAG contexts."""

from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class RedactionResult:
    redacted_text: str
    entity_map_json: str
    pii_flags_json: str
    redaction_mode: str = "balanced"

    @property
    def entity_map(self) -> dict[str, str]:
        return json.loads(self.entity_map_json or "{}")

    @property
    def pii_flags(self) -> dict[str, bool]:
        return json.loads(self.pii_flags_json or "{}")


class PrivacyRedactor:
    """Rule based redactor with stable placeholders per account/conversation."""

    PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
        ("api_key", re.compile(r"(?i)\b(?:sk|api[_-]?key|token|secret)[-_:=\s]*[A-Za-z0-9_\-]{16,}\b")),
        ("id_card", re.compile(r"\b\d{17}[\dXx]\b")),
        ("bank_card", re.compile(r"\b(?:\d[ -]?){16,19}\b")),
        ("phone", re.compile(r"(?<!\d)(?:\+?86[-\s]?)?1[3-9]\d{9}(?!\d)")),
        ("address", re.compile(r"[\u4e00-\u9fa5]{2,}(?:省|市|区|县|镇|乡|路|街|巷|号楼?|单元|室)[\u4e00-\u9fa5A-Za-z0-9\-]{2,30}")),
    )

    def __init__(self, conn: Any | None = None):
        self.conn = conn

    def redact(
        self,
        text: str,
        *,
        account_wxid: str = "",
        conversation_id: int | None = None,
        source_table: str = "runtime",
        source_id: str = "",
        mode: str = "balanced",
    ) -> RedactionResult:
        original = str(text or "")
        if not original:
            return RedactionResult("", "{}", "{}")

        entity_map: dict[str, str] = {}
        pii_flags: dict[str, bool] = {}
        counters: dict[str, int] = {}
        redacted = original

        matches: list[tuple[int, int, str, str]] = []
        for entity_type, pattern in self.PATTERNS:
            for match in pattern.finditer(original):
                value = match.group(0)
                if entity_type == "bank_card":
                    digits = re.sub(r"\D", "", value)
                    if len(digits) < 16:
                        continue
                matches.append((match.start(), match.end(), entity_type, value))

        # Replace from the end so offsets remain stable.
        for start, end, entity_type, value in sorted(matches, key=lambda item: item[0], reverse=True):
            placeholder = self._placeholder(
                account_wxid,
                conversation_id,
                entity_type,
                value,
                counters,
            )
            redacted = redacted[:start] + placeholder + redacted[end:]
            entity_map[placeholder] = self._hash_value(value)
            pii_flags[entity_type] = True
            self._persist_entity(account_wxid, conversation_id, entity_type, value, placeholder)

        result = RedactionResult(
            redacted_text=redacted,
            entity_map_json=json.dumps(entity_map, ensure_ascii=False, sort_keys=True),
            pii_flags_json=json.dumps(pii_flags, ensure_ascii=False, sort_keys=True),
            redaction_mode=mode,
        )
        self._persist_cache(
            account_wxid,
            conversation_id,
            source_table,
            str(source_id or self._hash_value(original)),
            mode,
            result,
        )
        return result

    def strong_mask(self, text: str) -> str:
        """Last-resort local mask. It never preserves sensitive raw values."""
        masked = str(text or "")
        for entity_type, pattern in self.PATTERNS:
            if entity_type == "bank_card":
                masked = pattern.sub(lambda m: "[BANK_CARD]" if len(re.sub(r"\D", "", m.group(0))) >= 16 else m.group(0), masked)
            else:
                masked = pattern.sub(f"[{entity_type.upper()}]", masked)
        if len(masked) > 600:
            masked = masked[:600] + "..."
        return masked

    def _placeholder(
        self,
        account_wxid: str,
        conversation_id: int | None,
        entity_type: str,
        value: str,
        counters: dict[str, int],
    ) -> str:
        existing = self._lookup_placeholder(account_wxid, conversation_id, entity_type, value)
        if existing:
            return existing
        counters[entity_type] = counters.get(entity_type, 0) + 1
        suffix = self._hash_value(value)[:6].upper()
        return f"[{entity_type.upper()}_{suffix}]"

    def _hash_value(self, value: str) -> str:
        return hashlib.sha256(str(value or "").encode("utf-8")).hexdigest()

    def _ensure_schema(self) -> None:
        if not self.conn:
            return
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS privacy_entities (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                account_wxid TEXT NOT NULL,
                conversation_id INTEGER,
                entity_hash TEXT NOT NULL,
                entity_type TEXT NOT NULL,
                placeholder TEXT NOT NULL,
                first_seen_at INTEGER NOT NULL,
                last_seen_at INTEGER NOT NULL,
                UNIQUE(account_wxid, conversation_id, entity_hash, entity_type)
            )
            """
        )
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS privacy_redaction_cache (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                account_wxid TEXT NOT NULL,
                conversation_id INTEGER,
                source_table TEXT NOT NULL,
                source_id TEXT NOT NULL,
                redaction_mode TEXT NOT NULL,
                redacted_text TEXT NOT NULL,
                entity_map_json TEXT,
                pii_flags_json TEXT,
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL,
                UNIQUE(account_wxid, conversation_id, source_table, source_id, redaction_mode)
            )
            """
        )

    def _lookup_placeholder(
        self,
        account_wxid: str,
        conversation_id: int | None,
        entity_type: str,
        value: str,
    ) -> str:
        if not self.conn:
            return ""
        self._ensure_schema()
        row = self.conn.execute(
            """
            SELECT placeholder
            FROM privacy_entities
            WHERE account_wxid = ? AND COALESCE(conversation_id, -1) = COALESCE(?, -1)
              AND entity_hash = ? AND entity_type = ?
            LIMIT 1
            """,
            (account_wxid, conversation_id, self._hash_value(value), entity_type),
        ).fetchone()
        return str(row["placeholder"] if row else "")

    def _persist_entity(
        self,
        account_wxid: str,
        conversation_id: int | None,
        entity_type: str,
        value: str,
        placeholder: str,
    ) -> None:
        if not self.conn:
            return
        self._ensure_schema()
        now = int(time.time())
        self.conn.execute(
            """
            INSERT INTO privacy_entities
            (account_wxid, conversation_id, entity_hash, entity_type, placeholder, first_seen_at, last_seen_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(account_wxid, conversation_id, entity_hash, entity_type) DO UPDATE SET
                last_seen_at = excluded.last_seen_at
            """,
            (account_wxid, conversation_id, self._hash_value(value), entity_type, placeholder, now, now),
        )

    def _persist_cache(
        self,
        account_wxid: str,
        conversation_id: int | None,
        source_table: str,
        source_id: str,
        mode: str,
        result: RedactionResult,
    ) -> None:
        if not self.conn:
            return
        self._ensure_schema()
        now = int(time.time())
        self.conn.execute(
            """
            INSERT INTO privacy_redaction_cache
            (account_wxid, conversation_id, source_table, source_id, redaction_mode,
             redacted_text, entity_map_json, pii_flags_json, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(account_wxid, conversation_id, source_table, source_id, redaction_mode)
            DO UPDATE SET
                redacted_text = excluded.redacted_text,
                entity_map_json = excluded.entity_map_json,
                pii_flags_json = excluded.pii_flags_json,
                updated_at = excluded.updated_at
            """,
            (
                account_wxid,
                conversation_id,
                source_table,
                source_id,
                mode,
                result.redacted_text,
                result.entity_map_json,
                result.pii_flags_json,
                now,
                now,
            ),
        )
