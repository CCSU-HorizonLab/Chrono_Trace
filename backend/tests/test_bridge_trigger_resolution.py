"""Bridge-level tests for unified trigger resolution."""

import os
import json
import sqlite3
import sys
import threading
import time


sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.analysis.preprocessing_orchestrator import PreprocessedStatistics
from app.services.realtime.suggestion_engine import SuggestionResult
from app.services.realtime.suggestion_observer import (
    EVENT_SHOWN,
    ensure_observation_table,
    record_observation,
)
from app.webview.bridge import Bridge


class FakeMonitor:
    def __init__(self):
        self._suggestion_config = {"engine_type": "llm"}
        self.emotion_tracker = None
        self.current_batch_id = "manual-batch"
        self.current_display_name = None
        self.current_account_wxid = "wxid_test"


class FakeMonitorWithProfile(FakeMonitor):
    def __init__(self):
        super().__init__()
        self.current_display_name = "Grace."


class FakeEngine:
    def __init__(self):
        self.last_trigger_type = None
        self.last_context = None

    def generate(self, trigger_type, intent, context):
        self.last_trigger_type = trigger_type
        self.last_context = context
        return SuggestionResult(
            trigger_type=trigger_type,
            intent=intent,
            summary="测试建议",
            speeches=["测试话术"],
            severity="medium",
            confidence=0.9,
        )


class FakeStreamingEngine(FakeEngine):
    def generate(self, trigger_type, intent, context, stream_callback=None):
        if stream_callback:
            stream_callback({"type": "stage", "stage": "llm", "message": "模型生成中"})
            stream_callback({"type": "delta", "text": '{"summary":"流式', "channel": "content"})
            stream_callback({"type": "delta", "text": '建议"}', "channel": "content"})
        return super().generate(trigger_type, intent, context)


def _setup_db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE realtime_suggestions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            account_wxid TEXT NOT NULL,
            batch_id TEXT NOT NULL,
            trigger_type TEXT NOT NULL,
            intent TEXT DEFAULT 'maintain',
            severity TEXT DEFAULT 'medium',
            summary TEXT DEFAULT '',
            speeches TEXT NOT NULL,
            confidence REAL DEFAULT 1.0,
            status TEXT DEFAULT 'pending',
            engine_type TEXT DEFAULT 'llm',
            trigger_context TEXT,
            created_at INTEGER NOT NULL,
            read_at INTEGER,
            dismissed_at INTEGER,
            reply TEXT,
            thought_process TEXT
        )
        """
    )
    ensure_observation_table(conn)
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
                {"sender_attr": "other", "content": "看能不能去香港留学", "timestamp": 1},
            ]
        },
    )

    assert result["ok"] is True
    assert result["suggestion"]["trigger_type"] == "manual_request"
    assert engine.last_trigger_type == "manual_request"
    assert engine.last_context["account_wxid"] == "wxid_test"

    row = conn.execute(
        "SELECT trigger_type, trigger_context FROM realtime_suggestions LIMIT 1"
    ).fetchone()
    assert row["trigger_type"] == "manual_request"
    assert "manual_request" in row["trigger_context"]


def test_bridge_suggestion_stream_returns_events_and_final_result(monkeypatch):
    bridge = Bridge.__new__(Bridge)
    # partial Bridge：_prune_task_dicts 会触碰的任务字典与锁（__init__ 未运行）
    bridge._wechat_key_capture_lock = threading.Lock()
    bridge._wechat_key_capture_sessions = {}
    bridge._model_download_lock = threading.Lock()
    bridge._model_download_status = {}
    engine = FakeStreamingEngine()
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

    started = bridge.start_suggestion_stream(
        "maintain",
        {"recent_messages": [{"sender_attr": "other", "content": "最近有点累", "timestamp": 1}]},
    )

    assert started["ok"] is True
    deadline = time.time() + 2
    poll = {}
    while time.time() < deadline:
        poll = bridge.get_suggestion_stream(started["stream_id"], 0)
        if poll.get("done"):
            break
        time.sleep(0.02)

    assert poll["ok"] is True
    assert poll["done"] is True
    assert poll["result"]["ok"] is True
    assert poll["result"]["suggestion"]["summary"] == "测试建议"
    event_text = "".join(str(event.get("text") or "") for event in poll["events"])
    assert "流式建议" in event_text


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


def test_bridge_manual_generate_returns_twenty_recent_messages_for_display(monkeypatch):
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
                {"sender_attr": "self" if i % 2 == 0 else "other", "content": f"消息{i}", "timestamp": i}
                for i in range(30)
            ]
        },
    )

    assert result["ok"] is True
    assert len(result["context_used"]["recent_messages"]) == 20
    assert result["context_used"]["recent_messages"][0]["content"] == "消息10"
    assert result["context_used"]["recent_messages"][-1]["content"] == "消息29"


def test_bridge_manual_generate_injects_style_constraints_from_cached_history(monkeypatch):
    bridge = Bridge.__new__(Bridge)
    engine = FakeEngine()
    conn = _setup_db()

    monkeypatch.setattr(
        "app.services.realtime.monitor_service.RealtimeMonitorService",
        lambda: FakeMonitorWithProfile(),
    )
    monkeypatch.setattr(
        "app.services.realtime.suggestion_engine.SuggestionEngineFactory.create",
        lambda engine_type: engine,
    )
    monkeypatch.setattr("app.db.connection.get_db", lambda: conn)
    monkeypatch.setattr(
        "app.services.realtime.contact_profiler.ContactProfiler.get_profile",
        lambda self, display_name, account_wxid="": None,
    )
    monkeypatch.setattr(
        "app.services.realtime.self_profiler.SelfProfiler.get_profile",
        lambda self, display_name, account_wxid="": {
            "conversation_id": 7,
            "profile": {"typing_style": "短句"},
            "features_snapshot": {"user_msg_style": {"avg_chars_per_msg": 9.0}},
            "created_at": 0,
            "expires_at": 9999999999,
            "expired": False,
        },
    )
    monkeypatch.setattr(
        "app.services.realtime.historical_context.load_cached_style_inputs",
        lambda conversation_id: (
            PreprocessedStatistics(
                total_message_count=100,
                average_message_length=15.0,
                emoji_message_count=0,
                sender_initiated_count=20,
                contact_initiated_count=80,
                nickname_message_count=0,
                sender_nickname_message_count=0,
                contact_nickname_message_count=0,
            ),
            {
                "emotional_resonance": {"score": 30},
                "attitude_tendency": {"score": 35},
            },
        ),
    )

    result = bridge.generate_suggestion(
        "maintain",
        {
            "recent_messages": [
                {"sender_attr": "other", "content": "最近有点累", "timestamp": 1},
            ]
        },
    )

    assert result["ok"] is True
    style_constraints = engine.last_context["historical_context"]["style_constraints"]
    assert style_constraints["avg_msg_length"] == 9.0
    assert style_constraints["max_speech_length"] == 22
    assert style_constraints["communication_type"] == "reactive"
    assert style_constraints["emotional_style"] == "cold"


def test_bridge_get_pending_suggestions_marks_viewed(monkeypatch):
    bridge = Bridge.__new__(Bridge)
    bridge.settings = {"wechat_user_wxid": "wxid_test"}
    conn = _setup_db()
    conn.execute(
        """
        INSERT INTO realtime_suggestions
        (id, account_wxid, batch_id, trigger_type, intent, severity, summary, speeches, confidence, status, created_at)
        VALUES (1, 'wxid_test', 'batch-1', 'negative_streak', 'maintain', 'medium', '测试建议', ?, 0.9, 'pending', 1000)
        """,
        (json.dumps(["测试话术"], ensure_ascii=False),),
    )
    record_observation(
        conn,
        suggestion_id=1,
        account_wxid="wxid_test",
        event_type=EVENT_SHOWN,
        batch_id="batch-1",
        display_name="Grace.",
        trigger_type="negative_streak",
        created_at=1000,
    )
    conn.commit()

    monkeypatch.setattr("app.db.connection.get_db", lambda: conn)
    monkeypatch.setattr(
        "app.services.realtime.monitor_service.RealtimeMonitorService",
        lambda: FakeMonitor(),
    )

    result = bridge.get_pending_suggestions("batch-1")

    assert result["ok"] is True
    assert len(result["suggestions"]) == 1
    read_row = conn.execute("SELECT read_at FROM realtime_suggestions WHERE id = 1").fetchone()
    viewed_row = conn.execute(
        "SELECT event_type FROM suggestion_observations WHERE suggestion_id = 1 AND event_type = 'viewed'"
    ).fetchone()
    assert read_row["read_at"] is not None
    assert viewed_row["event_type"] == "viewed"


def test_bridge_dismiss_suggestion_records_observation(monkeypatch):
    bridge = Bridge.__new__(Bridge)
    bridge.settings = {"wechat_user_wxid": "wxid_test"}
    conn = _setup_db()
    conn.execute(
        """
        INSERT INTO realtime_suggestions
        (id, account_wxid, batch_id, trigger_type, intent, severity, summary, speeches, confidence, status, created_at)
        VALUES (2, 'wxid_test', 'batch-2', 'topic_cooling', 'maintain', 'medium', '测试建议', ?, 0.9, 'pending', 1000)
        """,
        (json.dumps(["测试话术"], ensure_ascii=False),),
    )
    record_observation(
        conn,
        suggestion_id=2,
        account_wxid="wxid_test",
        event_type=EVENT_SHOWN,
        batch_id="batch-2",
        display_name="妈",
        trigger_type="topic_cooling",
        created_at=1000,
    )
    conn.commit()

    monkeypatch.setattr("app.db.connection.get_db", lambda: conn)

    result = bridge.dismiss_suggestion(2)

    assert result["ok"] is True
    row = conn.execute(
        "SELECT status, dismissed_at FROM realtime_suggestions WHERE id = 2"
    ).fetchone()
    event_row = conn.execute(
        "SELECT event_type FROM suggestion_observations WHERE suggestion_id = 2 AND event_type = 'dismissed'"
    ).fetchone()
    assert row["status"] == "dismissed"
    assert row["dismissed_at"] is not None
    assert event_row["event_type"] == "dismissed"


def test_bridge_get_suggestion_metrics_returns_aggregates(monkeypatch):
    bridge = Bridge.__new__(Bridge)
    bridge.settings = {"wechat_user_wxid": "wxid_test"}
    conn = _setup_db()
    now = int(time.time())
    conn.execute(
        """
        INSERT INTO realtime_suggestions
        (id, account_wxid, batch_id, trigger_type, intent, severity, summary, speeches, confidence, status, created_at)
        VALUES
        (1, 'wxid_test', 'batch-1', 'negative_streak', 'maintain', 'medium', 'A', '[]', 1.0, 'pending', ?),
        (2, 'wxid_test', 'batch-2', 'topic_cooling', 'maintain', 'medium', 'B', '[]', 1.0, 'pending', ?)
        """
        ,
        (now - 20, now - 10),
    )
    record_observation(
        conn,
        suggestion_id=1,
        account_wxid="wxid_test",
        event_type=EVENT_SHOWN,
        batch_id="batch-1",
        display_name="Grace.",
        trigger_type="negative_streak",
        created_at=now - 20,
    )
    record_observation(
        conn,
        suggestion_id=1,
        account_wxid="wxid_test",
        event_type="adopted",
        similarity=0.9,
        selected_speech="A",
        actual_message="A",
        actual_message_type="text",
        created_at=now - 19,
    )
    record_observation(
        conn,
        suggestion_id=2,
        account_wxid="wxid_test",
        event_type=EVENT_SHOWN,
        batch_id="batch-2",
        display_name="妈",
        trigger_type="topic_cooling",
        created_at=now - 10,
    )
    record_observation(
        conn,
        suggestion_id=2,
        account_wxid="wxid_test",
        event_type="dismissed",
        created_at=now - 9,
    )
    conn.commit()

    monkeypatch.setattr("app.db.connection.get_db", lambda: conn)

    result = bridge.get_suggestion_metrics(7)

    assert result["ok"] is True
    assert result["metrics"]["shown_count"] == 2
    assert result["metrics"]["adopted_count"] == 1
    assert result["metrics"]["dismissed_count"] == 1
