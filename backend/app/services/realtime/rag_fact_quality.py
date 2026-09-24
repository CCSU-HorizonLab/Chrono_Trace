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

_GENERIC_TURNS = {
    "嗯",
    "嗯嗯",
    "哦",
    "好的",
    "好好好",
    "可以",
    "行吧",
    "看一下吧",
    "你看一下",
    "怎么说",
    "什么",
    "哪个",
    "666",
    "6666",
}

# 微信系统/通知消息特征：不是用户表达的事实，不进记忆
SYSTEM_MESSAGE_MARKERS = (
    "我通过了你的朋友验证请求",
    "你现在可以开始聊天",
    "撤回了一条消息",
    "拍了拍",
    "以下为新消息",
    "收到了红包",
    "领取了红包",
    "发出了红包",
    "转账给你",
    "你已收款",
    "以上是打招呼的内容",
)


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
        if ch == "\ufffd" or ord(ch) < 0x20 or (0x80 <= ord(ch) <= 0xFF)
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
    if compact in _GENERIC_TURNS:
        return "generic_turn"
    if any(marker in compact for marker in SYSTEM_MESSAGE_MARKERS):
        return "system_message"
    if looks_corrupted(compact):
        return "corrupted_text"
    if re.fullmatch(r"[\W_\d]+", compact, flags=re.UNICODE):
        return "nonsemantic_turn"
    # 疑问轮：问句助词结尾，或以疑问指代开头且较短（长句多为陈述，如"她在深圳做后端"）
    if compact.endswith(("吗", "么", "呢", "？", "?")):
        return "question_turn"
    if len(compact) < 15 and re.match(r"^(你|她|他|哪|什么|怎么|是不是|啥)", compact):
        return "question_turn"
    if any(term in compact for term in SENSITIVE_TERMS):
        return "sensitive_quarantine"
    if re.fullmatch(r"(?:好的|好滴|好|嗯|哦|噢|行|可以|哈哈|嘿嘿|666|啊|呀|吧|滴)+", compact):
        return "acknowledgement"

    if not require_kind_signal:
        return None

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
    return None


def is_usable_shadow_fact(kind: str, content: Any, *, context: str = "") -> bool:
    return fact_quality_reason(kind, content, context=context) is None
