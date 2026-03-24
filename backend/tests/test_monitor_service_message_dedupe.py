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


def test_process_message_dedupes_same_runtime_id_when_time_anchor_is_stable():
    service, buffer = _make_service()
    message = SimpleNamespace(
        hash="provider-hash-1",
        id="runtime-1",
        is_self=False,
        is_system=False,
        content="什么SL？",
        type="text",
        time="12:48",
        CreateTime="12:48",
        timestamp=0,
        visible_index=3,
    )

    service._process_message(message)
    assert len(buffer.saved_messages) == 1

    message.hash = "provider-hash-1b"
    service._process_message(message)

    assert len(buffer.saved_messages) == 1
    assert len(service.seen_message_keys) == 1


def test_process_message_dedupes_same_runtime_id_even_if_sender_attr_flips():
    service, buffer = _make_service()
    message = SimpleNamespace(
        hash="provider-hash-role-flip",
        id="runtime-role-flip-1",
        is_self=False,
        is_system=False,
        content="就拽就拽",
        type="text",
        time="",
        CreateTime="",
        timestamp=0,
        visible_index=5,
    )

    service._process_message(message)
    assert len(buffer.saved_messages) == 1
    assert buffer.saved_messages[0]["sender_attr"] == "friend"

    message.is_self = True
    service._process_message(message)

    assert len(buffer.saved_messages) == 1
    assert len(service.seen_message_keys) == 1


def test_process_message_dedupes_same_visible_message_even_if_runtime_id_changes():
    service, buffer = _make_service()
    first_message = SimpleNamespace(
        hash="provider-hash-runtime-1",
        id="runtime-a",
        is_self=False,
        is_system=False,
        content="我在你旁边扯你说对不起",
        type="text",
        time="12:48",
        CreateTime="12:48",
        timestamp=0,
        visible_index=5,
    )
    second_message = SimpleNamespace(
        hash="provider-hash-runtime-2",
        id="runtime-b",
        is_self=False,
        is_system=False,
        content="我在你旁边扯你说对不起",
        type="text",
        time="12:48",
        CreateTime="12:48",
        timestamp=0,
        visible_index=5,
    )

    service._process_message(first_message)
    service._process_message(second_message)

    assert len(buffer.saved_messages) == 1
    assert len(service.seen_message_keys) == 1


def test_visible_message_signature_uses_edge_window_not_just_single_top_item():
    service, _buffer = _make_service()
    first = SimpleNamespace(hash="", id="1", is_self=False, type="text", content="顶部", time="")
    second_a = SimpleNamespace(hash="", id="2a", is_self=False, type="text", content="第二条A", time="")
    second_b = SimpleNamespace(hash="", id="2b", is_self=False, type="text", content="第二条B", time="")

    signature_a = service._visible_message_signature([first, second_a], from_tail=False, size=2)
    signature_b = service._visible_message_signature([first, second_b], from_tail=False, size=2)

    assert signature_a != signature_b


def test_checkpoint_match_prefers_runtime_id_for_short_anchor_text():
    service, _buffer = _make_service()
    checkpoint = {
        "last_runtime_id": "runtime-anchor-1",
        "last_message_preview": "怎么了",
        "last_message_timestamp": 1234567890,
    }
    message = SimpleNamespace(
        id="runtime-anchor-1",
        content="怎么了",
    )

    reason = service._checkpoint_match_reason(checkpoint, message, resolved_timestamp=0)

    assert reason == "runtime_id_exact"


def test_checkpoint_match_uses_sliding_context_window_for_duplicate_short_text():
    service, _buffer = _make_service()
    checkpoint = {
        "last_runtime_id": "",
        "last_message_preview": "怎么了",
        "last_message_timestamp": 1774273245,
        "last_message_context": {
            "before": [
                "撅嘴",
                "你都没看见！ 也没听见",
                "狗屎!",
                "就拽就拽、引用 稽塔 的消息 : 你刚刚带个耳机拽的要死",
            ],
            "after": ["system:昨天 21:20"],
        },
    }

    current_visible_messages = [
        SimpleNamespace(id="1", is_self=True, is_system=False, type="text", content="你都没看见！ 也没听见"),
        SimpleNamespace(id="2", is_self=True, is_system=False, type="text", content="狗屎!"),
        SimpleNamespace(id="3", is_self=False, is_system=False, type="text", content="就拽就拽、引用 稽塔 的消息 : 你刚刚带个耳机拽的要死"),
        SimpleNamespace(id="4", is_self=False, is_system=False, type="text", content="怎么了"),
        SimpleNamespace(id="5", is_self=False, is_system=True, type="system", content="21:20"),
    ]
    older_visible_messages = [
        SimpleNamespace(id="a1", is_self=True, is_system=False, type="text", content="啥也听不见"),
        SimpleNamespace(id="a2", is_self=True, is_system=False, type="text", content="我在你旁边扯你说对不起"),
        SimpleNamespace(id="a3", is_self=True, is_system=False, type="text", content="撅嘴"),
        SimpleNamespace(id="a4", is_self=True, is_system=False, type="text", content="你都没看见！ 也没听见"),
        SimpleNamespace(id="a5", is_self=True, is_system=False, type="text", content="狗屎!"),
        SimpleNamespace(id="a6", is_self=False, is_system=False, type="text", content="就拽就拽、引用 稽塔 的消息 : 你刚刚带个耳机拽的要死"),
        SimpleNamespace(id="a7", is_self=False, is_system=False, type="text", content="怎么了"),
        SimpleNamespace(id="a8", is_self=False, is_system=True, type="system", content="昨天 20:53"),
        SimpleNamespace(id="a9", is_self=True, is_system=False, type="text", content="狗屎!"),
        SimpleNamespace(id="a10", is_self=True, is_system=False, type="text", content="那你自己修"),
        SimpleNamespace(id="a11", is_self=False, is_system=False, type="text", content="没有问题了！"),
    ]

    current_reason = service._checkpoint_match_reason(
        checkpoint,
        current_visible_messages[3],
        resolved_timestamp=0,
        visible_messages=current_visible_messages,
        visible_index=3,
    )
    older_reason = service._checkpoint_match_reason(
        checkpoint,
        older_visible_messages[6],
        resolved_timestamp=0,
        visible_messages=older_visible_messages,
        visible_index=6,
    )

    assert current_reason == "context_window"
    assert older_reason is None


def test_backfill_scroll_step_uses_faster_stride_when_anchor_context_is_far():
    service, _buffer = _make_service()
    checkpoint = {
        "last_message_preview": "怎么了",
        "last_message_context": {
            "before": [
                "撅嘴",
                "你都没看见！ 也没听见",
                "狗屎!",
            ],
            "after": ["system:昨天 21:20"],
        },
    }
    visible_messages = [
        SimpleNamespace(id="1", is_self=True, is_system=False, type="text", content="完全无关1"),
        SimpleNamespace(id="2", is_self=False, is_system=False, type="text", content="完全无关2"),
        SimpleNamespace(id="3", is_self=True, is_system=False, type="text", content="完全无关3"),
    ]

    step = service._choose_backfill_scroll_step(
        checkpoint=checkpoint,
        visible_messages=visible_messages,
        round_index=1,
        default_wheel_times=3,
    )

    assert step == 6


def test_backfill_scroll_step_uses_large_stride_when_visible_time_is_far_later_than_checkpoint():
    service, _buffer = _make_service()
    checkpoint = {
        "last_message_preview": "怎么了",
        "last_message_timestamp": 1774273245,
        "last_message_context": {
            "before": ["狗屎!"],
            "after": ["system:昨天 21:20"],
        },
    }
    visible_messages = [
        SimpleNamespace(id="1", is_self=False, is_system=True, type="system", content="13:16"),
        SimpleNamespace(id="2", is_self=True, is_system=False, type="text", content="要能量吗"),
        SimpleNamespace(id="3", is_self=False, is_system=False, type="text", content="不用"),
    ]

    step = service._choose_backfill_scroll_step(
        checkpoint=checkpoint,
        visible_messages=visible_messages,
        round_index=2,
        default_wheel_times=3,
    )

    assert step == 8


def test_backfill_scroll_step_slows_down_when_anchor_window_enters_view():
    service, _buffer = _make_service()
    checkpoint = {
        "last_message_preview": "怎么了",
        "last_message_context": {
            "before": [
                "撅嘴",
                "你都没看见！ 也没听见",
                "狗屎!",
                "就拽就拽、引用 稽塔 的消息 : 你刚刚带个耳机拽的要死",
            ],
            "after": ["system:昨天 21:20"],
        },
    }
    visible_messages = [
        SimpleNamespace(id="1", is_self=True, is_system=False, type="text", content="你都没看见！ 也没听见"),
        SimpleNamespace(id="2", is_self=True, is_system=False, type="text", content="狗屎!"),
        SimpleNamespace(id="3", is_self=False, is_system=False, type="text", content="就拽就拽、引用 稽塔 的消息 : 你刚刚带个耳机拽的要死"),
        SimpleNamespace(id="4", is_self=False, is_system=False, type="text", content="怎么了"),
        SimpleNamespace(id="5", is_self=False, is_system=True, type="system", content="21:20"),
    ]

    step = service._choose_backfill_scroll_step(
        checkpoint=checkpoint,
        visible_messages=visible_messages,
        round_index=6,
        default_wheel_times=3,
    )

    assert step == 1


def test_backfill_scroll_direction_can_correct_if_viewport_is_older_than_checkpoint():
    service, _buffer = _make_service()

    direction = service._choose_backfill_scroll_direction(
        proximity={"preview_visible": False, "focus_hits": 0},
        time_gap_seconds=-(20 * 60),
    )

    assert direction == "down"


def test_backfill_scroll_repeats_batches_more_small_scrolls_when_time_gap_is_large():
    service, _buffer = _make_service()

    repeats = service._choose_backfill_scroll_repeats(
        proximity={"preview_visible": False, "focus_hits": 0},
        time_gap_seconds=13 * 3600,
    )

    assert repeats == 3


def test_backfill_scroll_repeats_stays_single_step_near_anchor():
    service, _buffer = _make_service()

    repeats = service._choose_backfill_scroll_repeats(
        proximity={"preview_visible": True, "focus_hits": 2},
        time_gap_seconds=13 * 3600,
    )

    assert repeats == 1


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
