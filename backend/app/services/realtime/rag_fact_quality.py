"""Quality gates for durable contact-memory facts.

Semantic prototype matching is useful for finding candidates, but it is not a
fact extractor by itself.  This module keeps short-lived conversational turns
out of the active fact table and requires a lexical signal that agrees with the
predicted memory kind.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .rag_relevance_gate import RagRelevanceGate

# 敏感查询阻断清单（rag_relevance_gate）＋ 事实入库前的补充强敏词；
# 前者服务于"查询端阻断"，密码/密钥/宽泛住址只影响入库质量层。
SENSITIVE_TERMS = tuple(dict.fromkeys(
    RagRelevanceGate.SENSITIVE_LOOKUP_TERMS + ("密码", "密钥", "住址")
))


def _load_quality_patterns() -> dict[str, tuple[str, ...]]:
    """Load quality-gate word lists from the external patterns config.

    P2-1 纪律：词表是数据不是代码——代指残句特征、微信系统消息特征
    等语言词表外置于 fact_quality_patterns.json，扩充改配置不动代码。
    配置缺失时安全降级为空表（不拦截），绝不让质量门崩溃。
    """
    path = Path(__file__).with_name("fact_quality_patterns.json")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return {
            key: tuple(str(term) for term in terms if str(term).strip())
            for key, terms in payload.items()
            if isinstance(terms, list) and not key.startswith("_")
        }
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        return {}


_QUALITY_PATTERNS = _load_quality_patterns()
# 微信系统/通知消息特征：不是用户表达的事实，不进记忆
SYSTEM_MESSAGE_MARKERS = _QUALITY_PATTERNS.get("system_message_markers", ())
VAGUE_REFERENCE_TERMS = _QUALITY_PATTERNS.get("vague_reference_terms", ())
GENERIC_TURNS = frozenset(_QUALITY_PATTERNS.get("generic_turns", ()))
VAGUE_REFERENCE_TERMS = _QUALITY_PATTERNS.get("vague_reference_terms", ())
# 一次性金钱往来细节（设计蓝图排除项）：短句命中即拦截，词表外置
TRANSACTION_DETAIL_TERMS = _QUALITY_PATTERNS.get("transaction_detail_terms", ())
# 弱化态度残句（"没那么想要"）：仅当整句极短（无宾语）时拦截；
# 与 vague_reference_terms 分键——后者出现即拦，前者要短于宾语长度
WEAK_ATTITUDE_TERMS = _QUALITY_PATTERNS.get("weak_attitude_terms", ())


def _load_kind_signals() -> dict[str, tuple[str, ...]]:
    """Load kind signal words from the external fact_kind_hints config.

    词表外置是 v4 P2-1 的既定决策（通用检索/质量代码不内嵌具体业务语料）；
    扩充信号词改 json，不动代码。
    """
    path = Path(__file__).with_name("fact_kind_hints.json")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return {
            str(kind): tuple(str(term) for term in terms if str(term).strip())
            for kind, terms in payload.items()
            if isinstance(terms, list)
        }
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        return {}


_KIND_SIGNALS = _load_kind_signals()

def looks_corrupted(text: str) -> bool:
    """Detect garbled/binary message bodies.

    替换符、控制字符或高位怪字符（中文语境几乎不会出现 0x80-0xFF 拉丁
    扩展区密集内容）占比超过 25% 视为损坏——作为事实或证据都会让
    "来源原文拼不上"。
    """
    compact = str(text or "")
    if not compact:
        return False
    bad = sum(
        1
        for ch in compact
        if ch == "�" or ord(ch) < 0x20 or (0x80 <= ord(ch) <= 0xFF)
    )
    return bad / len(compact) > 0.25


def fact_text_parts(content: Any) -> tuple[str, str]:
    """Return the focal message and the optional rendered context."""
    text = str(content or "").strip()
    text = re.sub(r"^(?:我|对方)提到：", "", text)
    if "\n相关上下文：" in text:
        primary, context = text.split("\n相关上下文：", 1)
        return re.sub(r"\s+", " ", primary).strip(), re.sub(r"\s+", " ", context).strip()
    return re.sub(r"\s+", " ", text).strip(), ""


def _compact(text: str) -> str:
    return re.sub(r"\s+", "", str(text or ""))


def _has_object(text: str, signals: tuple[str, ...]) -> bool:
    compact = _compact(text)
    remainder = compact
    for signal in sorted(signals, key=len, reverse=True):
        remainder = remainder.replace(signal, "")
    remainder = re.sub(r"[，。！？、：；,.!?\[\]（）()~～#@\d]+", "", remainder)
    for filler in ("随便", "一下子", "一下", "了", "着", "吧", "呢", "啊", "呀"):
        remainder = remainder.replace(filler, "")
    return len(remainder) >= 2


def fact_quality_reason(
    kind: str,
    content: Any,
    *,
    context: str = "",
    require_kind_signal: bool = True,
) -> str | None:
    """Return ``None`` for an active-quality fact, otherwise a reason code.

    require_kind_signal=False 用于 LLM 结构化抽取：kind 由模型判定，
    无需词表佐证；但长度/通用应答/疑问轮/敏感词等基础项仍然生效。
    """
    primary, rendered_context = fact_text_parts(content)
    context_text = f"{rendered_context} {context}".strip()
    compact = _compact(primary)
    if len(compact) < 4:
        return "too_short"
    if compact in GENERIC_TURNS:
        return "generic_turn"
    if any(marker in compact for marker in SYSTEM_MESSAGE_MARKERS):
        return "system_message"
    if looks_corrupted(compact):
        return "corrupted_text"
    # 代指残句：短句命中代指特征词（词表见 fact_quality_patterns.json）
    # 且无具体对象——"就买一下下嘛"类断上下文垃圾事实
    if VAGUE_REFERENCE_TERMS and len(compact) <= 20 and any(
        term in compact for term in VAGUE_REFERENCE_TERMS
    ):
        return "vague_fragment"
    # 一次性金钱往来细节（"早餐钱""转你20"）：设计蓝图排除项，非长期记忆
    if TRANSACTION_DETAIL_TERMS and len(compact) <= 24 and any(
        term in compact for term in TRANSACTION_DETAIL_TERMS
    ):
        return "transaction_detail"
    if re.fullmatch(r"[\W_\d]+", compact, flags=re.UNICODE):
        return "nonsemantic_turn"
    # 敏感词优先于疑问判定："对方手机号是多少"是敏感查询而非普通问句
    if any(term in compact for term in SENSITIVE_TERMS):
        return "sensitive_quarantine"
    # 弱化态度残句：整句极短（<=8 字）且命中弱化词——"没那么想要"类
    # 无宾语残句；带宾语（"没那么想要那款键盘了"）放行给后续检查
    if WEAK_ATTITUDE_TERMS and len(compact) <= 8 and any(
        term in compact for term in WEAK_ATTITUDE_TERMS
    ):
        return "vague_fragment"
    # 疑问轮：问句助词结尾，或以疑问指代开头且较短（长句多为陈述，如"她在深圳做后端"）
    # "多少/几块"结尾是询价（"早餐多少"），同为问句形态
    if compact.endswith(("吗", "么", "呢", "？", "?", "多少", "几块")):
        return "question_turn"
    if len(compact) < 15 and re.match(r"^(你|她|他|哪|什么|怎么|是不是|啥)", compact):
        return "question_turn"
    if re.fullmatch(r"(?:好的|好滴|好|嗯|哦|噢|行|可以|哈哈|嘿嘿|666|啊|呀|吧|滴)+", compact):
        return "acknowledgement"

    if not require_kind_signal:
        return None

    # 原型路径长度门槛（P2 收紧）：真实库 93 条 active 原型事实中 74 条
    # （80%）焦点 <12 字且无一值得长期保留（"不想你嘛""答应个屁"）。
    # LLM 路径不受限（宽松模式已在上方 return）——模型负责自包含判断。
    # 放在精确分类规则之后作兜底：已有词表命中的仍按原 reason 归因。
    if len(compact) < 12:
        return "prototype_too_short"

    if str(kind or "") == "marker_fallback":
        signals = tuple(dict.fromkeys(signal for values in _KIND_SIGNALS.values() for signal in values))
    else:
        signals = _KIND_SIGNALS.get(str(kind or ""), ())
    if not signals:
        return "unknown_kind"
    primary_hits = tuple(signal for signal in signals if signal in primary)
    context_hits = tuple(signal for signal in signals if signal in context_text)
    if not primary_hits and not context_hits:
        return "kind_signal_missing"
    # A neighboring turn is evidence, not a fact.  The focal message itself
    # must carry the kind signal; this prevents "看一下吧" or "不知道" from
    # inheriting a topic from an adjacent message.
    if not primary_hits:
        return "context_only_weak"
    # A generic activity verb is not a hobby memory without an object.
    if kind == "hobby_or_game":
        object_text = _compact(primary)
        for signal in sorted(signals, key=len, reverse=True):
            object_text = object_text.replace(signal, "")
        for filler in ("随便", "一下子", "一下", "确实", "挺好", "还挺", "了", "着", "吧", "呢", "啊", "呀"):
            object_text = object_text.replace(filler, "")
        if len(object_text) < 4:
            return "hobby_object_missing"
    if kind in {"preference_like", "preference_dislike", "food_or_place"} and not _has_object(primary, signals):
        return "object_missing"
    # 购买类"……的"结尾是代指（"直接买80的""想买便宜点的"）——买的
    # 具体物品已丢失，无法自包含
    if kind == "purchase_or_price" and compact.endswith("的"):
        return "object_missing"
    return None


def is_usable_shadow_fact(kind: str, content: Any, *, context: str = "") -> bool:
    return fact_quality_reason(kind, content, context=context) is None
