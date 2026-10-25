"""主动性均衡双闸门（二项检验 + Cohen's h）与问答口吻测试。

口径背景：51/49 这类近对半分不能定性「谁更主动」——双侧精确
二项检验 p<0.05 且效应量 h≥0.2 才给方向，h≥0.5 才说「明显」。
"""

import os
import sqlite3
import sys


sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.analysis.initiative_balance import (
    BAND_BALANCED,
    BAND_INSUFFICIENT,
    BAND_OTHER_DOMINANT,
    BAND_OTHER_LEANS,
    BAND_SELF_DOMINANT,
    BAND_SELF_LEANS,
    _two_sided_binomial_p,
    classify_initiative,
)


def test_near_half_never_claims_direction():
    # 用户实录：49/51 与 51/49 都不得定性谁更主动
    assert classify_initiative(100, 49) == BAND_BALANCED
    assert classify_initiative(100, 51) == BAND_BALANCED
    assert classify_initiative(100, 50) == BAND_BALANCED


def test_small_sample_leaning_is_noise():
    # 6 场 4/2（66.7%）：二项 p≈0.69，与对半不可区分
    assert classify_initiative(6, 4) == BAND_BALANCED
    # 100 场 60/40：p≈0.057 仍不过 α=0.05
    assert classify_initiative(100, 60) == BAND_BALANCED


def test_significant_small_effect_is_leaning():
    # 200 场 62%：p<0.001 且 h≈0.24（小效应）→ 略偏向
    assert classify_initiative(200, 124) == BAND_OTHER_LEANS
    assert classify_initiative(200, 76) == BAND_SELF_LEANS


def test_medium_effect_is_dominant():
    # 20 场 90%：p≈0.0004 且 h≈0.93（大效应）→ 明显
    assert classify_initiative(20, 18) == BAND_OTHER_DOMINANT
    assert classify_initiative(20, 2) == BAND_SELF_DOMINANT


def test_insufficient_sample():
    assert classify_initiative(4, 3) == BAND_INSUFFICIENT
    assert classify_initiative(0, 0) == BAND_INSUFFICIENT


def test_binomial_p_exact_value():
    # n=20, k=18：p = 2·(C(20,18)+C(20,19)+C(20,20))/2^20
    expected = 2 * (190 + 20 + 1) / 2**20
    assert abs(_two_sided_binomial_p(18, 20) - expected) < 1e-12


def _bridge_with_stats(total, user_initiated, other_initiated, rate):
    """构造内存库 + AnalysisReadApiMixin，绕开线程本地 get_db。"""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        "CREATE TABLE initiative_stats (conversation_id INTEGER PRIMARY KEY, "
        "total_sessions INTEGER, user_initiated_sessions INTEGER, "
        "other_initiated_sessions INTEGER, initiative_rate REAL, "
        "last_updated INTEGER)"
    )
    conn.execute(
        "INSERT INTO initiative_stats VALUES (1, ?, ?, ?, ?, 0)",
        (total, user_initiated, other_initiated, rate),
    )
    conn.commit()

    from app.db import connection as db_connection
    from app.webview.api.analysis_read import AnalysisReadApiMixin

    original = db_connection.get_db
    db_connection.get_db = lambda: conn
    try:
        return AnalysisReadApiMixin().get_initiative_stats(1)
    finally:
        db_connection.get_db = original
        conn.close()


def test_bridge_interpretation_balanced_tone():
    # 51/49：不再出现「您更主动/对方更主动」的定性
    result = _bridge_with_stats(100, 51, 49, 0.49)
    text = result["data"]["interpretation"]
    assert "谈不上谁更主动" in text
    assert "更主动" not in text.replace("谈不上谁更主动", "")


def test_bridge_interpretation_leaning_tone():
    result = _bridge_with_stats(200, 76, 124, 0.62)
    assert result["data"]["interpretation"] == (
        "对方发起 62% 的会话，主动性略偏向对方"
    )


def test_bridge_interpretation_dominant_tone():
    result = _bridge_with_stats(20, 2, 18, 0.9)
    assert result["data"]["interpretation"] == (
        "对方发起 90% 的会话，主动性明显在对方一侧"
    )


def test_bridge_interpretation_insufficient():
    result = _bridge_with_stats(3, 2, 1, 1 / 3)
    assert result["data"]["interpretation"] == "样本还太少（3 场会话），先不下结论"
