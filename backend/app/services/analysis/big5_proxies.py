"""大五人格印象——基础层（纯统计代理，无 LLM 永远可用）。

设计（docs/analysis/time-depth.md 记录口径）：
- 五维均为 0-100 连续分数，不贴 MBTI 式标签；这是「语言风格印象」，
  不是心理测评。
- 每维由 2-4 个行为代理子指标加权合成，权重为点数制；子指标缺席
  （如情感缓存缺失时 intensity_variance 为 None）按在场指标重归一，
  与 affinity_weights 惯例一致。
- 子指标原始值 → 0-100：锚点表分段线性插值（锚点值单调递增），
  超出锚点范围向两端截断。
- 本模块纯函数、不落库、不读 DB；指标采集在
  personality_impression_service._collect_raw_indicators。
"""

from typing import Any, Dict, List, Optional, Tuple

# 维度键（学界通用缩写）
DIMENSIONS = ("extraversion", "conscientiousness", "neuroticism", "agreeableness", "openness")

DIMENSION_LABELS = {
    "extraversion": "外向性",
    "conscientiousness": "尽责性",
    "neuroticism": "神经质",
    "agreeableness": "宜人性",
    "openness": "开放性",
}

# 锚点表：[(原始值, 映射分)]，分段线性；列表内映射分单调不减
_DIMENSION_SPECS: Dict[str, Dict[str, Any]] = {
    "extraversion": {
        "weights": {"daily_avg": 40, "icebreak_ratio": 30, "emoji_exclaim_density": 30},
        "anchors": {
            "daily_avg": [(0, 10), (5, 40), (20, 70), (60, 100)],
            "icebreak_ratio": [(0, 10), (0.3, 40), (0.6, 72), (1.0, 100)],
            "emoji_exclaim_density": [(0, 15), (0.05, 45), (0.15, 75), (0.3, 100)],
        },
    },
    "conscientiousness": {
        "weights": {"unanswered_rate": 50, "daily_cv": 30, "topic_continuation": 20},
        "anchors": {
            # 未回应事件率与日量波动为反向指标：值越高分越低（锚点倒序书写）
            "unanswered_rate": [(0, 90), (0.1, 65), (0.3, 35), (0.6, 10)],
            "daily_cv": [(0, 90), (0.5, 70), (1.0, 45), (2.0, 15)],
            "topic_continuation": [(0, 20), (0.3, 50), (0.6, 75), (0.9, 100)],
        },
    },
    "neuroticism": {
        "weights": {"intensity_variance": 40, "negative_ratio": 30, "late_night_ratio": 15, "revoke_rate": 15},
        "anchors": {
            "intensity_variance": [(0, 15), (0.05, 45), (0.12, 70), (0.25, 100)],
            "negative_ratio": [(0, 10), (0.1, 40), (0.25, 70), (0.5, 100)],
            "late_night_ratio": [(0, 20), (0.05, 50), (0.15, 80), (0.3, 100)],
            "revoke_rate": [(0, 20), (0.01, 50), (0.05, 80), (0.1, 100)],
        },
    },
    "agreeableness": {
        "weights": {"pos_neg_ratio": 40, "positive_response_rate": 30, "empathy_density": 30},
        "anchors": {
            "pos_neg_ratio": [(0, 10), (0.6, 45), (0.8, 70), (0.95, 100)],
            "positive_response_rate": [(0, 15), (0.3, 45), (0.6, 72), (0.9, 100)],
            "empathy_density": [(0, 15), (0.02, 45), (0.08, 75), (0.2, 100)],
        },
    },
    "openness": {
        "weights": {"ttr": 40, "topic_entropy": 30, "share_density": 30},
        "anchors": {
            "ttr": [(0.2, 15), (0.4, 45), (0.55, 70), (0.75, 100)],
            "topic_entropy": [(0.3, 20), (0.55, 50), (0.75, 75), (0.9, 100)],
            "share_density": [(0, 15), (0.05, 45), (0.15, 75), (0.3, 100)],
        },
    },
}


def anchor_score(value: float, anchors: List[Tuple[float, float]]) -> float:
    """锚点表分段线性插值；超出范围向两端截断到 [首锚点分, 末锚点分]。"""
    if value <= anchors[0][0]:
        return float(anchors[0][1])
    if value >= anchors[-1][0]:
        return float(anchors[-1][1])
    for (x0, y0), (x1, y1) in zip(anchors, anchors[1:]):
        if x0 <= value <= x1:
            if x1 == x0:
                return float(y1)
            ratio = (value - x0) / (x1 - x0)
            return float(y0 + ratio * (y1 - y0))
    return float(anchors[-1][1])


def compute_dimension(dimension: str, indicators: Dict[str, Optional[float]]) -> Optional[Dict[str, Any]]:
    """单维合成：缺席指标按在场权重重归一；全缺席返回 None。"""
    spec = _DIMENSION_SPECS[dimension]
    total_points = 0
    weighted = 0.0
    parts: Dict[str, Dict[str, Any]] = {}

    for name, points in spec["weights"].items():
        value = indicators.get(name)
        if value is None or not (isinstance(value, (int, float))):
            parts[name] = {"value": None, "points": points, "used": False}
            continue
        score = anchor_score(float(value), spec["anchors"][name])
        total_points += points
        weighted += score * points
        parts[name] = {
            "value": round(float(value), 4),
            "points": points,
            "used": True,
            "mapped": round(score, 1),
        }

    if total_points == 0:
        return None
    return {
        "score": round(weighted / total_points, 1),
        "indicators": parts,
    }


def compute_big5_base(
    raw_indicators: Dict[str, Optional[float]],
) -> Dict[str, Any]:
    """五维基础层合成。输入为单侧原始子指标 dict。"""
    result: Dict[str, Any] = {}
    for dim in DIMENSIONS:
        computed = compute_dimension(dim, raw_indicators)
        if computed is None:
            result[dim] = {"score": None, "label": DIMENSION_LABELS[dim], "indicators": {}}
        else:
            result[dim] = {"label": DIMENSION_LABELS[dim], **computed}
    return result
