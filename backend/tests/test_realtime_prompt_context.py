"""Prompt/context regression tests for realtime suggestion stack."""

import os
import sqlite3
import sys


sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

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
    assert "历史联系人画像" in prompt
    assert "会话统计特征" in prompt
    assert "平均回复时长: 180 秒" in prompt


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
