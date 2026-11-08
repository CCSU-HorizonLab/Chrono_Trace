"""脉搏页聚合 API 测试（指标直白化层：只翻译不新算）。"""

import os
import sqlite3
import sys
import time
from typing import Any, Dict

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import app.webview.api.pulse as pulse_mod
from app.webview.api.pulse import (
    PulseApiMixin,
    _directional_response_medians,
    _fmt_minutes,
    _medians_to_minutes,
    _monthly_overview,
    _temperature_label,
    _template_verdict,
    _trend_line,
    _warning_from_risk,
)

_DAY = 86400


# ----------------------------------------------------------------------
# 测试夹具：in-memory 库 + get_db 打桩（pulse 模块全部懒导入，
# 打 app.db.connection.get_db 即可覆盖）
# ----------------------------------------------------------------------

def _make_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        "CREATE TABLE messages (id INTEGER PRIMARY KEY, conversation_id INTEGER,"
        " is_sender INTEGER, timestamp INTEGER)"
    )
    conn.execute(
        "CREATE TABLE message_preprocessed (message_id INTEGER PRIMARY KEY,"
        " conversation_id INTEGER, char_count INTEGER, is_valid INTEGER)"
    )
    conn.execute(
        "CREATE TABLE response_times (id INTEGER PRIMARY KEY,"
        " reply_message_id INTEGER, conversation_id INTEGER,"
        " response_time_seconds REAL, is_abnormal INTEGER)"
    )
    conn.execute(
        "CREATE TABLE initiative_stats (conversation_id INTEGER PRIMARY KEY,"
        " total_sessions INTEGER, user_initiated_sessions INTEGER,"
        " other_initiated_sessions INTEGER)"
    )
    conn.execute(
        "CREATE TABLE affinity_scores (id INTEGER PRIMARY KEY,"
        " conversation_id INTEGER, analysis_version INTEGER,"
        " overall_score REAL, created_at INTEGER)"
    )
    return conn


@pytest.fixture
def db(monkeypatch):
    conn = _make_db()
    monkeypatch.setattr("app.db.connection.get_db", lambda: conn)
    yield conn
    conn.close()


def _insert_rt(db, msg_id, is_sender, ts, seconds, abnormal=0):
    """插一条回消息 + 对应 response_times（口径：reply 的发送方定方向）。"""
    db.execute(
        "INSERT INTO messages(id, conversation_id, is_sender, timestamp)"
        " VALUES (?, 1, ?, ?)",
        (msg_id, is_sender, ts),
    )
    db.execute(
        "INSERT INTO response_times(reply_message_id, conversation_id,"
        " response_time_seconds, is_abnormal) VALUES (?, 1, ?, ?)",
        (msg_id, seconds, abnormal),
    )


# ----------------------------------------------------------------------
# 纯函数
# ----------------------------------------------------------------------

class TestTemperatureLabel:
    def test_boundaries(self):
        assert _temperature_label(75) == "炽热"
        assert _temperature_label(74.9) == "温热"
        assert _temperature_label(60) == "温热"
        assert _temperature_label(59.9) == "温和"
        assert _temperature_label(45) == "温和"
        assert _temperature_label(44.9) == "转凉"
        assert _temperature_label(30) == "转凉"
        assert _temperature_label(0) == "冰点"


class TestFmtMinutes:
    def test_segments(self):
        assert "秒" in _fmt_minutes(0.5)
        assert _fmt_minutes(5) == "5 分钟"
        assert _fmt_minutes(90) == "1.5 小时"


# ----------------------------------------------------------------------
# 双向回复中位数（口径同海报 _poster_reply_stats）
# ----------------------------------------------------------------------

class TestDirectionalResponseMedians:
    def test_odd_and_even_median(self, db):
        now = int(time.time())
        # 我回 TA：3 条（奇数）→ 中位 120
        for i, sec in enumerate([300, 120, 60], start=1):
            _insert_rt(db, i, 1, now - 100, sec)
        # TA 回我：4 条（偶数）→ 排序 [30,60,90,600] 中间两值 (60+90)/2 = 75
        for i, sec in enumerate([30, 90, 60, 600], start=11):
            _insert_rt(db, i, 0, now - 100, sec)
        stats = _directional_response_medians(1, now - _DAY, now)
        assert stats["me_to_ta_median_sec"] == 120
        assert stats["ta_to_me_median_sec"] == pytest.approx(75)
        assert stats["me_count"] == 3
        assert stats["ta_count"] == 4

    def test_excludes_abnormal_and_null(self, db):
        now = int(time.time())
        _insert_rt(db, 1, 1, now - 100, 60)
        _insert_rt(db, 2, 1, now - 100, 999999, abnormal=1)  # 异常剔除
        _insert_rt(db, 3, 1, now - 100, None)  # NULL 剔除
        stats = _directional_response_medians(1, now - _DAY, now)
        assert stats["me_count"] == 1
        assert stats["me_to_ta_median_sec"] == 60
        assert stats["ta_count"] == 0
        assert stats["ta_to_me_median_sec"] is None

    def test_empty_window(self, db):
        now = int(time.time())
        assert _directional_response_medians(1, now - _DAY, now) is None

    def test_minutes_conversion(self):
        assert _medians_to_minutes(None) is None
        out = _medians_to_minutes(
            {"me_to_ta_median_sec": 90, "ta_to_me_median_sec": None,
             "me_count": 2, "ta_count": 0}
        )
        assert out["me_to_ta_median_min"] == 1.5
        assert out["ta_to_me_median_min"] is None


# ----------------------------------------------------------------------
# 本月速览
# ----------------------------------------------------------------------

class TestMonthlyOverview:
    def test_aggregation_and_month_boundary(self, db):
        now = int(time.time())
        month_start = pulse_mod._month_start_ts(now)
        # 当月内一条深夜（03:00 本地）+ 一条白天；上月一条不计
        lt = time.localtime(now)
        late = int(time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, 3, 0, 0, 0, 0, -1)))
        day = int(time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, 12, 0, 0, 0, 0, -1)))
        in_month = [t for t in (late, day) if month_start <= t <= now]
        # 构造保证：若当天 12:00 尚未到（凌晨跑测试），只用已过时刻
        for idx, ts in enumerate(in_month, start=1):
            db.execute(
                "INSERT INTO messages(id, conversation_id, is_sender, timestamp)"
                " VALUES (?, 1, ?, ?)",
                (idx, idx % 2, ts),
            )
            db.execute(
                "INSERT INTO message_preprocessed(message_id, conversation_id,"
                " char_count, is_valid) VALUES (?, 1, ?, 1)",
                (idx, 10 * idx),
            )
        db.execute(
            "INSERT INTO messages(id, conversation_id, is_sender, timestamp)"
            " VALUES (99, 1, 1, ?)", (month_start - _DAY,)
        )
        db.execute(
            "INSERT INTO message_preprocessed(message_id, conversation_id,"
            " char_count, is_valid) VALUES (99, 1, 999, 1)"
        )
        out = _monthly_overview(1, now)
        assert out["messages"] == len(in_month)
        assert out["chars"] == sum(10 * i for i in range(1, len(in_month) + 1))
        # 深夜条数：03:00 那条若已入月则计 1，12:00 不计
        assert out["late_night"] == (1 if late in in_month else 0)

    def test_invalid_chars_excluded(self, db):
        now = int(time.time())
        db.execute(
            "INSERT INTO messages(id, conversation_id, is_sender, timestamp)"
            " VALUES (1, 1, 1, ?)", (now,)
        )
        db.execute(
            "INSERT INTO message_preprocessed(message_id, conversation_id,"
            " char_count, is_valid) VALUES (1, 1, 555, 0)"
        )
        out = _monthly_overview(1, now)
        assert out["messages"] == 1
        assert out["chars"] == 0


# ----------------------------------------------------------------------
# 趋势线 / 预警 / 模板判读
# ----------------------------------------------------------------------

class TestTrendLine:
    def test_caliber_filter_and_order(self, db):
        for ver, score, ts in [(6, 50, 100), (7, 99, 200), (6, 60, 300), (6, 55, 200)]:
            db.execute(
                "INSERT INTO affinity_scores(conversation_id, analysis_version,"
                " overall_score, created_at) VALUES (1, ?, ?, ?)",
                (ver, score, ts),
            )
        line = _trend_line(1, caliber=6)
        # 只取 caliber 6，按 created_at 升序（同刻按插入序稳定）
        assert [s for _, s in line] == [50, 55, 60]


class TestWarningFromRisk:
    def test_normal_returns_none(self):
        risk = {
            "highest_level": "未见异常",
            "signals": {"hot_cold": {"label": "忽冷忽热", "level": "未见异常", "note": "n"}},
        }
        assert _warning_from_risk(risk) is None
        assert _warning_from_risk(None) is None

    def test_alert_keeps_only_abnormal_signals(self):
        risk = {
            "highest_level": "预警",
            "signals": {
                "hot_cold": {"label": "忽冷忽热", "level": "预警", "note": "波动大"},
                "one_sided": {"label": "单方面付出", "level": "留意", "note": "失衡"},
                "warm_then_cold": {"label": "先热后冷", "level": "未见异常", "note": "n"},
            },
        }
        out = _warning_from_risk(risk)
        assert out["level"] == "预警"
        assert [it["label"] for it in out["items"]] == ["忽冷忽热", "单方面付出"]

    def test_mismatch_highest_but_no_items(self):
        # highest 非正常但 signals 全空 → 不输出（防御：不占焦虑空间）
        assert _warning_from_risk({"highest_level": "预警", "signals": {}}) is None


class TestTemplateVerdict:
    def test_three_segments(self):
        text = _template_verdict(
            {"score": 62, "label": "温热", "delta": -2.5},
            {"me_pct": 70, "total_sessions": 10, "user_initiated": 7, "other_initiated": 3},
            {"me_to_ta_median_min": 30, "ta_to_me_median_min": 5,
             "me_count": 3, "ta_count": 3},
        )
        assert "关系温度 62（温热）" in text
        assert "下降 2.5 分" in text
        assert "对话多由你发起（70%）" in text
        assert "TA 回你" in text and "更快" in text

    def test_balanced_and_empty(self):
        text = _template_verdict(
            None,
            {"me_pct": 50, "total_sessions": 4, "user_initiated": 2, "other_initiated": 2},
            {"me_to_ta_median_min": 5, "ta_to_me_median_min": 5, "me_count": 2, "ta_count": 2},
        )
        assert "双方话题发起较为均衡" in text
        assert "双方回复节奏相当" in text
        assert _template_verdict(None, None, None) == ""


# ----------------------------------------------------------------------
# get_pulse_overview 全 payload 组装
# ----------------------------------------------------------------------

def _base_payload(result=None, history=None, stale=False, pending=0):
    return {
        "ok": True,
        "result": result,
        "analysis_stale": stale,
        "pending_message_count": pending,
        "history": history or {},
    }


def _full_result(llm_interpretation=None, absent_reason=None, score=62.0):
    return {
        "overall_score": score,
        "analysis_caliber": 6,
        "llm_relationship": (
            {"interpretation": llm_interpretation} if llm_interpretation else None
        ),
        "llm_relationship_absent_reason": absent_reason,
        "risk_assessment": {
            "highest_level": "留意",
            "signals": {
                "one_sided": {"label": "单方面付出", "level": "留意", "note": "你发起居多"},
            },
        },
    }


class _Stub(PulseApiMixin):
    """Bridge 多继承的最小替身：只提供 get_affinity_scores。"""

    def __init__(self, payload):
        self._payload = payload

    def get_affinity_scores(self, conversation_id):
        return self._payload


class TestGetPulseOverview:
    def test_llm_verdict_and_full_payload(self, db, monkeypatch):
        now = int(time.time())
        # 近 30 天一条我回 TA；initiative 7:3；历史两行同口径
        _insert_rt(db, 1, 1, now - 100, 120)
        db.execute(
            "INSERT INTO initiative_stats VALUES (1, 10, 7, 3)"
        )
        for score, ts in [(58, now - 10 * _DAY), (62, now - _DAY)]:
            db.execute(
                "INSERT INTO affinity_scores(conversation_id, analysis_version,"
                " overall_score, created_at) VALUES (1, 6, ?, ?)",
                (score, ts),
            )
        stub = _Stub(_base_payload(result=_full_result(llm_interpretation="LLM 综合判读文字")))
        out = stub.get_pulse_overview(1)

        assert out["ok"] is True
        assert out["analyzed"] is True
        # verdict 走 LLM
        assert out["verdict"] == {"text": "LLM 综合判读文字", "source": "llm"}
        # 温度：分数+话术+趋势线（当前口径过滤后两条）
        assert out["temperature"]["score"] == 62.0
        assert out["temperature"]["label"] == "温热"
        assert [s for _, s in out["temperature"]["trend_line"]] == [58, 62]
        # 主动天平
        assert out["initiative"]["me_pct"] == 70.0
        # 回应温度：近窗有数据、前窗无
        assert out["response"]["recent"]["me_to_ta_median_min"] == 2.0
        assert out["response"]["prev"] is None
        # 预警翻译
        assert out["warning"]["level"] == "留意"
        assert out["warning"]["items"][0]["label"] == "单方面付出"
        # professional 透传
        assert out["professional"]["result"]["overall_score"] == 62.0
        assert out["professional"]["absent_reason"] is None

    def test_template_verdict_fallback(self, db):
        stub = _Stub(_base_payload(result=_full_result(absent_reason="未配置 LLM")))
        out = stub.get_pulse_overview(1)
        assert out["verdict"]["source"] == "template"
        assert "关系温度 62（温热）" in out["verdict"]["text"]
        assert out["professional"]["absent_reason"] == "未配置 LLM"

    def test_unanalyzed_conversation(self, db):
        stub = _Stub(_base_payload(result=None))
        out = stub.get_pulse_overview(999)
        assert out["ok"] is True
        assert out["analyzed"] is False
        assert out["verdict"] is None
        assert out["temperature"] is None
        assert out["warning"] is None
        assert out["response"] is None
        assert out["monthly"]["messages"] == 0
        assert out["professional"]["result"] is None

    def test_delta_only_when_comparable(self, db):
        # comparable=False → delta=None（口径不比不显趋势）
        stub = _Stub(_base_payload(
            result=_full_result(score=50.0),
            history={"score_trend": 5.0, "comparable": False},
        ))
        out = stub.get_pulse_overview(1)
        assert out["temperature"]["delta"] is None

        stub2 = _Stub(_base_payload(
            result=_full_result(score=50.0),
            history={"score_trend": 5.0, "comparable": True},
        ))
        assert stub2.get_pulse_overview(1)["temperature"]["delta"] == 5.0

    def test_affinity_read_failure_degrades(self, db):
        """好感读出口失败时降级：其余指标照常，analyzed=False 不硬失败。"""

        class _Fail(_Stub):
            def get_affinity_scores(self, conversation_id):
                return {"ok": False, "error": "boom"}

        out = _Fail(_base_payload()).get_pulse_overview(1)
        assert out["ok"] is True
        assert out["analyzed"] is False
        assert out["verdict"] is None
        assert out["monthly"]["messages"] == 0
