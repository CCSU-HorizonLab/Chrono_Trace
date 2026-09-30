"""Utilities for building historical suggestion context."""

from __future__ import annotations

from typing import Any, Callable

from .style_constraints import compute_style_constraints, load_cached_style_inputs


def compute_chart_stats(messages: list[dict] | None) -> dict:
    """Build lightweight chat statistics for prompt conditioning.

    G3:配对修复——回复率要求"我方消息的紧邻下一条是对方",回复间隔
    取"我方消息 → 对方回复"的时延;统计只看人工聊天,转账/系统通知
    (即使被上游误标成 friend)不参与,避免通知污染派生关系结论。
    """
    from .recent_window import compute_pairing_stats

    return compute_pairing_stats(messages or [])


def build_historical_context(
    contact_profile: dict | None = None,
    emotion_summary: dict | None = None,
    recent_messages: list[dict] | None = None,
    self_profile_features: dict | None = None,
    preprocessed_stats=None,
    affinity_result=None,
) -> dict:
    """Build a compact optional historical context payload."""
    historical_context: dict = {}
    if contact_profile:
        historical_context["profile"] = contact_profile
    if emotion_summary:
        historical_context["emotion_summary"] = emotion_summary

    chart_stats = compute_chart_stats(recent_messages)
    if any(value not in (None, "N/A", 0) for value in chart_stats.values()):
        historical_context["chart_stats"] = chart_stats

    if any(
        value is not None
        for value in (self_profile_features, preprocessed_stats, affinity_result)
    ):
        style_constraints = compute_style_constraints(
            self_profile_features=self_profile_features,
            preprocessed_stats=preprocessed_stats,
            affinity_result=affinity_result,
        )
        historical_context["style_constraints"] = style_constraints.to_dict()

    return historical_context


def augment_context_with_historical_data(
    ctx: dict[str, Any],
    *,
    self_profile_cache: dict[str, Any] | None = None,
    load_style_inputs: Callable[[int | None], tuple[Any, Any] | tuple[None, None]] | None = None,
    conversation_id: int | None = None,
) -> dict[str, Any]:
    """Merge cached historical/style inputs into an existing runtime context.

    审核返工 2:``conversation_id`` 显式传入时优先(来自统一范围解析),
    不再依赖自我画像缓存里带的会话号——缓存缺失也能拿到好感/量化风格。
    """
    resolved_conversation_id = conversation_id
    self_profile_features = None
    if self_profile_cache:
        if resolved_conversation_id is None:
            resolved_conversation_id = self_profile_cache.get("conversation_id")
        self_profile_features = self_profile_cache.get("features_snapshot") or None

    style_loader = load_style_inputs or load_cached_style_inputs
    preprocessed_stats, affinity_result = style_loader(resolved_conversation_id)

    historical_context = ctx.get("historical_context", {})
    if not isinstance(historical_context, dict):
        historical_context = {}

    auto_historical = build_historical_context(
        contact_profile=ctx.get("contact_profile"),
        emotion_summary=ctx.get("emotion_summary"),
        recent_messages=ctx.get("recent_messages"),
        self_profile_features=self_profile_features,
        preprocessed_stats=preprocessed_stats,
        affinity_result=affinity_result,
    )
    for key, value in auto_historical.items():
        historical_context.setdefault(key, value)

    if historical_context:
        ctx["historical_context"] = historical_context
    if self_profile_features is not None:
        ctx.setdefault("self_profile_features", self_profile_features)
    if preprocessed_stats is not None:
        ctx.setdefault("preprocessed_stats", preprocessed_stats)
    if affinity_result is not None:
        ctx.setdefault("affinity_result", affinity_result)

    return historical_context
