"""风险预警模块测试（纯输入判定，双证据口径）。"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.analysis.engagement_metrics import EngagementMetrics
from app.services.analysis.preprocessing_orchestrator import PreprocessedStatistics
from app.services.analysis.risk_signal_service import (
    LEVEL_ALERT,
    LEVEL_NORMAL,
    LEVEL_WATCH,
    RiskSignalService,
)


def make_stats(sessions=20, contact_initiated=3):
    stats = PreprocessedStatistics()
    stats.total_sessions = sessions
    stats.contact_initiated_count = contact_initiated
    return stats


def evidence(**overrides):
    base = {key: {"found": False, "quotes": []} for key in
            ("hot_cold", "one_sided", "reality_denial", "warm_then_cold")}
    for key, quotes in overrides.items():
        base[key] = {"found": True, "quotes": quotes}
    return {"risk_evidence": base}


# ===== 双证据判定 =====


def test_stat_and_evidence_both_met_yields_alert():
    metrics = EngagementMetrics(daily_cv_active=1.2)
    result = RiskSignalService().assess(
        1, metrics, stats=make_stats(), llm_result=evidence(hot_cold=["前几天还天天聊"])
    )
    assert result["signals"]["hot_cold"]["level"] == LEVEL_ALERT
    assert result["signals"]["hot_cold"]["evidence"] == ["前几天还天天聊"]
    assert result["highest_level"] == LEVEL_ALERT


def test_stat_only_caps_at_watch():
    metrics = EngagementMetrics(daily_cv_active=1.2)
    result = RiskSignalService().assess(1, metrics, stats=make_stats(), llm_result=evidence())
    assert result["signals"]["hot_cold"]["level"] == LEVEL_WATCH
    assert "暂未找到对应对话证据" in result["signals"]["hot_cold"]["note"]


def test_evidence_only_caps_at_watch():
    metrics = EngagementMetrics(daily_cv_active=0.3)
    result = RiskSignalService().assess(
        1, metrics, stats=make_stats(), llm_result=evidence(hot_cold=["你忽冷忽热的"])
    )
    assert result["signals"]["hot_cold"]["level"] == LEVEL_WATCH
    assert "仅对话证据" in result["signals"]["hot_cold"]["note"]


def test_llm_absent_caps_all_at_watch():
    metrics = EngagementMetrics(
        daily_cv_active=1.2,
        text_message_count=100,
        revoke_self=5, revoke_other=3,
    )
    result = RiskSignalService().assess(1, metrics, stats=make_stats(), llm_result=None)
    assert result["llm_evidence_available"] is False
    assert LEVEL_ALERT not in {s["level"] for s in result["signals"].values()}
    assert result["signals"]["hot_cold"]["level"] == LEVEL_WATCH
    assert result["signals"]["reality_denial"]["level"] == LEVEL_WATCH


def test_no_signal_yields_normal():
    metrics = EngagementMetrics(daily_cv_active=0.2)
    result = RiskSignalService().assess(1, metrics, stats=make_stats(), llm_result=evidence())
    assert result["highest_level"] == LEVEL_NORMAL
    assert all(s["level"] == LEVEL_NORMAL for s in result["signals"].values())


# ===== 各信号统计条件 =====


def test_one_sided_needs_two_of_three_conditions():
    svc = RiskSignalService()
    # 仅发起失衡：不触发
    only_initiation = EngagementMetrics()
    met, _ = svc._check_one_sided(only_initiation, make_stats(contact_initiated=3))
    assert met is False
    # 发起失衡 + 我方连发未回：触发
    two_hits = EngagementMetrics(text_message_count=100, burst_unanswered_self=5)
    met, basis = svc._check_one_sided(two_hits, make_stats(contact_initiated=3))
    assert met is True
    assert "发起失衡" in basis and "连发未回" in basis
    # 敷衍 + 连发（发起均衡）：触发
    met, _ = svc._check_one_sided(
        EngagementMetrics(text_message_count=100, burst_unanswered_self=4,
                          perfunctory_rate_other=0.25),
        make_stats(contact_initiated=12),
    )
    assert met is True


def test_reality_denial_uses_revoke_per_100():
    svc = RiskSignalService()
    # 200 条消息仅 3 次撤回 = 1.5/100，未达阈值
    met, _ = svc._check_reality_denial(
        EngagementMetrics(text_message_count=200, revoke_self=1, revoke_other=2)
    )
    assert met is False
    # 100 条消息 3 次撤回 = 3.0/100，触发
    met, basis = svc._check_reality_denial(
        EngagementMetrics(text_message_count=100, revoke_self=2, revoke_other=1)
    )
    assert met is True
    assert "撤回频次" in basis


def test_warm_then_cold_compares_first_and_last_third():
    svc = RiskSignalService()
    # 9 个活跃日：前段日均 12 → 近段日均 3（降幅 75%）触发
    daily = {}
    for d in range(9):
        daily[f"2026-0{d + 1}"] = 12 if d < 3 else (3 if d >= 6 else 8)
    met, basis = svc._check_warm_then_cold(EngagementMetrics(daily_counts=daily))
    assert met is True
    assert "降幅 75%" in basis
    # 基线过低不触发
    low = {f"d{i}": 2 for i in range(9)}
    met, _ = svc._check_warm_then_cold(EngagementMetrics(daily_counts=low))
    assert met is False
    # 活跃日不足
    met, _ = svc._check_warm_then_cold(EngagementMetrics(daily_counts={"a": 5}))
    assert met is False
