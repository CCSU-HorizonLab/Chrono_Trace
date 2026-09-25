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
from app.services.realtime.style_constraints import StyleConstraints


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
                "style_constraints": {
                    "emoji_density": 0.0,
                    "avg_msg_length": 8.5,
                    "max_speech_length": 21,
                    "communication_type": "reactive",
                    "emotional_style": "cold",
                    "nickname_usage": False,
                },
            },
        },
    )

    assert "常用句式模板" in prompt
    assert "在策略正确的前提下尽量贴近" in prompt
    assert "至少 2 条沿用" not in prompt
    assert "本关系里的态度与角色" not in prompt
    assert "与对方共有的记忆常识" not in prompt
    assert "【量化风格硬约束（必须遵守）】" in prompt
    assert "每条话术严禁超过 21 字" in prompt
    assert "话术中严禁出现任何 emoji" in prompt
    assert "历史上下文补充" in prompt
    assert "平均回复时长=180 秒" in prompt
    assert "越新的消息权重越高" in prompt
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


def test_llm_prompt_without_history_uses_default_style_fallback():
    engine = LLMSuggestionEngine()

    prompt = engine._build_prompt(
        "topic_cooling",
        "maintain",
        {
            "recent_messages": [
                {"sender_attr": "other", "content": "最近有点忙", "timestamp": 100},
                {"sender_attr": "self", "content": "那先忙", "timestamp": 101},
            ],
        },
    )

    assert "【用户风格缺省约束】" in prompt
    assert "默认每条话术不超过 15 字" in prompt
    assert "禁止 emoji、连续感叹号、连续问号" in prompt


def test_llm_prompt_uses_char_guard_for_long_messages():
    engine = LLMSuggestionEngine()
    recent_messages = [
        {
            "id": i + 1,
            "timestamp": 100 + i,
            "sender_attr": "other" if i % 2 else "self",
            "content": f"msg{i}_" + ("很长" * 500),
        }
        for i in range(30)
    ]

    prompt = engine._build_prompt(
        "topic_cooling",
        "maintain",
        {"recent_messages": recent_messages},
    )

    assert "msg0_" not in prompt
    assert "msg10_" in prompt
    assert "msg29_" in prompt


def test_llm_prompt_keeps_twenty_recent_messages_even_when_each_is_long():
    engine = LLMSuggestionEngine()
    recent_messages = [
        {
            "id": i + 1,
            "timestamp": 100 + i,
            "sender_attr": "self" if i % 2 == 0 else "other",
            "content": f"消息{i}-" + ("很长" * 100),
        }
        for i in range(20)
    ]

    prompt = engine._build_prompt(
        "topic_cooling",
        "maintain",
        {"recent_messages": recent_messages},
    )

    assert "消息0-" in prompt
    assert "消息19-" in prompt


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


def test_llm_prompt_uses_visible_index_to_preserve_same_timestamp_order():
    engine = LLMSuggestionEngine()
    recent_messages = [
        {
            "id": 40,
            "timestamp": 1743078480,
            "visible_index": 7,
            "sender_attr": "self",
            "content": "今天晚上",
        },
        {
            "id": 39,
            "timestamp": 1743078480,
            "visible_index": 6,
            "sender_attr": "friend",
            "content": "你是指什么时候",
        },
        {
            "id": 38,
            "timestamp": 1743078480,
            "visible_index": 4,
            "sender_attr": "friend",
            "content": "行",
        },
        {
            "id": 37,
            "timestamp": 1743078480,
            "visible_index": 3,
            "sender_attr": "self",
            "content": "应该是修好了",
        },
    ]

    prompt = engine._build_prompt(
        "topic_cooling",
        "maintain",
        {"recent_messages": recent_messages},
    )

    assert prompt.index("我：应该是修好了") < prompt.index("对方：行")
    assert prompt.index("对方：行") < prompt.index("对方：你是指什么时候")
    assert prompt.index("对方：你是指什么时候") < prompt.index("我：今天晚上")


def test_llm_prompt_filters_content_rules_and_keeps_style_rules(monkeypatch):
    engine = LLMSuggestionEngine()

    monkeypatch.setattr(
        feedback_rule_extractor.FeedbackRuleExtractor,
        "get_active_rules",
        lambda self, display_name, account_wxid="": [
            "用户倾向于用图片而非文字表达情绪或状态",
            "用户这类场景更爱用语音回复，不会打长文字",
            "用户对不感兴趣的话题会直接转移话题",
            "用户拒绝闲聊时，会直接转移话题到学习内容",
            "用户倾向于用具体事实和数字回应，而非附和或调侃。",
        ],
    )

    prompt = engine._build_prompt(
        "topic_cooling",
        "maintain",
        {
            "display_name": "Grace.",
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
    assert "用户这类场景更爱用语音回复，不会打长文字" in prompt
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
    assert "【用户本体克隆画像（必须严格模仿，不可偏离）】" not in prompt
    assert "【量化风格硬约束（必须遵守）】" not in prompt


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


def test_llm_manual_request_treats_generate_suggestion_style_clone_as_advice_prompt():
    engine = LLMSuggestionEngine()

    prompt = engine._build_prompt(
        "manual_request",
        "maintain",
        {
            "user_context": [
                {"role": "user", "content": "生成建议 模仿我说话"},
            ],
        },
    )

    assert "请基于当前上下文给出可发送的话术" in prompt
    assert "不要生成建议卡片" not in prompt


def test_llm_streaming_response_reader_collects_content_deltas():
    engine = LLMSuggestionEngine()
    events = []
    lines = [
        b'data: {"choices":[{"delta":{"content":"{\\"summary\\":\\""}}]}\n',
        b'data: {"choices":[{"delta":{"content":"ok\\"}"}}]}\n',
        b"data: [DONE]\n",
    ]

    text = engine._read_streaming_response(
        lines,
        stream_callback=lambda event: events.append(event),
        allow_reasoning_fallback=False,
    )

    assert text == '{"summary":"ok"}'
    assert "".join(event.get("text", "") for event in events) == text


def test_llm_manual_request_treats_style_refinement_after_advice_as_advice_prompt():
    engine = LLMSuggestionEngine()

    prompt = engine._build_prompt(
        "manual_request",
        "maintain",
        {
            "user_context": [
                {"role": "user", "content": "她刚刚这样说，我该怎么开口？"},
                {"role": "assistant", "content": "建议你先真诚道歉。你可以说：对不起，刚刚那个类比不太合适。"},
                {"role": "user", "content": "模仿我说话"},
            ],
        },
    )

    assert "请基于当前上下文给出可发送的话术" in prompt
    assert "不要生成建议卡片" not in prompt


def test_llm_manual_request_treats_request_for_suggestion_speeches_as_advice_prompt():
    engine = LLMSuggestionEngine()

    prompt = engine._build_prompt(
        "manual_request",
        "maintain",
        {
            "user_context": [
                {"role": "user", "content": "你不生成点建议话术？"},
            ],
        },
    )

    assert "请基于当前上下文给出可发送的话术" in prompt
    assert "不要生成建议卡片" not in prompt


def test_llm_manual_request_treats_related_advice_as_advice_prompt():
    engine = LLMSuggestionEngine()

    prompt = engine._build_prompt(
        "manual_request",
        "intimate",
        {
            "user_context": [
                {"role": "assistant", "content": "可以，就提杀戮尖塔。"},
                {"role": "user", "content": "我要你给出相关建议"},
            ],
        },
    )

    assert "请基于当前上下文给出可发送的话术" in prompt
    assert "不要生成建议卡片" not in prompt


def test_llm_manual_request_treats_third_party_memory_followup_as_advice_prompt():
    engine = LLMSuggestionEngine()

    prompt = engine._build_prompt(
        "manual_request",
        "intimate",
        {
            "user_context": [
                {"role": "user", "content": "比如上次的杀戮尖塔啊 什么的"},
                {"role": "assistant", "content": "可以，就提杀戮尖塔，问问她最近有没有玩。"},
                {"role": "user", "content": "她上次说的什么流派 我不知道"},
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


def test_llm_parse_response_enforces_dynamic_style_constraints():
    engine = LLMSuggestionEngine()

    result = engine._parse_response(
        json.dumps(
                {
                    "reply": "",
                    "thought_process": "test",
                    "summary": "test",
                    "speeches": ["我理解你的感受😊", "今天真的是特别特别特别特别累吧"],
                },
                ensure_ascii=False,
            ),
        "manual_request",
        "maintain",
        style_constraints=StyleConstraints(
            emoji_density=0.0,
            avg_msg_length=6.0,
            max_speech_length=12,
            communication_type="reactive",
            emotional_style="cold",
            nickname_usage=False,
        ),
    )

    assert result is None


def test_llm_parse_response_keeps_reply_when_all_speeches_filtered():
    engine = LLMSuggestionEngine()

    result = engine._parse_response(
        json.dumps(
            {
                "reply": "我先帮你捋一下",
                "thought_process": "test",
                "summary": "这里其实不该展示建议卡片",
                "speeches": ["我理解你的感受😊"],
            },
            ensure_ascii=False,
        ),
        "manual_request",
        "maintain",
        style_constraints=StyleConstraints(
            emoji_density=0.0,
            avg_msg_length=5.0,
            max_speech_length=10,
            communication_type="balanced",
            emotional_style="neutral",
            nickname_usage=False,
        ),
    )

    assert result is not None
    assert result.summary == "[PURE_CHAT]"
    assert result.reply == "我先帮你捋一下"
    assert result.speeches == []


def test_llm_parse_response_keeps_manual_request_reference_speeches_when_reply_present():
    engine = LLMSuggestionEngine()

    result = engine._parse_response(
        json.dumps(
            {
                "reply": "好的，明白了。以下是建议话术：",
                "thought_process": "test",
                "summary": "承认行为不当并转移话题",
                "speeches": [
                    "行，我知道了。刚才确实是我没过脑子，不该拿你跟别人比，以后不这样了。",
                    "是我考虑不周。那种比较的行为确实挺没劲的，以后肯定注意。"
                ],
            },
            ensure_ascii=False,
        ),
        "manual_request",
        "maintain",
        style_constraints=StyleConstraints(
            emoji_density=0.0,
            avg_msg_length=6.0,
            max_speech_length=12,
            communication_type="balanced",
            emotional_style="neutral",
            nickname_usage=False,
        ),
    )

    assert result is not None
    assert result.summary == "承认行为不当并转移话题"
    assert result.reply == "好的，明白了。以下是建议话术："
    assert len(result.speeches) == 2


def test_llm_parse_response_keeps_manual_request_reference_speeches_without_reply():
    engine = LLMSuggestionEngine()

    result = engine._parse_response(
        json.dumps(
            {
                "reply": "",
                "thought_process": "用户在延续上一轮建议，需要给出可发送话术。",
                "summary": "用撒娇语气追问上次说的内容",
                "speeches": [
                    "宝宝 上次你说什么贵来着 我忘了 再跟我说说呗～",
                    "嘿嘿 宝宝上次说杀戮尖塔里啥贵啊 我记性不好",
                    "宝宝不是说要买啥贵的嘛 我忘了 提醒我一下～",
                ],
            },
            ensure_ascii=False,
        ),
        "manual_request",
        "intimate",
        style_constraints=StyleConstraints(
            emoji_density=0.345,
            avg_msg_length=8.5,
            max_speech_length=21,
            communication_type="reactive",
            emotional_style="warm",
            nickname_usage=True,
        ),
    )

    assert result is not None
    assert result.summary == "用撒娇语气追问上次说的内容"
    assert len(result.speeches) == 3


def test_llm_antipattern_match_avoids_overblocking_followup_question():
    engine = LLMSuggestionEngine()

    assert engine._contains_ai_antipattern("你说得对。") is True
    assert engine._contains_ai_antipattern("你说得对吧？") is False


def test_llm_sanitize_limited_emoji_keeps_last_emoji():
    engine = LLMSuggestionEngine()

    sanitized = engine._sanitize_speech_candidate(
        "好呀😊😂",
        StyleConstraints(
            emoji_density=0.02,
            avg_msg_length=8.0,
            max_speech_length=20,
            communication_type="balanced",
            emotional_style="neutral",
            nickname_usage=False,
        ),
    )

    assert sanitized == "好呀😂"


def test_llm_extract_message_text_falls_back_to_reasoning_content():
    engine = LLMSuggestionEngine()

    content = engine._extract_message_text(
        {
            "content": "",
            "reasoning_content": '{"reply":"","thought_process":"测试","summary":"测试摘要","speeches":["测试话术"]}',
        }
    )

    assert '"summary":"测试摘要"' in content


def test_llm_extract_message_text_ignores_reasoning_content_for_json_mode():
    engine = LLMSuggestionEngine()

    content = engine._extract_message_text(
        {
            "content": "",
            "reasoning_content": "这里是模型推理过程，不是最终 JSON。",
        },
        allow_reasoning_fallback=False,
    )

    assert content == ""


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
- 杀戮尖塔2好玩吗
- 你现在打到哪了
        """,
        "manual_request",
        "maintain",
    )

    assert result is not None
    assert result.summary == "已从思考输出中提取可直接发送的话术"
    assert result.speeches == ["那你最近又在玩啥", "杀戮尖塔2好玩吗", "你现在打到哪了"]


def test_llm_parse_response_rejects_meta_prompt_rules_as_speeches():
    engine = LLMSuggestionEngine()

    result = engine._parse_response(
        """
{
  "reply": "",
  "thought_process": "thought_process: 基于用户输入是主动请求建议来开启一个特定话题",
  "summary": "话术应该关于开启杀戮尖塔2SL mod的话题。",
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
    monkeypatch.setattr(engine, "_build_prompt", lambda trigger_type, intent, context, model_config=None: "prompt")
    monkeypatch.setattr(
        engine,
        "_generate_reasoning_analysis",
        lambda model_config, user_prompt: "对方在聊游戏模组，顺着兴趣切进去更自然。\n- 你那个SL mod具体改了啥",
    )
    monkeypatch.setattr(
        engine,
        "_format_reasoning_result",
        lambda model_config, user_prompt, analysis_text: """
{"reply":"","thought_process":"对方在聊游戏模组，顺着兴趣切进去更自然。","summary":"顺着杀戮尖塔2 mod继续聊。","speeches":["你那个SL mod具体改了啥","这个mod你是在哪下的","你现在玩起来手感咋样"]}        
        """,
    )
    monkeypatch.setattr(
        engine,
        "_repair_response",
        lambda model_config, user_prompt, raw_response: """
{"reply":"","thought_process":"对方在聊游戏模组，顺着兴趣切进去更自然。","summary":"顺着杀戮尖塔2 mod继续聊。","speeches":["你那个SL mod具体改了啥","这个mod你是在哪下的","你现在玩起来手感咋样"]}        
        """,
    )

    result = engine.generate("manual_request", "maintain", {})

    assert result.summary == "顺着杀戮尖塔2 mod继续聊。"
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


def test_llm_parse_response_salvages_truncated_json_speech():
    engine = LLMSuggestionEngine()

    result = engine._parse_response(
        '{\n'
        '  "reply": "好的，根据聊天记录给你几个选择：",\n'
        '  "thought_process": "对方抱怨贵，顺着无奈语气接一句。",\n'
        '  "summary": "用无奈带点幽默回应。",\n'
        '  "speeches": [\n'
        '    "那咋整，咱还能不买',
        "manual_request",
        "maintain",
    )

    assert result is not None
    assert result.summary == "用无奈带点幽默回应。"
    assert result.speeches == ["那咋整，咱还能不买"]


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
    assert captured["payload"]["max_tokens"] >= 768


def test_llm_call_api_uses_dynamic_completion_budget_for_long_json_prompt(monkeypatch):
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
                    "usage": {"prompt_tokens": 1200, "completion_tokens": 1, "total_tokens": 1201},
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
            "max_tokens": 512,
            "temperature": 0.3,
        },
        "长上下文" * 900,
    )

    assert captured["payload"]["max_tokens"] >= 1280


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


def test_generate_quick_prompts_uses_twenty_message_window_with_recency_weighting(monkeypatch):
    engine = LLMSuggestionEngine()
    captured = {}

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

    def fake_call(model_config, prompt):
        captured["prompt"] = prompt
        return '["继续游戏","表达关心","顺着话题","转移话题"]'

    monkeypatch.setattr(engine, "_call_quick_prompts_api", fake_call)

    prompts = engine.generate_quick_prompts(
        {
            "recent_messages": [
                {
                    "id": i + 1,
                    "timestamp": 100 + i,
                    "sender_attr": "self" if i % 2 == 0 else "other",
                    "content": f"消息{i}",
                }
                for i in range(12)
            ],
        }
    )

    assert "消息0" in captured["prompt"]
    assert "消息11" in captured["prompt"]
    assert "越新的消息权重越高" in captured["prompt"]
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


def test_self_profiler_parse_profile_json_repairs_common_llm_json_variants():
    profiler = SelfProfiler()

    parsed = profiler._parse_profile_json(
        """
        ```json
        {
          "typing_style": "极简短句流",
          "frequent_catchphrases": ["6", "nmd", "逆天",],
          "sentence_patterns": ["哈哈
这个",],
          "shared_memories": ["我最近聊过硬件",],
          "attitude_and_role": "熟人间吐槽",
          "do_and_donts": "控制在 8-12 字",
        }
        ```
        """
    )

    assert parsed is not None
    assert parsed["frequent_catchphrases"] == ["6", "nmd", "逆天"]
    assert parsed["sentence_patterns"] == ["哈哈\n这个"]
    assert parsed["do_and_donts"] == "控制在 8-12 字"
