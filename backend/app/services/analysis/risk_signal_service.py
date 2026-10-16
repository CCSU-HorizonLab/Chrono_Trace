"""风险预警模块：独立于好感度总分的关系风险信号判定。

四类信号（命名对齐调研定名表）：
- 忽冷忽热 hot_cold——热度忽高忽低（日消息量波动）
- 单向投入 one_sided——发起失衡 + 连发未回 + 敷衍回复的组合
- 现实否认 reality_denial——否认对方感受/记忆的话术 + 撤回集中
- 先热后冷 warm_then_cold——早期热情、近期明显降温

双证据判定：统计条件与 LLM 对话证据（relationship_llm_service 的
risk_evidence）同时满足才「预警」；单边最多「留意」；LLM 维缺席时
全部封顶「留意」。好感度测「多好」，风险测「伤不伤」——语义正交，
结果不参与好感度总分（见 AffinityAnalysisResult.risk_assessment）。

阈值为模块常量，不进用户配置（避免扩大 config fingerprint 面）。
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional, Tuple

from .engagement_metrics import EngagementMetrics
from .preprocessing_orchestrator import PreprocessedStatistics

logger = logging.getLogger(__name__)


def _per_100(events: int, total: int) -> float:
    """事件数折算为每百条消息频次。"""
    if total <= 0:
        return 0.0
    return events / total * 100.0


LEVEL_ALERT = "预警"
LEVEL_WATCH = "留意"
LEVEL_NORMAL = "未见异常"

# 统计条件阈值
HOT_COLD_CV_THRESHOLD = 0.8             # 日消息量波动系数（变异系数）
ONE_SIDED_INITIATION_SHARE = 0.35       # 对方发起会话占比低于此视为失衡
ONE_SIDED_BURST_PER_100 = 3.0           # 我方连发未回每百条消息频次
ONE_SIDED_PERFUNCTORY_RATE = 0.15       # 对方敷衍回复率
ONE_SIDED_MIN_CONDITIONS = 2            # 三条件至少同时满足几项
REALITY_DENIAL_REVOKE_PER_100 = 2.0     # 双方撤回每百条消息频次
WARM_THEN_COLD_DECLINE_RATIO = 0.5      # 近期日均降至早期日均的比例以下
WARM_THEN_COLD_MIN_EARLY_DAILY = 5.0    # 早期日均基线（过低无下降可言）

SIGNAL_LABELS = {
    "hot_cold": "忽冷忽热",
    "one_sided": "单向投入",
    "reality_denial": "现实否认",
    "warm_then_cold": "先热后冷",
}


class RiskSignalService:
    """关系风险信号判定（纯计算，输入 metrics/stats/LLM 证据）。"""

    def assess(
        self,
        conversation_id: int,
        metrics: EngagementMetrics,
        stats: Optional[PreprocessedStatistics] = None,
        llm_result: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """产出 {signals, highest_level, llm_evidence_available}。"""
        evidence = self._llm_evidence(llm_result)
        llm_available = bool(evidence is not None)

        checks = {
            "hot_cold": self._check_hot_cold(metrics),
            "one_sided": self._check_one_sided(metrics, stats),
            "reality_denial": self._check_reality_denial(metrics),
            "warm_then_cold": self._check_warm_then_cold(metrics),
        }

        signals: Dict[str, Dict[str, Any]] = {}
        levels = []
        for key, (stat_met, basis) in checks.items():
            found = bool(evidence and evidence.get(key, {}).get("found"))
            quotes = [
                str(q)[:60]
                for q in ((evidence or {}).get(key, {}).get("quotes") or [])[:3]
            ]
            if stat_met and found:
                level = LEVEL_ALERT
            elif stat_met or found:
                level = LEVEL_WATCH
            else:
                level = LEVEL_NORMAL
            levels.append(level)
            signals[key] = {
                "label": SIGNAL_LABELS[key],
                "level": level,
                "stat_basis": basis,
                "evidence": quotes,
                "note": self._note(key, stat_met, found),
            }

        highest = LEVEL_NORMAL
        for level in (LEVEL_NORMAL, LEVEL_WATCH, LEVEL_ALERT):
            if level in levels:
                highest = level
        result = {
            "signals": signals,
            "highest_level": highest,
            "llm_evidence_available": llm_available,
        }
        logger.info(
            "[风险预警] 会话 %s: 最高级=%s (%s)",
            conversation_id,
            highest,
            "; ".join(f"{k}={v['level']}" for k, v in signals.items()),
        )
        return result

    # ---------- LLM 证据 ----------

    @staticmethod
    def _llm_evidence(llm_result: Optional[Dict[str, Any]]) -> Optional[Dict]:
        """取 LLM 维的风险对话证据；维缺席/无证据时返回 None。"""
        if not isinstance(llm_result, dict):
            return None
        evidence = llm_result.get("risk_evidence")
        return evidence if isinstance(evidence, dict) else None

    # ---------- 统计条件 ----------

    @staticmethod
    def _check_hot_cold(
        metrics: EngagementMetrics,
    ) -> Tuple[bool, str]:
        cv = metrics.daily_cv_active
        if cv is None:
            return False, "活跃日不足两天，无法衡量波动"
        met = cv >= HOT_COLD_CV_THRESHOLD
        return met, f"日消息量波动系数 {cv:.2f}（阈值 {HOT_COLD_CV_THRESHOLD}）"

    @staticmethod
    def _check_one_sided(
        metrics: EngagementMetrics,
        stats: Optional[PreprocessedStatistics],
    ) -> Tuple[bool, str]:
        conditions = []
        basis = []
        total_sessions = int(getattr(stats, "total_sessions", 0) or 0)
        if total_sessions > 0:
            other_share = (
                float(getattr(stats, "contact_initiated_count", 0) or 0)
                / total_sessions
            )
            if other_share < ONE_SIDED_INITIATION_SHARE:
                conditions.append("发起失衡")
            basis.append(f"对方发起占比 {other_share:.0%}")
        else:
            basis.append("无会话记录")
        burst_per_100 = _per_100(
            metrics.burst_unanswered_self, metrics.text_message_count
        )
        if burst_per_100 >= ONE_SIDED_BURST_PER_100:
            conditions.append("我方连发未回")
        basis.append(f"我方连发未回 {burst_per_100:.1f} 次/百条")
        if metrics.perfunctory_rate_other >= ONE_SIDED_PERFUNCTORY_RATE:
            conditions.append("对方敷衍回复")
        basis.append(f"对方敷衍回复率 {metrics.perfunctory_rate_other:.0%}")

        met = len(conditions) >= ONE_SIDED_MIN_CONDITIONS
        detail = f"（命中：{'、'.join(conditions)}）" if conditions else ""
        return met, "；".join(basis) + detail

    @staticmethod
    def _check_reality_denial(
        metrics: EngagementMetrics,
    ) -> Tuple[bool, str]:
        total_revokes = metrics.revoke_self + metrics.revoke_other
        per_100 = _per_100(total_revokes, metrics.text_message_count)
        met = per_100 >= REALITY_DENIAL_REVOKE_PER_100
        return met, f"撤回频次 {per_100:.1f} 次/百条（阈值 {REALITY_DENIAL_REVOKE_PER_100}）"

    @staticmethod
    def _check_warm_then_cold(
        metrics: EngagementMetrics,
    ) -> Tuple[bool, str]:
        days = sorted(metrics.daily_counts) if metrics.daily_counts else []
        if len(days) < 6:
            return False, "活跃日不足六天，无法对照前后热度"
        third = max(1, len(days) // 3)
        early_days = days[:third]
        recent_days = days[-third:]
        early_mean = sum(metrics.daily_counts[d] for d in early_days) / third
        recent_mean = sum(metrics.daily_counts[d] for d in recent_days) / third
        if early_mean < WARM_THEN_COLD_MIN_EARLY_DAILY:
            return False, f"早期日均 {early_mean:.1f} 条，基线过低不构成降温"
        met = recent_mean < early_mean * WARM_THEN_COLD_DECLINE_RATIO
        if recent_mean < early_mean:
            change = f"降幅 {1 - recent_mean / early_mean:.0%}"
        else:
            change = f"升幅 {recent_mean / early_mean - 1:.0%}"
        return met, (
            f"早期日均 {early_mean:.1f} 条 → 近期 {recent_mean:.1f} 条"
            f"（{change}）"
        )

    # ---------- 说明文本 ----------

    @staticmethod
    def _note(key: str, stat_met: bool, found: bool) -> str:
        # 未见异常用中性文案：告急话术配绿色级会自相矛盾
        # （如近期日均高于早期却写「明显降温」）
        if not stat_met and not found:
            return {
                "hot_cold": "日消息量波动在正常范围，热度供给稳定",
                "one_sided": "双方投入较为均衡，无明显单向付出",
                "reality_denial": "未发现否认感受或记忆的话术",
                "warm_then_cold": "前后热度变化在正常范围，未见明显退潮",
            }[key]
        text = {
            "hot_cold": "热度忽高忽低，情绪供给不稳定，容易让人持续期待又落空",
            "one_sided": "互动投入明显偏向一方：一方持续找话题，另一方较少回应",
            "reality_denial": "出现否认你感受或记忆的话术，并伴随消息撤回，需警惕被扭曲自我认知",
            "warm_then_cold": "早期热情、近期明显降温，关系热度可能正在退潮",
        }[key]
        if stat_met and not found:
            return text + "（统计指标偏高，暂未找到对应对话证据）"
        if found and not stat_met:
            return text + "（仅对话证据，统计指标未达阈值）"
        return text
