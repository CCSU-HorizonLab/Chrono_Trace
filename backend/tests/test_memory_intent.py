"""Regression samples for memory intent driven RAG triggering."""

import os
import sys


sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.realtime.memory_intent import detect_memory_intent
from scripts.evaluate_memory_intent_samples import evaluate


def test_memory_intent_fixed_acceptance_samples():
    samples = [
        ("她上次说的什么流派我不知道", "memory_request", True, "reply"),
        ("她说的那个流派是啥", "memory_request", True, "reply"),
        ("她说过喜欢拿铁吗", "memory_request", True, "reply"),
        ("找一下上次那家店我们吃的啥", "memory_request", True, "reply"),
        ("这个人现在适合开玩笑吗", "relationship_context", True, "reply"),
        ("你好，测试一下", "none", False, "reply"),
        ("给我回一句", "none", False, "suggestion"),
        ("她上次说的游戏是啥，但索引无结果", "memory_request", True, "reply"),
        ("我们之前吃的那家店是啥", "memory_request", True, "reply"),
        ("按我们之前的关系怎么回比较好", "relationship_context", True, "suggestion"),
        ("历史记录 我说错了 你找找RAG文档里的历史记录", "memory_request", True, "reply"),
        ("那你看看文档里有没有合适的聊天记录 比如杀戮尖塔啥的", "memory_request", True, "reply"),
    ]

    for text, mode, should_retrieve, shape in samples:
        intent = detect_memory_intent({"user_context": text})
        assert shape in {"reply", "suggestion"}
        assert intent.mode == mode
        assert intent.should_retrieve is should_retrieve
        if should_retrieve:
            assert intent.query


def test_memory_intent_inherits_recent_memory_followup():
    intent = detect_memory_intent(
        {
            "conversation_id": 1,
            "user_context": [
                {"role": "user", "content": "找一下上次她说杀戮尖塔的记录"},
                {"role": "assistant", "content": "查到她提过杀戮尖塔。"},
                {"role": "user", "content": "那给我个相关建议"},
            ],
        }
    )

    assert intent.mode == "memory_request"
    assert intent.should_retrieve is True
    assert "杀戮尖塔" in intent.query
    assert intent.reason == "continued_recent_memory_context"


def test_memory_intent_does_not_inherit_after_topic_switch():
    intent = detect_memory_intent(
        {
            "conversation_id": 1,
            "user_context": [
                {"role": "user", "content": "找一下上次她说杀戮尖塔的记录"},
                {"role": "assistant", "content": "查到她提过杀戮尖塔。"},
                {"role": "user", "content": "换个话题，今天吃什么"},
            ],
        }
    )

    assert intent.mode == "none"
    assert intent.should_retrieve is False


def test_memory_intent_uses_prototype_signal_for_implicit_lookup():
    intent = detect_memory_intent({"user_context": "你还记得那家店吗"})
    assert intent.mode == "memory_request"
    assert intent.should_retrieve is True
    assert intent.reason == "memory_prototype_signal"


def test_memory_intent_history_does_not_cross_contact():
    intent = detect_memory_intent(
        {
            "conversation_id": 2,
            "user_context": "那给我个相关建议",
            "memory_intent_history": [
                {
                    "conversation_id": 1,
                    "mode": "memory_request",
                    "confidence": 0.9,
                    "query": "杀戮尖塔",
                }
            ],
        }
    )

    assert intent.mode == "none"
    assert intent.should_retrieve is False


def test_memory_intent_evaluation_report_has_no_fixed_sample_mismatches():
    samples = [
        {"id": "lookup", "user_context": "你还记得那家店吗", "expected_mode": "memory_request", "expected_retrieve": True, "no_hit_honest": True},
        {"id": "chat", "user_context": "你好，测试一下", "expected_mode": "none", "expected_retrieve": False, "no_hit_honest": True},
    ]
    report = evaluate(samples)
    assert report["mismatches"] == []
    assert report["recall"] == 1.0
    assert report["false_positive_rate"] == 0.0
