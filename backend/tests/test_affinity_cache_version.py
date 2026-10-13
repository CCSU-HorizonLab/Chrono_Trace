import os
import sqlite3
import sys


sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.analysis.affinity_analysis_service import (
    AffinityAnalysisResult,
    AffinityAnalysisService,
    DimensionScore,
)


def create_settings_db():
    db = sqlite3.connect(":memory:")
    db.execute(
        """
        CREATE TABLE settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            updated_at INTEGER NOT NULL
        )
        """
    )
    db.commit()
    return db


def create_service(monkeypatch, db):
    monkeypatch.setattr("app.services.analysis.affinity_analysis_service.get_db", lambda: db)
    service = AffinityAnalysisService.__new__(AffinityAnalysisService)
    service.CACHE_SCHEMA_VERSION = AffinityAnalysisService.CACHE_SCHEMA_VERSION
    return service


def test_outdated_affinity_cache_is_ignored(monkeypatch):
    db = create_settings_db()
    service = create_service(monkeypatch, db)

    db.execute(
        "INSERT INTO settings (key, value, updated_at) VALUES (?, ?, ?)",
        (
            "affinity_scores_1",
            """
            {
                "overall_score": 12.3,
                "overall_interpretation": "old",
                "conversation_id": 1,
                "analysis_timestamp": 100,
                "analysis_duration_ms": 10,
                "task_id": "affinity_1_old",
                "status": "completed",
                "cache_version": 1
            }
            """,
            100,
        ),
    )
    db.commit()

    result = service.get_scores(1)

    assert result is None


def test_version_constants_pinned_to_current_caliber():
    """口径 5 = 六维重组为四维 + LLM；缓存 13 = 结果 JSON 字段换名。"""
    assert AffinityAnalysisService.CACHE_SCHEMA_VERSION == 13
    assert AffinityAnalysisService.CALIBER_VERSION == 5


def test_saved_affinity_cache_round_trips_with_version(monkeypatch):
    db = create_settings_db()
    service = create_service(monkeypatch, db)

    result = AffinityAnalysisResult(
        overall_score=66.6,
        overall_interpretation="ok",
        emotional_resonance=DimensionScore(
            name="情感共鸣",
            score=20.0,
            weight=0.4,
            weighted_score=8.0,
            interpretation="x",
            sub_scores={"bidirectional_positive": 16.67},
            bonus_scores={"base_resonance_score": 16.67},
        ),
        risk_assessment={"highest_level": "留意", "signals": {}, "llm_evidence_available": False},
        conversation_id=1,
        analysis_timestamp=123,
        analysis_duration_ms=456,
        task_id="affinity_1_new",
        status="completed",
    )

    service._save_results(1, result)
    loaded = service.get_scores(1)

    assert loaded is not None
    assert loaded.cache_version == service.CACHE_SCHEMA_VERSION
    assert loaded.cache_updated_at > 0
    assert loaded.emotional_resonance is not None
    assert loaded.emotional_resonance.sub_scores["bidirectional_positive"] == 16.67
    assert loaded.emotional_resonance.bonus_scores["base_resonance_score"] == 16.67
    # 风险预警随同一 JSON 落库缓存
    assert loaded.risk_assessment == {"highest_level": "留意", "signals": {}, "llm_evidence_available": False}
