"""好感度历史分数测试（落库/趋势/口径可比性）。"""

import os
import sqlite3
import sys
from dataclasses import dataclass, field
from typing import Dict

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import app.services.analysis.affinity_history as hist_mod
from app.services.analysis.affinity_history import (
    compute_trend,
    get_recent_scores,
    record_score_history,
)


@dataclass
class _Dim:
    score: float = 0.0
    weight: float = 0.0
    weighted_score: float = 0.0
    sub_scores: Dict[str, float] = field(default_factory=dict)


@dataclass
class _Result:
    overall_score: float = 60.0
    analysis_caliber: int = 4
    analysis_duration_ms: int = 1200
    emotional_resonance: _Dim = field(default_factory=lambda: _Dim(70, 0.4, 28))
    chat_positivity: _Dim = field(default_factory=lambda: _Dim(50, 0.35, 17.5))
    attitude_tendency: _Dim = field(default_factory=lambda: _Dim(40, 0.25, 10))
    preference_compatibility: _Dim = None  # type: ignore[assignment]
    intimacy_signals: _Dim = field(default_factory=lambda: _Dim(60, 0.12, 7.2))
    llm_relationship: _Dim = None  # type: ignore[assignment]


class _Stats:
    total_message_count = 500
    total_interaction_pairs = 200


@pytest.fixture
def db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    # 与 schema.sql 的 affinity_scores 同构（含 CHECK 约束）
    conn.execute("""
        CREATE TABLE affinity_scores (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            conversation_id INTEGER NOT NULL,
            analysis_version INTEGER DEFAULT 1,
            overall_score REAL NOT NULL,
            emotional_resonance_score REAL NOT NULL,
            chat_positivity_score REAL NOT NULL,
            attitude_tendency_score REAL NOT NULL,
            preference_compatibility_score REAL NOT NULL,
            sub_scores_json TEXT,
            message_count INTEGER NOT NULL,
            interaction_pair_count INTEGER NOT NULL,
            config_snapshot TEXT,
            analysis_duration_ms INTEGER,
            created_at INTEGER NOT NULL
        )
    """)
    yield conn
    conn.close()


@pytest.fixture(autouse=True)
def patch_db(db, monkeypatch):
    monkeypatch.setattr(hist_mod, "get_db", lambda: db)


def test_record_inserts_row_with_caliber_and_full_subscores_json(db):
    record_score_history(1, _Result(overall_score=66.5), stats=_Stats(),
                         config_snapshot={"config_fingerprint": "abc"})
    row = db.execute("SELECT * FROM affinity_scores").fetchone()
    assert row["analysis_version"] == 4
    assert row["overall_score"] == 66.5
    assert row["message_count"] == 500
    import json
    sub = json.loads(row["sub_scores_json"])
    assert set(sub) == {
        "emotional_resonance", "chat_positivity", "attitude_tendency",
        "preference_compatibility", "intimacy_signals", "llm_relationship",
    }
    assert sub["intimacy_signals"]["score"] == 60


def test_trend_computed_from_last_two_rows(db):
    record_score_history(1, _Result(overall_score=50.0))
    record_score_history(1, _Result(overall_score=58.0))
    trend = compute_trend(1)
    assert trend["last_score"] == 58.0
    assert trend["prev_score"] == 50.0
    assert trend["score_trend"] == 8.0
    assert trend["comparable"] is True


def test_trend_incomparable_across_caliber_versions(db):
    record_score_history(1, _Result(overall_score=50.0, analysis_caliber=3))
    record_score_history(1, _Result(overall_score=58.0, analysis_caliber=4))
    trend = compute_trend(1)
    assert trend["comparable"] is False
    assert trend["score_trend"] is None  # 前端据此不显示趋势徽章


def test_single_row_has_no_trend(db):
    record_score_history(1, _Result(overall_score=42.0))
    trend = compute_trend(1)
    assert trend["last_score"] == 42.0
    assert trend["prev_score"] is None
    assert trend["comparable"] is False


def test_record_failure_does_not_raise(db):
    # 坏结果对象（缺 overall_score）只记日志不抛
    record_score_history(1, object())  # type: ignore[arg-type]
    assert get_recent_scores(1) == []
