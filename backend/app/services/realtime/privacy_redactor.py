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


# G4:受保护的作品译名片段——这些词含"路/街/道"等字符,会被地址模式
# 误伤(如"路易吉鬼屋"的"路"被当成路名后缀)。命中即整体豁免地址判定。
PROTECTED_NAME_FRAGMENTS: tuple[str, ...] = (
    "路易吉",
    "马里奥",
    "塞尔达",
    "皮卡丘",
    "宝可梦",
    "海拉鲁",
    "原神",
    "星穹铁道",
    "艾尔登",
    "法环",
    "黑神话",
    "悟空传",
    "霍格沃茨",
    "哈利波特",
    "中土世界",
    "赛博朋克",
)

# G4:裸路名(无门牌数字)需要居住/方位语境才判为地址,否则大概率是
# 作品名、游戏地名(中路/上路)或普通名词。
_ADDRESS_ROAD_SUFFIXES = ("路", "街", "巷", "道")
_ADDRESS_CONTEXT_MARKERS = (
    "住在",
    "家在",
    "位于",
    "地址",
    "址在",
    "搬到",
    "迁至",
    "小区",
    "号楼",
    "单元",
    "宿舍",
    "公寓",
    "门店",
    "校区",
)


def _address_match_is_false_positive(original: str, start: int, end: int) -> bool:
    """裸路名误伤判定:路/街/巷/道 后缀且无门牌数字、无居住语境 → 判伪。"""
    value = original[start:end]
    road_index = -1
    for index in range(2, len(value)):
        if value[index] in _ADDRESS_ROAD_SUFFIXES:
            road_index = index
            break
    if road_index < 0:
        # 行政区划后缀(省/市/区/县等)或门牌后缀(号楼/单元/室),不按裸路名判伪。
        return False
    tail = value[road_index + 1 :]
    if any(char.isdigit() for char in tail):
        return False  # 带门牌号,按真实地址处理
    context_window = original[max(0, start - 6) : start + road_index]
    if any(marker in context_window for marker in _ADDRESS_CONTEXT_MARKERS):
        return False
    return True


_PLACEHOLDER_RE = re.compile(r"\[[A-Z][A-Z_]+(?:_[0-9A-F]{1,8})?\]")
_CJK_CHAR_RE = re.compile(r"[\u4e00-\u9fa5]")


def _cjk_bigrams(text: str) -> set[str]:
    chars = _CJK_CHAR_RE.findall(text)
    return {chars[index] + chars[index + 1] for index in range(len(chars) - 1)}


def evidence_core_intact(original: str, redacted: str, *, min_ratio: float = 0.45) -> bool:
    """G4:脱敏后事实的核心对象是否仍然可理解。

    判定规则:

    - 非中文内容交由占位符密度判断,无法判定时保守认为可用(占位符本身
      可追溯);
    - 短事实(≤8 个汉字)只要出现占位符就视为核心对象丢失;
    - 长事实用 CJK bigram 保留率衡量,低于阈值说明实体被整体吃掉。
    """
    original_text = str(original or "")
    redacted_text = str(redacted or "")
    original_clean = _PLACEHOLDER_RE.sub("", original_text)
    han_chars = _CJK_CHAR_RE.findall(original_clean)
    if not han_chars:
        return True
    if len(han_chars) <= 8:
        return not _PLACEHOLDER_RE.search(redacted_text)
    original_grams = _cjk_bigrams(original_clean)
    if not original_grams:
        return True
    redacted_grams = _cjk_bigrams(_PLACEHOLDER_RE.sub("", redacted_text))
    kept_ratio = len(original_grams & redacted_grams) / len(original_grams)
    return kept_ratio >= min_ratio


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

        # G4:受保护作品译名先用等长 PUA 哨兵替换(保持偏移不变),
        # 让地址模式无法跨越它们匹配;脱敏完成后原样恢复。
        protected_restore: list[tuple[str, str]] = []
        scan_text = original
        for index, fragment in enumerate(PROTECTED_NAME_FRAGMENTS):
            if fragment and fragment in scan_text:
                sentinel = chr(0xF0000 + index) * len(fragment)
                protected_restore.append((sentinel, fragment))
                scan_text = scan_text.replace(fragment, sentinel)

        redacted = scan_text

        matches: list[tuple[int, int, str, str]] = []
        for entity_type, pattern in self.PATTERNS:
            for match in pattern.finditer(scan_text):
                value = match.group(0)
                if entity_type == "bank_card":
                    digits = re.sub(r"\D", "", value)
                    if len(digits) < 16:
                        continue
                if entity_type == "address" and _address_match_is_false_positive(
                    scan_text, match.start(), match.end()
                ):
                    continue
                matches.append((match.start(), match.end(), entity_type, value))

        # 重叠消解：多个模式的匹配区间可能交叠（如地址模式的尾段会吞掉紧跟其后的电话号码），
        # 直接按原始偏移逐个切片替换会把已写入的占位符再次切开，产出损坏文本。
        # 这里按起点升序（同起点取更长区间）贪心保留互不重叠的匹配，丢弃与已保留区间
        # 重叠的后续匹配，保证任意字符至多被一个占位符替换。
        resolved: list[tuple[int, int, str, str]] = []
        kept_end = -1
        for start, end, entity_type, value in sorted(
            matches,
            key=lambda item: (item[0], -(item[1] - item[0])),
        ):
            if start < kept_end:
                continue
            resolved.append((start, end, entity_type, value))
            kept_end = end

        # Replace from the end so offsets remain stable.
        for start, end, entity_type, value in sorted(resolved, key=lambda item: item[0], reverse=True):
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

        # G4:恢复被哨兵保护的作品译名(它们不应被地址规则吃掉)。
        for sentinel, fragment in protected_restore:
            redacted = redacted.replace(sentinel, fragment)

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
