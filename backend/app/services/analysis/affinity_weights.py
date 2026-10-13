"""好感度四维 + LLM 权重归一引擎。

点数制：每维一个 declared 权重（不要求和为 1），启用判定决定该维是否
在场；总分阶段把在场维度的 declared 归一为有效权重（和恰为 1）。
缺席维度（未配关键词的偏好维、未配模型/调用失败的 LLM 维）自动从
分母剔除，其余维度权重自动放大。

默认权重 0.40/0.35/0.15 保持互动投入与情感共鸣 8:7 比例延续旧
「聊天积极度/情感共振率」的相对关系；亲近信号、喜好兼容度与 LLM
关系评估为次级维度。
"""

from __future__ import annotations

import logging
from typing import Any, Dict

from .affinity_config import AffinityConfig

logger = logging.getLogger(__name__)

# 维度 key 序（与 AffinityAnalysisResult 的维度字段一一对应）
DIMENSION_ORDER = (
    "interaction_investment",
    "emotional_resonance",
    "closeness_signals",
    "preference_compatibility",
    "llm_relationship",
)

# 各维字段名（AffinityAnalysisResult / DimensionScore 装载处）
DIMENSION_FIELDS = {
    "interaction_investment": "interaction_investment",
    "emotional_resonance": "emotional_resonance",
    "closeness_signals": "closeness_signals",
    "preference_compatibility": "preference_compatibility",
    "llm_relationship": "llm_relationship",
}

# 默认 declared 权重（点数制）
DEFAULT_WEIGHTS: Dict[str, float] = {
    "interaction_investment": 0.40,
    "emotional_resonance": 0.35,
    "closeness_signals": 0.15,
    "preference_compatibility": 0.10,
    "llm_relationship": 0.08,
}

# AffinityConfig 上的权重字段名 → 维度 key
_CONFIG_WEIGHT_FIELDS = {
    "weight_interaction_investment": "interaction_investment",
    "weight_emotional_resonance": "emotional_resonance",
    "weight_closeness_signals": "closeness_signals",
    "weight_preference_compatibility": "preference_compatibility",
    "weight_llm_relationship": "llm_relationship",
}


def resolve_dimension_plan(
    config: AffinityConfig, llm_available: bool
) -> Dict[str, Dict[str, Any]]:
    """解析各维权重计划：config 覆盖默认值，附启用判定。

    Args:
        config: 会话配置（权重字段为点数制，非法值回退默认）
        llm_available: LLM 评估是否可用（激活模型存在；调用失败在
            维度计算期才揭晓，缺席处理见 apply_weight_normalization）

    Returns:
        {维度 key: {"declared": float, "enabled": bool}}
    """
    plan: Dict[str, Dict[str, Any]] = {}
    for field_name, dim_key in _CONFIG_WEIGHT_FIELDS.items():
        declared = DEFAULT_WEIGHTS[dim_key]
        try:
            override = float(getattr(config, field_name, declared))
            if 0.0 <= override <= 1.0:
                declared = override
        except (TypeError, ValueError):
            pass
        plan[dim_key] = {"declared": declared, "enabled": True}

    # 偏好维：未配置关键词则缺席（无从匹配）
    if not (getattr(config, "preference_keywords", None) or []):
        plan["preference_compatibility"]["enabled"] = False

    # LLM 维：开关关闭或无激活模型则缺席
    llm_enabled = bool(getattr(config, "llm_relationship_enabled", True))
    if not llm_enabled or not llm_available:
        plan["llm_relationship"]["enabled"] = False

    return plan


def apply_weight_normalization(result: Any) -> Dict[str, float]:
    """对 result 上在场的 DimensionScore 归一权重并覆写 weighted_score。

    在场 = 字段存在且非 None 且 declared > 0。LLM 维缺席（None 或
    declared=0）自动从分母剔除。Σ=0 时回退三本地维默认（防止极端配置
    让总分失去意义）。

    Returns:
        {维度 key: 有效权重}（和为 1；仅在场维度）
    """
    entries: Dict[str, Any] = {}
    for dim_key in DIMENSION_ORDER:
        score = getattr(result, DIMENSION_FIELDS[dim_key], None)
        if score is None:
            continue
        declared = float(getattr(score, "weight", 0.0) or 0.0)
        if declared <= 0:
            continue
        entries[dim_key] = score

    if not entries:
        logger.warning("[权重引擎] 无任何在场维度，回退本地三维默认权重")
        fallback = {
            "interaction_investment": DEFAULT_WEIGHTS["interaction_investment"],
            "emotional_resonance": DEFAULT_WEIGHTS["emotional_resonance"],
            "closeness_signals": DEFAULT_WEIGHTS["closeness_signals"],
        }
        total = sum(fallback.values())
        for dim_key, declared in fallback.items():
            score = getattr(result, DIMENSION_FIELDS[dim_key], None)
            if score is not None:
                score.weight = declared / total
                score.weighted_score = score.score * score.weight
        return {k: d / total for k, d in fallback.items()}

    total = sum(float(getattr(score, "weight", 0.0)) for score in entries.values())
    effective: Dict[str, float] = {}
    for dim_key, score in entries.items():
        score.weight = float(getattr(score, "weight", 0.0)) / total
        score.weighted_score = score.score * score.weight
        effective[dim_key] = score.weight
    return effective
