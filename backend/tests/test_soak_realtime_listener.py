"""Focused tests for realtime listener soak analysis helpers."""

import os
import sys


sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from backend.scripts.soak_realtime_listener import analyze_batch_messages, summarize_cycle


def test_analyze_batch_messages_reports_duplicate_hashes_and_runtime_ids():
    result = analyze_batch_messages(
        [
            {
                "sender_attr": "friend",
                "message_type": "text",
                "content": "什么SL？",
                "timestamp": 100,
                "runtime_id": "rt-1",
                "message_hash": "hash-1",
            },
            {
                "sender_attr": "friend",
                "message_type": "text",
                "content": "什么SL？",
                "timestamp": 100,
                "runtime_id": "rt-1",
                "message_hash": "hash-1",
            },
        ]
    )

    assert result["total_messages"] == 2
    assert result["duplicate_hashes"] == {"hash-1": 2}
    assert result["duplicate_runtime_ids"] == {"rt-1": 2}
    assert result["sender_counts"]["friend"] == 2


def test_summarize_cycle_flags_provider_mismatch_and_duplicate_failure():
    summary = summarize_cycle(
        {
            "statuses": [
                {
                    "provider": "wxauto",
                    "chat_ready": True,
                    "chat_error": "",
                    "polling_alive": True,
                }
            ],
            "batch_analysis": {
                "total_messages": 2,
                "duplicate_hashes": {"hash-1": 2},
                "duplicate_runtime_ids": {},
                "duplicate_semantics": {},
            },
            "errors": [],
        },
        requested_backend="native_uia",
    )

    assert summary["ok"] is False
    assert summary["provider_mismatch"] is True
    assert summary["duplicate_hash_count"] == 1
