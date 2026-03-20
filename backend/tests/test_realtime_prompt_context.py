"""Prompt/context regression tests for realtime suggestion stack."""

import os
import sqlite3
import sys
import time


sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from app.services.realtime import feedback_rule_extractor
from app.services.realtime.llm_engine import LLMSuggestionEngine
from app.services.realtime.self_profiler import SelfProfiler


def test_llm_prompt_includes_historical_context_and_sentence_patterns():
    engine = LLMSuggestionEngine()
    prompt = engine._build_prompt(
        "negative_streak",
        "maintain",
        {
            "contact_profile": {
                "chat_style": "慢热但真诚",
                "personality_tags": ["理性", "克制"],
            },
            "self_profile": {
                "typing_style": "短句直给",
                "frequent_catchphrases": ["哈哈"],
                "sentence_patterns": ["哈哈[内容]", "就[事情]而已"],
                "do_and_donts": "每条建议控制在 8-14 字",
            },
            "emotion_summary": {
                "trend": "negative",
                "avg_polarity": -0.52,
                "window_size": 5,
                "recent_polarities": [-1, -1, 0, -1, -1],
            },
            "recent_messages": [
                {"sender_attr": "other", "content": "这两天有点累"},
                {"sender_attr": "self", "content": "那你早点休息"},
            ],
            "historical_context": {
                "profile": {
                    "chat_style": "偏理性",
                    "personality_tags": ["谨慎"],
                    "interests": ["摄影"],
                    "communication_tips": "不要太咄咄逼人",
                },
                "emotion_summary": {
                    "trend": "negative",
                    "avg_polarity": -0.4,
                    "avg_intensity": 0.6,
                },
                "chart_stats": {
                    "reply_rate": "0.75",
                    "positive_rate": "0.33",
                    "msg_ratio": "12:10",
                    "avg_reply_gap": 180,
                },
            },
        },
    )

    assert "常用句式模板" in prompt
    assert "本关系里的态度与角色" not in prompt
    assert "与对方共有的记忆常识" not in prompt
    assert "历史上下文补充" in prompt
    assert "平均回复时长=180 秒" in prompt
    assert prompt.index("【最近对话】") < prompt.index("【历史上下文补充（低权重）】")


def test_llm_prompt_keeps_more_than_eight_short_messages():
    engine = LLMSuggestionEngine()
    recent_messages = [
        {
            "id": i + 1,
            "timestamp": 100 + i,
            "sender_attr": "self" if i % 2 == 0 else "other",
            "content": f"短句{i}",
        }
        for i in range(12)
    ]

    prompt = engine._build_prompt(
        "topic_cooling",
        "maintain",
        {"recent_messages": recent_messages},
    )

    assert "短句0" in prompt
    assert "短句11" in prompt
    assert prompt.count("：短句") == 12


def test_llm_prompt_uses_char_guard_for_long_messages():
    engine = LLMSuggestionEngine()
    recent_messages = [
        {
            "id": i + 1,
            "timestamp": 100 + i,
            "sender_attr": "other" if i % 2 else "self",
            "content": f"{i}-" + ("很长" * 500),
        }
        for i in range(6)
    ]

    prompt = engine._build_prompt(
        "topic_cooling",
        "maintain",
        {"recent_messages": recent_messages},
    )

    assert "0-" not in prompt
    assert "5-" in prompt


def test_llm_prompt_compresses_older_messages_when_window_exceeds_threshold():
    engine = LLMSuggestionEngine()
    recent_messages = [
        {
            "id": i + 1,
            "timestamp": 100 + i,
            "sender_attr": "self" if i % 2 == 0 else "other",
            "content": f"消息{i}",
        }
        for i in range(40)
    ]

    prompt = engine._build_prompt(
        "topic_cooling",
        "maintain",
        {"recent_messages": recent_messages},
    )

    assert "更早的 20 条消息已折叠" in prompt
    assert "消息20" in prompt
    assert "消息39" in prompt


def test_llm_prompt_injects_memories_only_when_keyword_matches_recent_other_messages():
    engine = LLMSuggestionEngine()
    memories = [
        {"summary": "上次一起去迪士尼玩得很开心", "created_at": int(time.time()) - 3600},
        {"summary": "她提过最近工作压力很大", "created_at": int(time.time()) - 7200},
    ]

    prompt_without_match = engine._build_prompt(
        "positive_window",
        "intimate",
        {
            "recent_messages": [
                {"id": 1, "timestamp": 100, "sender_attr": "other", "content": "今天就正常下班"},
                {"id": 2, "timestamp": 101, "sender_attr": "self", "content": "那挺好"},
            ],
            "relevant_memories": memories,
        },
    )
    assert "被唤醒的历史记忆" not in prompt_without_match

    prompt_with_match = engine._build_prompt(
        "positive_window",
        "intimate",
        {
            "recent_messages": [
                {"id": 1, "timestamp": 100, "sender_attr": "other", "content": "突然想起上次去迪士尼还挺开心的"},
                {"id": 2, "timestamp": 101, "sender_attr": "self", "content": "我也记得"},
            ],
            "relevant_memories": memories,
        },
    )
    assert "被唤醒的历史记忆" in prompt_with_match
    assert "迪士尼" in prompt_with_match
    assert "工作压力" not in prompt_with_match


def test_llm_prompt_normalizes_desc_recent_messages_before_windowing():
    engine = LLMSuggestionEngine()
    recent_messages = [
        {"id": 4, "timestamp": 104, "sender_attr": "other", "content": "最新消息"},
        {"id": 3, "timestamp": 103, "sender_attr": "self", "content": "第三条"},
        {"id": 2, "timestamp": 102, "sender_attr": "other", "content": "第二条"},
        {"id": 1, "timestamp": 101, "sender_attr": "self", "content": "第一条"},
    ]

    prompt = engine._build_prompt(
        "topic_cooling",
        "maintain",
        {"recent_messages": recent_messages},
    )

    assert prompt.index("我：第一条") < prompt.index("对方：最新消息")


def test_llm_prompt_filters_content_rules_and_keeps_style_rules(monkeypatch):
    engine = LLMSuggestionEngine()

    monkeypatch.setattr(
        feedback_rule_extractor.FeedbackRuleExtractor,
        "get_active_rules",
        lambda self, display_name: [
            "用户倾向于用图片而非文字表达情绪或状态",
            "用户对不感兴趣的话题会直接转移话题",
            "用户拒绝闲聊时，会直接转移话题到学习内容",
            "用户倾向于用具体事实和数字回应，而非附和或调侃。",
        ],
    )

    prompt = engine._build_prompt(
        "topic_cooling",
        "maintain",
        {
            "display_name": "阿澄",
            "recent_messages": [
                {"id": 1, "timestamp": 100, "sender_attr": "other", "content": "最近在忙啥"},
                {"id": 2, "timestamp": 101, "sender_attr": "self", "content": "瞎忙"},
            ],
            "self_profile": {
                "typing_style": "短句直给",
                "frequent_catchphrases": ["hhh"],
                "sentence_patterns": ["[内容] hhh"],
                "attitude_and_role": "偏主动",
                "shared_memories": ["之前总聊高数"],
                "do_and_donts": "不要写太长",
            },
        },
    )

    assert "【表达偏好参考（仅影响措辞，不决定话题）】" in prompt
    assert "用户倾向于用图片而非文字表达情绪或状态" in prompt
    assert "用户倾向于用具体事实和数字回应，而非附和或调侃。" in prompt
    assert "用户对不感兴趣的话题会直接转移话题" not in prompt
    assert "用户拒绝闲聊时，会直接转移话题到学习内容" not in prompt
    assert "本关系里的态度与角色" not in prompt
    assert "与对方共有的记忆常识" not in prompt


def test_self_profiler_collect_features_and_parse_sentence_patterns():
    profiler = SelfProfiler()
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row

    conn.execute(
        """
        CREATE TABLE messages (
            conversation_id INTEGER,
            is_sender INTEGER,
            message_type INTEGER,
            content TEXT,
            timestamp INTEGER
        )
        """
    )
    conn.execute(
        """
        INSERT INTO messages (conversation_id, is_sender, message_type, content, timestamp)
        VALUES
            (1, 1, 1, '哈哈好呀', 100),
            (1, 1, 1, '就这样而已', 120),
            (1, 0, 1, '收到', 130)
        """
    )

    features = profiler._collect_features(conn, 1)
    assert features["user_msg_style"]["msg_count"] == 2
    assert features["user_msg_style"]["avg_chars_per_msg"] > 0

    parsed = profiler._parse_profile_json(
        """
        {
          "typing_style": "短句",
          "frequent_catchphrases": ["哈哈"],
          "attitude_and_role": "自然",
          "do_and_donts": "每条建议控制在 8-12 字"
        }
        """
    )
    assert parsed is not None
    assert parsed["sentence_patterns"] == []
