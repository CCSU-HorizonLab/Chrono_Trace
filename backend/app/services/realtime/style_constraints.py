"""Utilities for deriving quantitative style constraints for realtime suggestions."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


DEFAULT_MAX_SPEECH_LENGTH = 15


@dataclass
class StyleConstraints:
    emoji_density: float = 0.0
    avg_msg_length: float = 0.0
    max_speech_length: int = DEFAULT_MAX_SPEECH_LENGTH
    communication_type: str = "balanced"
    emotional_style: str = "neutral"
    nickname_usage: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _safe_get(source: Any, *keys: str) -> Any:
    current = source
    for key in keys:
        if current is None:
            return None
        if isinstance(current, dict):
            current = current.get(key)
        else:
            current = getattr(current, key, None)
    return current


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _resolve_emotional_style(affinity_result: Any) -> str:
    resonance_score = _safe_float(
        _safe_get(affinity_result, "emotional_resonance", "score")
    )
    attitude_score = _safe_float(
        _safe_get(affinity_result, "attitude_tendency", "score")
    )

    style_score = 0.0
    if attitude_score > 0 and resonance_score > 0:
        style_score = (attitude_score * 0.65) + (resonance_score * 0.35)
    elif attitude_score > 0:
        style_score = attitude_score
    else:
        style_score = resonance_score

    if style_score <= 0:
        return "neutral"

    if style_score < 40:
        return "cold"
    if style_score > 70:
        return "warm"
    return "neutral"


def compute_style_constraints(
    self_profile_features: dict[str, Any] | None = None,
    preprocessed_stats: Any = None,
    affinity_result: Any = None,
) -> StyleConstraints:
    """Derive prompt/runtime style constraints from cached historical analysis."""
    stats_total = max(
        _safe_int(_safe_get(preprocessed_stats, "total_message_count")),
        0,
    )
    emoji_count = max(
        _safe_int(_safe_get(preprocessed_stats, "emoji_message_count")),
        0,
    )
    emoji_density = (emoji_count / stats_total) if stats_total else 0.0

    avg_msg_length = _safe_float(
        _safe_get(self_profile_features, "user_msg_style", "avg_chars_per_msg")
    )
    if avg_msg_length <= 0:
        avg_msg_length = _safe_float(_safe_get(preprocessed_stats, "average_message_length"))

    if avg_msg_length > 0:
        max_speech_length = min(48, max(1, int(avg_msg_length * 2.5)))
    else:
        max_speech_length = DEFAULT_MAX_SPEECH_LENGTH

    sender_initiated = max(
        _safe_int(_safe_get(preprocessed_stats, "sender_initiated_count")),
        0,
    )
    contact_initiated = max(
        _safe_int(_safe_get(preprocessed_stats, "contact_initiated_count")),
        0,
    )
    initiated_total = sender_initiated + contact_initiated
    communication_type = "balanced"
    if initiated_total:
        initiative_rate = sender_initiated / initiated_total
        if initiative_rate > 0.6:
            communication_type = "proactive"
        elif initiative_rate < 0.4:
            communication_type = "reactive"

    emotional_style = _resolve_emotional_style(affinity_result)

    total_nickname_count = _safe_int(_safe_get(preprocessed_stats, "nickname_message_count"))
    sender_nickname_count = _safe_int(
        _safe_get(preprocessed_stats, "sender_nickname_message_count")
    )
    contact_nickname_count = _safe_int(
        _safe_get(preprocessed_stats, "contact_nickname_message_count")
    )
    if (
        total_nickname_count > 0
        and sender_nickname_count == 0
        and contact_nickname_count == 0
    ):
        nickname_usage = True
    else:
        nickname_usage = sender_nickname_count > 0

    return StyleConstraints(
        emoji_density=round(emoji_density, 4),
        avg_msg_length=round(avg_msg_length, 1) if avg_msg_length > 0 else 0.0,
        max_speech_length=max_speech_length,
        communication_type=communication_type,
        emotional_style=emotional_style,
        nickname_usage=nickname_usage,
    )


def load_cached_style_inputs(conversation_id: int | None):
    """Read cached preprocessing / affinity results without triggering recomputation."""
    if not conversation_id:
        return None, None

    try:
        from ..analysis import AffinityAnalysisService, PreprocessingOrchestrator

        preprocessed_stats = PreprocessingOrchestrator()._load_cached_statistics(conversation_id)
        affinity_result = AffinityAnalysisService().get_scores(conversation_id)
        return preprocessed_stats, affinity_result
    except Exception:
        return None, None
