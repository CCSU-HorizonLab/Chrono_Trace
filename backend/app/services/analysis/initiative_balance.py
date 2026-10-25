# -*- coding: utf-8 -*-
"""主动性均衡判定：双侧二项检验 + Cohen's h 双闸门。

近对半的发起占比（如 51%/49%）不能定性为「谁更主动」——差异要
下结论须同时过两道闸门：

1. **统计显著**：双侧精确二项检验（H0: 双方发起对半）p < 0.05。
   小样本下 60/40 也会被挡（6 场 4/2 的 p≈0.69，与对半无法区分）。
2. **效应量达标**：Cohen's h ≥ 0.2（小效应下限，对 0.5 基准约合
   60/40）才谈方向，≥ 0.5（中效应，约 74/26）才算「明显」。
   大样本下 52/48 虽然 p 值能过，效应量不足同样不算。

两道闸门对应公开研究的通行口径：Cohen 效应量分级（h 0.2/0.5/0.8
= 小/中/大）与 α=0.05 检验水准；实测 55 vs 50 在 α=0.05、功效 80%
下约需 600+ 场会话才能分辨，日常几十到几百场的量级里近对半分
理应判均衡。
"""
from __future__ import annotations

import math

# 分带常量（other/self 指发起方归属）
BAND_INSUFFICIENT = "insufficient"      # 样本不足
BAND_BALANCED = "balanced"              # 与对半不可区分 / 效应量可忽略
BAND_OTHER_LEANS = "other_leans"        # 略偏向对方（小效应）
BAND_SELF_LEANS = "self_leans"          # 略偏向自己（小效应）
BAND_OTHER_DOMINANT = "other_dominant"  # 明显对方（中效应以上）
BAND_SELF_DOMINANT = "self_dominant"    # 明显自己（中效应以上）

MIN_SESSIONS = 5   # 少于该场次不判断
ALPHA = 0.05       # 双侧检验水准
H_SMALL = 0.2      # Cohen's h 小效应下限（≈60/40）
H_MEDIUM = 0.5     # Cohen's h 中效应下限（≈74/26）

_LN2 = math.log(2.0)
_ARCSIN_SQRT_HALF = math.asin(math.sqrt(0.5))  # = π/4


def _two_sided_binomial_p(k: int, n: int) -> float:
    """双侧精确二项检验 p 值（H0: p=0.5，观测 k/n）。

    统计「出现概率不高于观测值」的全部结果概率之和；PMF 经
    lgamma 计算，任意 n 无下溢。
    """
    ln_ref = _ln_choose(n, k) - n * _LN2
    total = 0.0
    for i in range(n + 1):
        ln_p = _ln_choose(n, i) - n * _LN2
        if ln_p <= ln_ref + 1e-9:
            total += math.exp(ln_p)
    return min(1.0, total)


def _ln_choose(n: int, k: int) -> float:
    return (
        math.lgamma(n + 1) - math.lgamma(k + 1) - math.lgamma(n - k + 1)
    )


def classify_initiative(total_sessions: int, other_initiated: int) -> str:
    """按双闸门判定主动发起的均衡分带。

    Args:
        total_sessions: 会话总数
        other_initiated: 对方发起的会话数

    Returns:
        BAND_* 分带常量之一
    """
    if total_sessions < MIN_SESSIONS:
        return BAND_INSUFFICIENT
    p_other = other_initiated / total_sessions
    if p_other == 0.5:
        return BAND_BALANCED
    # 闸门 1：方向显著性（取多数侧计数做双侧检验）
    majority = max(other_initiated, total_sessions - other_initiated)
    if _two_sided_binomial_p(majority, total_sessions) >= ALPHA:
        return BAND_BALANCED
    # 闸门 2：效应量分级（Cohen's h = 2·arcsin√p − π/2）
    h = 2.0 * math.asin(math.sqrt(p_other)) - 2.0 * _ARCSIN_SQRT_HALF
    magnitude = abs(h)
    if magnitude < H_SMALL:
        return BAND_BALANCED
    to_other = h > 0
    if magnitude < H_MEDIUM:
        return BAND_OTHER_LEANS if to_other else BAND_SELF_LEANS
    return BAND_OTHER_DOMINANT if to_other else BAND_SELF_DOMINANT
