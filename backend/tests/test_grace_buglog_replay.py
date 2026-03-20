"""Replay prompt snapshots derived from 阿澄's bug.log session."""

from __future__ import annotations

import os
import sys


sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.realtime import feedback_rule_extractor
from app.services.realtime.llm_engine import LLMSuggestionEngine


def _build_recent_messages(raw_messages: list[tuple[str, str]]) -> list[dict]:
    messages = []
    for index, (sender_attr, content) in enumerate(raw_messages, start=1):
        messages.append(
            {
                "id": index,
                "timestamp": index,
                "sender_attr": sender_attr,
                "content": content,
            }
        )
    return messages


def _extract_recent_block(prompt: str) -> str:
    if "【最近对话】" not in prompt:
        return prompt
    return prompt.split("【最近对话】", 1)[1].split(
        "请根据以上信息生成思考过程和沟通建议", 1
    )[0]


BUGLOG_TOPIC_SHIFT = _build_recent_messages(
    [
        ("self", "那很爽了"),
        ("other", "而且都是他们找我交朋友"),
        ("other", "我可能吸引有钱人"),
        ("self", "看见你就想扶贫了（）"),
        ("self", "动画表情"),
        ("other", "我会装自己有钱"),
        ("other", "装不下去了，天天拼好饭"),
        ("self", "[捂脸]我之前还算能用的有余"),
        ("self", "买了台NS"),
        ("self", "完了"),
        ("self", "每个月都烧光"),
        ("other", "我也是啊，我把钱all in买中古包"),
        ("self", "主要是上课也能掏出来玩"),
        ("other", "下个月才有钱了"),
        ("self", "[捂脸]我没招了 这个啥鸟ai还在高数"),
        ("self", "图片"),
        ("other", "我都不学高数了"),
    ]
)


BUGLOG_RECENT_FIRST = _build_recent_messages(
    [
        ("self", "铁球跑今天开播"),
        ("self", "急死我了"),
        ("self", "看不到"),
        ("self", "我操"),
        ("self", "真的吗"),
        ("self", "真的啊"),
        ("self", "急死了"),
        ("self", "哪里看"),
        ("self", "网飞"),
        ("self", "坐等SBR上线"),
        ("self", "[捂脸]你还是那么抽象"),
        ("self", "上大学了没咋看见你上steam了"),
        ("other", "玩的少了"),
        ("self", "现在在玩潜水员"),
        ("self", "找个是？"),
        ("self", "真潜水吗？"),
        ("self", "还是？"),
        ("other", "就是那个潜水游戏"),
    ]
)


def test_grace_buglog_prompt_focuses_on_latest_topic_shift():
    engine = LLMSuggestionEngine()
    prompt = engine._build_prompt(
        "topic_cooling",
        "maintain",
        {"recent_messages": BUGLOG_TOPIC_SHIFT},
    )
    recent_block = _extract_recent_block(prompt)

    assert "我都不学高数了" in recent_block
    assert "这个啥鸟ai还在高数" in recent_block
    assert "下个月才有钱了" in recent_block
    assert "就是那个潜水游戏" not in recent_block
    assert "铁球跑今天开播" not in recent_block


def test_grace_buglog_prompt_keeps_current_game_topic_without_reordering():
    engine = LLMSuggestionEngine()
    prompt = engine._build_prompt(
        "topic_cooling",
        "maintain",
        {"recent_messages": list(reversed(BUGLOG_RECENT_FIRST))},
    )
    recent_block = _extract_recent_block(prompt)

    assert "就是那个潜水游戏" in recent_block
    assert "现在在玩潜水员" in recent_block
    assert recent_block.index("铁球跑今天开播") < recent_block.index("就是那个潜水游戏")


def test_grace_buglog_prompt_ignores_content_rules(monkeypatch):
    engine = LLMSuggestionEngine()

    monkeypatch.setattr(
        feedback_rule_extractor.FeedbackRuleExtractor,
        "get_active_rules",
        lambda self, display_name: [
            "用户对不感兴趣的话题会直接转移话题",
            "用户倾向于开启新话题而非延续玩笑",
            "用户倾向于用图片而非文字表达情绪或状态",
        ],
    )

    prompt = engine._build_prompt(
        "topic_cooling",
        "maintain",
        {
            "display_name": "阿澄",
            "recent_messages": BUGLOG_TOPIC_SHIFT,
        },
    )

    assert "用户倾向于用图片而非文字表达情绪或状态" in prompt
    assert "用户对不感兴趣的话题会直接转移话题" not in prompt
    assert "用户倾向于开启新话题而非延续玩笑" not in prompt


if __name__ == "__main__":
    engine = LLMSuggestionEngine()
    cases = [
        ("latest_topic_shift", BUGLOG_TOPIC_SHIFT),
        ("recent_first_ordering", list(reversed(BUGLOG_RECENT_FIRST))),
    ]
    for name, recent_messages in cases:
        prompt = engine._build_prompt(
            "topic_cooling",
            "maintain",
            {"recent_messages": recent_messages},
        )
        print(f"\n=== {name} ===")
        print(_extract_recent_block(prompt).strip())
