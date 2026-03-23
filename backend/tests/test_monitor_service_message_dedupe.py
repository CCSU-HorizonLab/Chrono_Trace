"""Targeted dedupe tests for realtime message polling."""

import json
import os
import sqlite3
import sys
from types import SimpleNamespace


sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.realtime.monitor_service import RealtimeMonitorService


class FakeMessageBuffer:
    def __init__(self):
        self.saved_messages = []

    def message_exists(self, message_hash: str) -> bool:
        return any(
            item.get("message_hash") == message_hash
            for item in self.saved_messages
        )

    def save_message(self, batch_id, talker_username, talker_display_name, message_data):
        self.saved_messages.append(
            {
                "batch_id": batch_id,
                "talker_username": talker_username,
                "talker_display_name": talker_display_name,
                **message_data,
            }
        )
        return True


class FakeSentimentService:
    def analyze(self, text):
        return {"polarity": 0, "intensity": 0}

    def analyze_and_cache(self, message_id, text):
        return {"message_id": message_id, "text": text}

    def is_ready(self):
        return True


class FakeWx:
    def __init__(self, messages):
        self.listener_profile = "wechat_405"
        self._messages = list(messages)

    def GetAllMessage(self):
        return list(self._messages)


def _make_service() -> tuple[RealtimeMonitorService, FakeMessageBuffer]:
    service = RealtimeMonitorService()
    buffer = FakeMessageBuffer()
    service.message_buffer = buffer
    service.sentiment_service = FakeSentimentService()
    service.emotion_tracker = None
    service.wx = SimpleNamespace(listener_profile="wechat_405")
    service.provider = None
    service.current_batch_id = "batch-1"
    service.current_talker = "friend_user"
    service.current_display_name = "Friend"
    service.is_monitoring = True
    service._listener_profile = "wechat_405"
    service._monitor_session_token = 1
    service.seen_hashes.clear()
    service.seen_message_keys.clear()
    service._last_known_ts = 0
    return service, buffer


def test_process_message_dedupes_same_runtime_id_even_if_timestamp_label_changes():
    service, buffer = _make_service()
    message = SimpleNamespace(
        hash="provider-hash-1",
        id="runtime-1",
        is_self=False,
        is_system=False,
        content="什么SL？",
        type="text",
        time="",
        CreateTime="",
        timestamp=0,
        visible_index=3,
    )

    service._process_message(message)
    assert len(buffer.saved_messages) == 1

    message.time = "12:48"
    service._process_message(message)

    assert len(buffer.saved_messages) == 1
    assert len(service.seen_message_keys) == 1


def test_process_message_dedupes_system_rows_without_provider_hash():
    service, buffer = _make_service()
    message = SimpleNamespace(
        hash="",
        id="runtime-system-1",
        is_self=False,
        is_system=True,
        content="昨天 14:25",
        type="system",
        time="昨天 14:25",
        CreateTime="昨天 14:25",
        timestamp=0,
        visible_index=0,
    )

    service._process_message(message)
    service._process_message(message)

    assert len(buffer.saved_messages) == 1
    saved = buffer.saved_messages[0]
    assert saved["sender_attr"] == "system"
    assert saved["message_hash"]


def test_seed_visible_message_baseline_skips_startup_history_processing():
    service, buffer = _make_service()
    message = SimpleNamespace(
        hash="provider-hash-2",
        id="runtime-startup-1",
        is_self=False,
        is_system=False,
        content="启动前已有消息",
        type="text",
        time="12:48",
        CreateTime="12:48",
        timestamp=0,
        visible_index=1,
    )
    service.wx = FakeWx([message])
    session_state = service._build_session_state(1)

    seeded = service._seed_visible_message_baseline(session_state)
    service._process_message(message, session_state=session_state)

    assert seeded == 1
    assert len(buffer.saved_messages) == 0


def test_process_message_ignores_stale_session_snapshot():
    service, buffer = _make_service()
    message = SimpleNamespace(
        hash="provider-hash-3",
        id="runtime-stale-1",
        is_self=False,
        is_system=False,
        content="过期会话消息",
        type="text",
        time="",
        CreateTime="",
        timestamp=0,
        visible_index=2,
    )
    stale_session = {
        "session_token": 0,
        "batch_id": "batch-1",
        "talker_username": "friend_user",
        "display_name": "Friend",
    }

    service._process_message(message, session_state=stale_session)

    assert len(buffer.saved_messages) == 0


def test_check_feedback_reserves_suggestion_once(monkeypatch):
    service, _buffer = _make_service()
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE realtime_suggestions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            batch_id TEXT NOT NULL,
            speeches TEXT NOT NULL,
            status TEXT DEFAULT 'pending',
            created_at INTEGER NOT NULL
        )
        """
    )
    conn.execute(
        """
        INSERT INTO realtime_suggestions (batch_id, speeches, status, created_at)
        VALUES (?, ?, 'pending', 9999999999)
        """,
        ("batch-1", json.dumps(["测试话术"], ensure_ascii=False)),
    )
    conn.commit()

    monkeypatch.setattr("app.db.connection.get_db", lambda: conn)

    calls = []

    class FakeExtractor:
        def compare_and_extract(self, ai_speeches, user_actual_message, display_name, suggestion_id=None):
            calls.append(
                {
                    "ai_speeches": ai_speeches,
                    "user_actual_message": user_actual_message,
                    "display_name": display_name,
                    "suggestion_id": suggestion_id,
                }
            )
            return None

    monkeypatch.setattr(
        "app.services.realtime.feedback_rule_extractor.FeedbackRuleExtractor",
        FakeExtractor,
    )

    started_targets = []

    class FakeThread:
        def __init__(self, target=None, daemon=None):
            self._target = target
            self.daemon = daemon

        def start(self):
            started_targets.append(self._target)

    monkeypatch.setattr("threading.Thread", FakeThread)

    session_state = service._build_session_state(1)
    service._check_feedback("第一条自发消息", session_state=session_state)
    service._check_feedback("第二条自发消息", session_state=session_state)

    row = conn.execute(
        "SELECT status FROM realtime_suggestions WHERE batch_id = ?",
        ("batch-1",),
    ).fetchone()

    assert row["status"] == "feedback_processing"
    assert len(started_targets) == 1
    assert calls == []
