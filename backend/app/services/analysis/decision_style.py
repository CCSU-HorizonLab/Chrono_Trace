"""决策风格推断（GDMS 锚定）——通道 A 映射 + 通道 B 行为信号（纯函数）。

设计（paper 规划 §3.1/§3.4，GDMS = Scott & Bruce 1995 五维）：
- 通道 A（风格层）：大五 0-100 分 → 参照先验 z 标准化 → GDMS 五维
  线性映射。系数第一版取同行评审数值汇合中值（方向以 Alacreu 2019/
  Dewberry/Bavolar 合成为主，El Othman 2020 的 N 方向反转按次级来源
  弃用，O 列跨样本不稳定一律减半）——**实现时以 Alacreu 表 4/
  El Othman 表格原文复核**，此处先落地工程形态供产品先用。
- 通道 B（行为层）：六个有据决策语言信号（词表密度，各自开关）+
  记忆链行为聚合（rag_facts 的 plan/promise/event：承诺兑现率、
  改主意率），对通道 A 做有界修正——与大五 LLM 增强层 ±15 同构但
  更保守（±10）。两个探索性特征（撤回率/承诺跟进）只输出不进先验。
- 参照群体先验为占位常量（均值 50/SD 15）：大五层无 z 分输出，
  待 N≥100 捐赠数据后替换为实测分布。样本不足的维度回退先验均值
  并降置信（五维可辨识度不均：依赖/回避信号密集，理性/自发需要
  足够决策话题样本）。
- 本模块纯函数、不落库、不读 DB；信号采集在 service 层，行为聚合
  由调用方查 rag_store 后传入。
- 推断目标如实口径：「从行为痕迹估计的决策风格倾向」，非心理测评。
"""

from typing import Any, Dict, List, Optional, Tuple

# GDMS 五维键（Scott & Bruce 1995）
GDMS_DIMENSIONS = ("rational", "intuitive", "dependent", "avoidant", "spontaneous")

GDMS_DIMENSION_LABELS = {
    "rational": "理性",
    "intuitive": "直觉",
    "dependent": "依赖",
    "avoidant": "回避",
    "spontaneous": "自发",
}

# 大五维键与 big5_proxies.DIMENSIONS 同源（延迟导入避免环，见 z_standardize）
BIG5_KEYS = ("extraversion", "conscientiousness", "neuroticism", "agreeableness", "openness")

# 通道 A 参照群体先验：(均值, SD)。占位常量——待捐赠数据实测分布替换
REF_POPULATION: Dict[str, Tuple[float, float]] = {
    "extraversion": (50.0, 15.0),
    "conscientiousness": (50.0, 15.0),
    "neuroticism": (50.0, 15.0),
    "agreeableness": (50.0, 15.0),
    "openness": (50.0, 15.0),
}

# 通道 A 线性映射先验（第一版，来源见模块 docstring）
# 键序 = BIG5_KEYS（E/C/N/A/O），单位：GDMS 分 / 大五 z 分
_MAPPING_PRIORS: Dict[str, Dict[str, float]] = {
    "rational": {
        "conscientiousness": 0.26, "agreeableness": 0.17, "neuroticism": -0.15,
        "extraversion": -0.07, "openness": 0.02,
    },
    "intuitive": {
        "extraversion": 0.17, "agreeableness": -0.12, "openness": 0.06,
        "neuroticism": 0.03, "conscientiousness": -0.02,
    },
    "dependent": {
        "agreeableness": 0.20, "neuroticism": 0.10, "openness": -0.08,
        "extraversion": -0.05, "conscientiousness": 0.05,
    },
    "avoidant": {
        "conscientiousness": -0.25, "neuroticism": 0.20, "extraversion": -0.15,
        "agreeableness": -0.12, "openness": -0.05,
    },
    "spontaneous": {
        "conscientiousness": -0.21, "agreeableness": -0.20, "neuroticism": 0.15,
        "extraversion": 0.10, "openness": -0.04,
    },
}

# 通道 B 六个有据信号（每个都有同行评审效标；权重=效标强度折算）
# density 口径：每千条文本消息的命中条数（service 层采集）
# anchors：密度 → 0-100 行为分（第一版工作锚点，待分布数据校准）
# enabled：默认开关——「各自开关」是产品要求，service 层可按会话覆盖
_SIGNAL_SPECS: Dict[str, Dict[str, Any]] = {
    "help_seeking": {
        "label": "求助问句", "target": "dependent", "direction": +1, "weight": 1.0,
        "patterns": ["你觉得呢", "你说呢", "帮我看看", "帮我参考", "怎么办", "怎么选",
                     "给点建议", "帮我拿主意", "帮我参谋", "你说哪个好"],
        "anchors": [(0, 35), (2, 50), (8, 72), (20, 100)],
        "enabled": True,
    },
    "deliberation": {
        "label": "决策列举", "target": "rational", "direction": +1, "weight": 1.0,
        "patterns": ["我查了", "对比了下", "研究了下", "查了一下", "列了一下",
                     "权衡", "利弊", "比较了", "调研了", "看了测评", "做了功课"],
        "anchors": [(0, 35), (2, 50), (8, 72), (20, 100)],
        "enabled": True,
    },
    "procrastination": {
        "label": "拖延话术", "target": "avoidant", "direction": +1, "weight": 0.8,
        "patterns": ["再看看", "以后再说", "懒得想", "再等等", "回头再说", "先放放",
                     "不急", "到时候再说", "想想再说", "再说吧"],
        "anchors": [(0, 35), (2, 50), (8, 72), (20, 100)],
        "enabled": True,
    },
    "impulsive": {
        "label": "冲动表态", "target": "spontaneous", "direction": +1, "weight": 0.8,
        "patterns": ["买了", "冲了", "管他呢", "先买了再说", "剁手", "忍不住",
                     "一冲动", "头脑一热", "先斩后奏", "不纠结了"],
        "anchors": [(0, 35), (2, 50), (8, 72), (20, 100)],
        "enabled": True,
    },
    "intuitive_talk": {
        "label": "直觉话术", "target": "intuitive", "direction": +1, "weight": 1.0,
        "patterns": ["我直觉觉得", "直觉告诉我", "凭感觉", "感觉上", "第六感",
                     "我说不上来但", "跟着感觉走", "心里有个声音"],
        "anchors": [(0, 35), (2, 50), (8, 72), (20, 100)],
        "enabled": True,
    },
    "late_night": {
        # chronotype↔冲动为间接证据（§3.4 信号⑥）：权重减半
        "label": "深夜活跃", "target": "spontaneous", "direction": +1, "weight": 0.5,
        "patterns": [],  # 密度由采集层按 0-5 点消息占比直供，不走词表
        "anchors": [(0, 35), (0.05, 50), (0.15, 72), (0.35, 100)],
        "enabled": True,
    },
}

# 探索性特征（§3.4 ⑦⑧）：产品可用、论文先验不用——只透传不进映射
EXPLORATORY_KEYS = ("revoke_rate", "promise_follow_through")

# 样本门槛：低于此文本消息量五维全部降置信（回退先验均值）
MIN_MESSAGES_FOR_SIGNALS = 200

# 通道 B 对通道 A 的每维有界修正幅度（与大五 LLM 增强 ±15 同构、更保守)
CHANNEL_B_MAX_ADJUST = 10.0

# 概率化表述五档
_SCORE_BANDS = [(30, "很低"), (42, "偏低"), (58, "中性"), (70, "偏高"), (101, "很高")]


def _band_label(score: float) -> str:
    for upper, label in _SCORE_BANDS:
        if score < upper:
            return label
    return "很高"


def z_standardize(big5_scores: Dict[str, Optional[float]]) -> Dict[str, Optional[float]]:
    """大五 0-100 分 → 参照先验 z 分。缺席维返回 None（映射段按在场维降置信）。"""
    out: Dict[str, Optional[float]] = {}
    for key in BIG5_KEYS:
        score = big5_scores.get(key)
        if score is None or not isinstance(score, (int, float)):
            out[key] = None
            continue
        mean, sd = REF_POPULATION[key]
        out[key] = (float(score) - mean) / sd
    return out


def _map_dimension(dim: str, z_scores: Dict[str, Optional[float]]) -> Optional[float]:
    """单维线性映射：z 分加权和 → 0-100（z 和 ∈ [-2.4, +2.4] 经验域映射到 50±40）。

    缺席大五维按零贡献处理（等效于该维取参照均值）；全缺席返回 None。
    """
    present = [k for k in BIG5_KEYS if z_scores.get(k) is not None]
    if not present:
        return None
    weighted = sum(
        _MAPPING_PRIORS[dim][key] * float(z_scores[key])  # type: ignore[arg-type]
        for key in present
    )
    # 线性映射到 50 中心：|系数和| 最大的 avoidant ≈ 0.77 → z=1 时偏移
    # 约 31 分；上限 2.4z 截断在经验域内（不外推到荒谬极值）
    score = 50.0 + weighted * 40.0
    return round(min(100.0, max(0.0, score)), 1)


def channel_a_scores(big5_scores: Dict[str, Optional[float]]) -> Dict[str, Any]:
    """通道 A：大五 → GDMS 五维（0-100 连续分 + 概率化表述 + 置信）。

    置信口径：五维大五全在场 = "normal"；缺席 1-2 维 = "reduced"；
    3 维以上缺席 = "low"（各维结果回退先验均值 50）。
    """
    z = z_standardize(big5_scores)
    missing = [k for k in BIG5_KEYS if z.get(k) is None]
    confidence = "normal" if not missing else ("reduced" if len(missing) <= 2 else "low")
    out: Dict[str, Any] = {"confidence": confidence, "missing_big5": missing}
    for dim in GDMS_DIMENSIONS:
        if confidence == "low":
            out[dim] = {"score": 50.0, "label": GDMS_DIMENSION_LABELS[dim],
                        "band": "中性", "fallback": True}
            continue
        score = _map_dimension(dim, z)
        if score is None:
            out[dim] = {"score": 50.0, "label": GDMS_DIMENSION_LABELS[dim],
                        "band": "中性", "fallback": True}
        else:
            out[dim] = {"score": score, "label": GDMS_DIMENSION_LABELS[dim],
                        "band": _band_label(score), "fallback": False}
    return out


def channel_b_scores(
    signal_densities: Dict[str, Optional[float]],
    *,
    message_count: int = 0,
) -> Dict[str, Any]:
    """通道 B：六信号密度 → 各信号行为分 + GDMS 维度聚合（含记忆链行为）。

    signal_densities 键 = _SIGNAL_SPECS（late_night 直供占比 0-1），
    值 = 密度（每千条）或 None（信号被开关关闭/采集缺席）。
    memory_behaviors 可由调用方另行并入（见 combine_channels）。
    样本不足（message_count < 门槛）整体降置信，行为分不参与修正。
    """
    insufficient = message_count < MIN_MESSAGES_FOR_SIGNALS
    signals: Dict[str, Any] = {}
    dim_accum: Dict[str, Dict[str, Any]] = {}
    for key, spec in _SIGNAL_SPECS.items():
        value = signal_densities.get(key)
        used = (
            spec["enabled"]
            and value is not None
            and isinstance(value, (int, float))
            and not insufficient
        )
        score = _anchor(float(value), spec["anchors"]) if used else None
        signals[key] = {
            "label": spec["label"], "target": spec["target"],
            "value": round(float(value), 4) if value is not None else None,
            "score": round(score, 1) if score is not None else None,
            "used": bool(used),
        }
        if not used or score is None:
            continue
        target = spec["target"]
        dim_accum.setdefault(target, {"weighted": 0.0, "points": 0.0})
        dim_accum[target]["weighted"] += score * float(spec["weight"])
        dim_accum[target]["points"] += float(spec["weight"])
    dims: Dict[str, Any] = {}
    for dim in GDMS_DIMENSIONS:
        acc = dim_accum.get(dim)
        if acc and acc["points"] > 0:
            dims[dim] = {"score": round(acc["weighted"] / acc["points"], 1)}
        else:
            dims[dim] = {"score": None}
    return {
        "confidence": "insufficient_sample" if insufficient else "normal",
        "message_count": message_count,
        "signals": signals,
        "dimensions": dims,
    }


def _anchor(value: float, anchors: List[Tuple[float, float]]) -> float:
    """与 big5_proxies.anchor_score 同构的分段线性插值（避免跨模块私有依赖）。"""
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


def combine_channels(
    a: Dict[str, Any],
    b: Optional[Dict[str, Any]],
    *,
    memory_behaviors: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """双通道合成：A 为基线，B（信号+记忆行为）做每维 ±10 有界修正。

    memory_behaviors（通道 B 记忆链部分，调用方从 rag_facts 聚合）：
    - promise_follow_through ∈ [0,1]：承诺兑现率 → dependent/A 修正
    - plan_supersede_rate ∈ [0,1]：改主意率 → spontaneous/A 修正
    空表/缺席优雅降级（当前 rag_facts 建设期常态）——不修正不改置信。
    """
    combined: Dict[str, Any] = {"confidence": a.get("confidence", "normal"), "dimensions": {}}
    b_dims = (b or {}).get("dimensions") or {}
    b_ok = (b or {}).get("confidence") == "normal"
    mem = memory_behaviors or {}
    for dim in GDMS_DIMENSIONS:
        a_entry = a.get(dim) or {}
        base = float(a_entry.get("score") if a_entry.get("score") is not None else 50.0)
        adjust = 0.0
        note: List[str] = []
        if b_ok:
            b_score = (b_dims.get(dim) or {}).get("score")
            if b_score is not None:
                # 行为分相对中性 50 的偏差，按 ±10 有界折算
                adjust += max(-CHANNEL_B_MAX_ADJUST, min(
                    CHANNEL_B_MAX_ADJUST, (float(b_score) - 50.0) * 0.25))
                note.append("信号修正")
        if dim == "dependent" and mem.get("promise_follow_through") is not None:
            # 高兑现率 → 决策后稳定执行，非依赖倾向：向下微修
            follow = float(mem["promise_follow_through"])
            adjust += (0.5 - follow) * 8.0
            note.append("承诺兑现")
        if dim == "spontaneous" and mem.get("plan_supersede_rate") is not None:
            supersede = float(mem["plan_supersede_rate"])
            adjust += (supersede - 0.5) * 8.0
            note.append("改主意率")
        score = round(min(100.0, max(0.0, base + adjust)), 1)
        combined["dimensions"][dim] = {
            "label": GDMS_DIMENSION_LABELS[dim],
            "score": score,
            "band": _band_label(score),
            "base": base,
            "adjust": round(adjust, 1),
            "adjust_notes": note,
        }
    return combined


def collect_signal_densities(texts: List[str]) -> Dict[str, float]:
    """词表信号密度采集（每千条文本消息命中条数）——纯函数，输入文本列表。

    late_night 不在此（占比口径按时间戳采集，复用大五层的
    late_night_ratio，不重复扫词表）。分析型路径非实时，朴素包含判断
    即可（10 万条 × 词表 ≈ 秒级）。
    """
    total = len(texts)
    if total == 0:
        return {}
    out: Dict[str, float] = {}
    for key, spec in _SIGNAL_SPECS.items():
        if not spec["enabled"] or not spec["patterns"]:
            continue
        hits = sum(1 for text in texts for pattern in spec["patterns"] if pattern in text)
        out[key] = round(hits * 1000.0 / total, 4)
    return out


def compute_decision_style(
    big5_scores: Dict[str, Optional[float]],
    signal_densities: Optional[Dict[str, Optional[float]]] = None,
    *,
    message_count: int = 0,
    memory_behaviors: Optional[Dict[str, Any]] = None,
    exploratory: Optional[Dict[str, Optional[float]]] = None,
) -> Dict[str, Any]:
    """总入口：通道 A + 通道 B（可选）+ 合成 + 探索性特征透传。"""
    a = channel_a_scores(big5_scores)
    b = channel_b_scores(signal_densities or {}, message_count=message_count)
    combined = combine_channels(a, b, memory_behaviors=memory_behaviors)
    return {
        "channel_a": a,
        "channel_b": b,
        "combined": combined,
        "exploratory": {
            key: (None if exploratory is None else exploratory.get(key))
            for key in EXPLORATORY_KEYS
        },
        "disclaimer": "从行为痕迹估计的决策风格倾向，非心理测评",
    }
