"""Prompt/context regression tests for realtime suggestion stack."""

import json
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


def test_llm_prompt_dedupes_repeated_same_sender_messages_before_rendering():
    engine = LLMSuggestionEngine()
    recent_messages = [
        {
            "id": 3,
            "timestamp": 103,
            "sender_attr": "self",
            "content": "怎么了",
            "message_type": "text",
        },
        {
            "id": 2,
            "timestamp": 102,
            "runtime_id": "runtime-2",
            "sender_attr": "friend",
            "content": "就拽就拽",
            "message_type": "text",
        },
        {
            "id": 1,
            "timestamp": 102,
            "runtime_id": "runtime-1",
            "sender_attr": "friend",
            "content": "就拽就拽",
            "message_type": "text",
        },
    ]

    prompt = engine._build_prompt(
        "topic_cooling",
        "maintain",
        {"recent_messages": recent_messages},
    )

    assert prompt.count("就拽就拽") == 1


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


def test_llm_prompt_uses_refined_emotion_shift_description():
    engine = LLMSuggestionEngine()

    prompt = engine._build_prompt(
        "emotion_shift",
        "maintain",
        {
            "recent_messages": [
                {"id": 1, "timestamp": 100, "sender_attr": "other", "content": "刚刚还挺顺的"},
                {"id": 2, "timestamp": 101, "sender_attr": "other", "content": "这下突然有点烦"},
            ],
        },
    )

    assert "对方近期情绪明显下坠，且最新表达偏负面" in prompt
    assert "对方情绪发生了突变，从正面转为负面" not in prompt


def test_llm_prompt_supports_manual_request_trigger_description():
    engine = LLMSuggestionEngine()

    prompt = engine._build_prompt(
        "manual_request",
        "maintain",
        {
            "recent_messages": [
                {"id": 1, "timestamp": 100, "sender_attr": "other", "content": "最近有点纠结"},
                {"id": 2, "timestamp": 101, "sender_attr": "self", "content": "该怎么回"},
            ],
        },
    )

    assert "用户主动请求建议，需要基于当前上下文给出回复思路" in prompt
    assert "必须严格只输出 JSON" in prompt


def test_llm_manual_request_direct_reply_prompt_avoids_suggestion_card():
    engine = LLMSuggestionEngine()

    prompt = engine._build_prompt(
        "manual_request",
        "maintain",
        {
            "contact_profile": {
                "personality_tags": ["亲密", "幽默"],
                "chat_style": "爱叫宝贝",
            },
            "self_profile": {
                "typing_style": "短句",
                "frequent_catchphrases": ["宝贝"],
                "sentence_patterns": ["宝贝[内容]"],
                "do_and_donts": "多用亲昵称呼",
            },
            "user_context": [
                {"role": "user", "content": "测试 回复功能 请回复我"},
            ],
        },
    )

    assert "优先在 `reply` 字段直接回应用户" in prompt
    assert "不要生成建议卡片" in prompt
    assert "自然、简洁的助手口吻" in prompt
    assert "【对方画像（低权重参考）】" not in prompt
    assert "【用户本体语言风格参考（仅影响措辞）】" not in prompt


def test_llm_manual_request_advice_prompt_still_requests_sendable_speeches():
    engine = LLMSuggestionEngine()

    prompt = engine._build_prompt(
        "manual_request",
        "maintain",
        {
            "user_context": [
                {"role": "user", "content": "她刚刚这么说了，我该怎么回？"},
            ],
        },
    )

    assert "请基于当前上下文给出可发送的话术" in prompt
    assert "不要生成建议卡片" not in prompt


def test_llm_parse_response_extracts_json_from_wrapped_text():
    engine = LLMSuggestionEngine()

    result = engine._parse_response(
        '好的，下面是结果：{"reply":"","thought_process":"对方还在正常推进话题。","summary":"顺着新话题接一句。","speeches":["那你更倾向哪个？"]}',
        "manual_request",
        "maintain",
    )

    assert result is not None
    assert result.summary == "顺着新话题接一句。"
    assert result.speeches == ["那你更倾向哪个？"]


def test_llm_extract_message_text_falls_back_to_reasoning_content():
    engine = LLMSuggestionEngine()

    content = engine._extract_message_text(
        {
            "content": "",
            "reasoning_content": '{"reply":"","thought_process":"测试","summary":"测试摘要","speeches":["测试话术"]}',
        }
    )

    assert '"summary":"测试摘要"' in content


def test_llm_parse_response_falls_back_to_reasoning_text_with_speeches():
    engine = LLMSuggestionEngine()

    result = engine._parse_response(
        """
首先，理解任务：这是用户主动请求“开启话题”。
话术例子：
- 宝贝在干嘛呢～
- 想你了嘿嘿
- 今天有什么好玩的事吗
输出必须是纯JSON。
        """,
        "manual_request",
        "maintain",
    )

    assert result is not None
    assert result.summary == "给出几条可直接发送的开启话题话术"
    assert result.speeches == ["宝贝在干嘛呢～", "想你了嘿嘿", "今天有什么好玩的事吗"]
    assert result.thought_process is not None


def test_llm_parse_response_rejects_placeholder_json_and_uses_reasoning_fallback():
    engine = LLMSuggestionEngine()

    result = engine._parse_response(
        """
{
  "reply": "（如果用户有提问或反馈，在这里直接回应用户的话；如果没有用户输入，此字段留空字符串）",
  "thought_process": "用一两句话简述你是如何推断对方的情感以及为什么提供以下建议的",
  "summary": "...",
  "speeches": ["话术1", "话术2", "话术3"]
}

话术例子：
- 那你最近又在玩啥
- 某款游戏2好玩吗
- 你现在打到哪了
        """,
        "manual_request",
        "maintain",
    )

    assert result is not None
    assert result.summary == "已从思考输出中提取可直接发送的话术"
    assert result.speeches == ["那你最近又在玩啥", "某款游戏2好玩吗", "你现在打到哪了"]


def test_llm_parse_response_rejects_meta_prompt_rules_as_speeches():
    engine = LLMSuggestionEngine()

    result = engine._parse_response(
        """
{
  "reply": "",
  "thought_process": "thought_process: 基于用户输入是主动请求建议来开启一个特定话题",
  "summary": "话术应该关于开启某款游戏2SL mod的话题。",
  "speeches": [
    "**千人千面，消除机味**：我必须彻底抛开AI常用的客套话等",
    "**完美模仿用户风格**：话术必须模仿用户本体克隆画像",
    "**身份区分**：\"我\"是用户本人，对方是聊天对象"
  ]
}
        """,
        "manual_request",
        "maintain",
    )

    assert result is None


def test_llm_generate_repairs_meta_response_before_returning_result(monkeypatch):
    engine = LLMSuggestionEngine()

    monkeypatch.setattr(
        engine,
        "_get_active_model",
        lambda: {
            "name": "DeepSeek R1",
            "provider": "deepseek",
            "model_id": "deepseek-reasoner",
            "api_base_url": "https://api.deepseek.com/v1",
            "api_key": "token",
            "max_tokens": 512,
            "temperature": 0.7,
        },
    )
    monkeypatch.setattr(engine, "_build_prompt", lambda trigger_type, intent, context: "prompt")
    monkeypatch.setattr(
        engine,
        "_generate_reasoning_analysis",
        lambda model_config, user_prompt: "对方在聊游戏模组，顺着兴趣切进去更自然。\n- 你那个SL mod具体改了啥",
    )
    monkeypatch.setattr(
        engine,
        "_format_reasoning_result",
        lambda model_config, user_prompt, analysis_text: """
{"reply":"","thought_process":"对方在聊游戏模组，顺着兴趣切进去更自然。","summary":"顺着某款游戏2 mod继续聊。","speeches":["你那个SL mod具体改了啥","这个mod你是在哪下的","你现在玩起来手感咋样"]}        
        """,
    )
    monkeypatch.setattr(
        engine,
        "_repair_response",
        lambda model_config, user_prompt, raw_response: """
{"reply":"","thought_process":"对方在聊游戏模组，顺着兴趣切进去更自然。","summary":"顺着某款游戏2 mod继续聊。","speeches":["你那个SL mod具体改了啥","这个mod你是在哪下的","你现在玩起来手感咋样"]}        
        """,
    )

    result = engine.generate("manual_request", "maintain", {})

    assert result.summary == "顺着某款游戏2 mod继续聊。"
    assert result.speeches == ["你那个SL mod具体改了啥", "这个mod你是在哪下的", "你现在玩起来手感咋样"]


def test_llm_parse_response_sanitizes_newlines_inside_json_strings():
    engine = LLMSuggestionEngine()

    result = engine._parse_response(
        '{\n'
        '  "reply": "",\n'
        '  "thought_process": "对方性格幽默亲密且常聊游戏，\n顺着游戏聊更自然。",\n'
        '  "summary": "顺着游戏话题继续聊。",\n'
        '  "speeches": ["你最近又在打哪个mod"]\n'
        '}',
        "manual_request",
        "maintain",
    )

    assert result is not None
    assert result.summary == "顺着游戏话题继续聊。"
    assert result.speeches == ["你最近又在打哪个mod"]


def test_llm_call_api_enables_json_mode_for_supported_provider(monkeypatch):
    engine = LLMSuggestionEngine()
    captured = {}

    monkeypatch.setattr(engine, "_validate_model_id", lambda model_id, base_url, api_key="": model_id)

    class DummyResponse:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return json.dumps(
                {
                    "choices": [
                        {
                            "message": {
                                "content": '{"reply":"","thought_process":"ok","summary":"ok","speeches":["hi"]}'
                            }
                        }
                    ],
                    "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
                }
            ).encode("utf-8")

    def fake_urlopen(req, timeout=0):
        captured["payload"] = json.loads(req.data.decode("utf-8"))
        return DummyResponse()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    engine._call_api(
        {
            "provider": "deepseek",
            "api_base_url": "https://api.deepseek.com/v1",
            "api_key": "token",
            "model_id": "deepseek-chat",
            "max_tokens": 256,
            "temperature": 0.3,
        },
        "test prompt",
    )

    assert captured["payload"]["response_format"] == {"type": "json_object"}


def test_llm_call_api_boosts_reasoner_max_tokens(monkeypatch):
    engine = LLMSuggestionEngine()
    captured = {}

    monkeypatch.setattr(engine, "_validate_model_id", lambda model_id, base_url, api_key="": model_id)

    class DummyResponse:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return json.dumps(
                {
                    "choices": [
                        {
                            "message": {
                                "content": '{"reply":"","thought_process":"ok","summary":"ok","speeches":["hi"]}'
                            }
                        }
                    ],
                    "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
                }
            ).encode("utf-8")

    def fake_urlopen(req, timeout=0):
        captured["payload"] = json.loads(req.data.decode("utf-8"))
        return DummyResponse()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    engine._call_api(
        {
            "provider": "deepseek",
            "api_base_url": "https://api.deepseek.com/v1",
            "api_key": "token",
            "model_id": "deepseek-reasoner",
            "max_tokens": 256,
            "temperature": 0.3,
        },
        "test prompt",
    )

    assert captured["payload"]["max_tokens"] >= 1024


def test_generate_quick_prompts_uses_dedicated_prompt_and_disables_json_object(monkeypatch):
    engine = LLMSuggestionEngine()
    captured = {}

    monkeypatch.setattr(
        engine,
        "_get_active_model",
        lambda: {
            "provider": "deepseek",
            "api_base_url": "https://api.deepseek.com/v1",
            "api_key": "token",
            "model_id": "deepseek-reasoner",
            "max_tokens": 256,
            "temperature": 0.7,
        },
    )
    monkeypatch.setattr(engine, "_resolve_formatter_model_config", lambda config: {**config, "model_id": "deepseek-chat"})

    def fake_call(model_config, messages, **kwargs):
        captured["model_id"] = model_config["model_id"]
        captured["messages"] = messages
        captured["kwargs"] = kwargs
        return '["继续游戏","表达关心","顺着话题","转移话题"]'

    monkeypatch.setattr(engine, "_call_api_with_messages", fake_call)

    prompts = engine.generate_quick_prompts(
        {
            "recent_messages": [
                {"id": 1, "timestamp": 100, "sender_attr": "self", "content": "宝宝"},
                {"id": 2, "timestamp": 101, "sender_attr": "self", "content": "还爬塔吗？"},
            ]
        }
    )

    assert captured["model_id"] == "deepseek-chat"
    assert captured["messages"][0]["content"].startswith("你是一个聊天联想词生成器")
    assert captured["kwargs"]["use_json_mode"] is False
    assert prompts == ["继续游戏", "表达关心", "顺着话题", "转移话题"]


def test_generate_quick_prompts_extracts_array_from_wrapped_text(monkeypatch):
    engine = LLMSuggestionEngine()

    monkeypatch.setattr(
        engine,
        "_get_active_model",
        lambda: {
            "provider": "deepseek",
            "api_base_url": "https://api.deepseek.com/v1",
            "api_key": "token",
            "model_id": "deepseek-chat",
            "max_tokens": 256,
            "temperature": 0.7,
        },
    )
    monkeypatch.setattr(
        engine,
        "_call_quick_prompts_api",
        lambda model_config, prompt: '先分析一下方向，然后给结果：["继续游戏","表达关心","顺着话题","转移话题"]',
    )

    prompts = engine.generate_quick_prompts({"recent_messages": []})

    assert prompts == ["继续游戏", "表达关心", "顺着话题", "转移话题"]


def test_generate_quick_prompts_salvages_speeches_array_from_object_response(monkeypatch):
    engine = LLMSuggestionEngine()

    monkeypatch.setattr(
        engine,
        "_get_active_model",
        lambda: {
            "provider": "deepseek",
            "api_base_url": "https://api.deepseek.com/v1",
            "api_key": "token",
            "model_id": "deepseek-chat",
            "max_tokens": 256,
            "temperature": 0.7,
        },
    )
    monkeypatch.setattr(
        engine,
        "_call_quick_prompts_api",
        lambda model_config, prompt: json.dumps(
            {
                "reply": "",
                "thought_process": "test",
                "summary": "",
                "speeches": ["继续游戏", "表达关心", "顺着话题", "转移话题"],
            },
            ensure_ascii=False,
        ),
    )

    prompts = engine.generate_quick_prompts({"recent_messages": []})

    assert prompts == ["继续游戏", "表达关心", "顺着话题", "转移话题"]


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
