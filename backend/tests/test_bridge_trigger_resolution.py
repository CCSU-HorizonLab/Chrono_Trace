"""Bridge-level tests for unified trigger resolution."""

import os
import sqlite3
import sys


sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.realtime.suggestion_engine import SuggestionResult
from app.webview.bridge import Bridge


class FakeMonitor:
    def __init__(self):
        self._suggestion_config = {"engine_type": "llm"}
        self.emotion_tracker = None
        self.current_batch_id = "manual-batch"
        self.current_display_name = None


class FakeEngine:
    def __init__(self):
        self.last_trigger_type = None

    def generate(self, trigger_type, intent, context):
        self.last_trigger_type = trigger_type
        return SuggestionResult(
            trigger_type=trigger_type,
            intent=intent,
            summary="测试建议",
            speeches=["测试话术"],
            severity="medium",
            confidence=0.9,
        )


def _setup_db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    return conn


def test_bridge_manual_generate_uses_manual_request_without_explicit_trigger(monkeypatch):
    bridge = Bridge.__new__(Bridge)
    engine = FakeEngine()
    conn = _setup_db()

    monkeypatch.setattr(
        "app.services.realtime.monitor_service.RealtimeMonitorService",
        lambda: FakeMonitor(),
    )
    monkeypatch.setattr(
        "app.services.realtime.suggestion_engine.SuggestionEngineFactory.create",
        lambda engine_type: engine,
    )
    monkeypatch.setattr("app.db.connection.get_db", lambda: conn)

    result = bridge.generate_suggestion(
        "maintain",
        {
            "recent_messages": [
                {"sender_attr": "other", "content": "看能不能去外地发展", "timestamp": 1},
            ]
        },
    )

    assert result["ok"] is True
    assert result["suggestion"]["trigger_type"] == "manual_request"
    assert engine.last_trigger_type == "manual_request"

    row = conn.execute(
        "SELECT trigger_type, trigger_context FROM realtime_suggestions LIMIT 1"
    ).fetchone()
    assert row["trigger_type"] == "manual_request"
    assert "manual_request" in row["trigger_context"]


def test_bridge_manual_generate_preserves_explicit_trigger(monkeypatch):
    bridge = Bridge.__new__(Bridge)
    engine = FakeEngine()
    conn = _setup_db()

    monkeypatch.setattr(
        "app.services.realtime.monitor_service.RealtimeMonitorService",
        lambda: FakeMonitor(),
    )
    monkeypatch.setattr(
        "app.services.realtime.suggestion_engine.SuggestionEngineFactory.create",
        lambda engine_type: engine,
    )
    monkeypatch.setattr("app.db.connection.get_db", lambda: conn)

    result = bridge.generate_suggestion(
        "maintain",
        {
            "trigger_type": "silence",
            "trigger_context": {"silent_seconds": 900},
            "recent_messages": [
                {"sender_attr": "other", "content": "还没回", "timestamp": 1},
            ],
        },
    )

    assert result["ok"] is True
    assert result["suggestion"]["trigger_type"] == "silence"
    assert engine.last_trigger_type == "silence"
