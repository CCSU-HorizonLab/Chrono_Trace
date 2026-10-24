"""Replay prompt snapshots derived from a real bug.log session（对话内容已匿名化改写）。"""

from __future__ import annotations

import os
import sys
from pathlib import Path


sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import app.db.connection as db_connection
from app.services.realtime.emotion_state_tracker import (
    EmotionStateTracker,
    TRIGGER_EMOTION_SHIFT,
)
from app.services.realtime import feedback_rule_extractor
from app.services.realtime.llm_engine import LLMSuggestionEngine
from scripts import replay_buglog_live as replay_live
from scripts.replay_buglog_live import CASES, detect_trigger


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


def _update_tracker_with_friend_window(items: list[tuple[str, int, float, float]]):
    tracker = EmotionStateTracker()
    triggers = []
    for index, (content, polarity, intensity, confidence) in enumerate(items, start=1):
        triggers = tracker.update(
            {
                "polarity": polarity,
                "intensity": intensity,
                "confidence": confidence,
                "rules_applied": [],
            },
            {
                "content": content,
                "sender_attr": "friend",
                "timestamp": index,
            },
            current_time=float(index),
        )
    return triggers


BUGLOG_TOPIC_SHIFT = _build_recent_messages(
    [
        ("self", "那确实爽"),
        ("other", "而且都是别人主动找我玩"),
        ("other", "我朋友好像都挺有钱"),
        ("self", "看见你就想接济你了（）"),
        ("self", "动画表情"),
        ("other", "我在朋友面前装大方"),
        ("other", "装不下去了，天天省着花"),
        ("self", "[捂脸]我之前手头还算宽裕"),
        ("self", "买了台游戏机"),
        ("self", "完了"),
        ("self", "每个月都花光"),
        ("other", "我也是啊，我把钱都拿去买东西了"),
        ("self", "主要是随身带着也能玩"),
        ("other", "下个月才有生活费了"),
        ("self", "[捂脸]我没招了 这课还挂着"),
        ("self", "图片"),
        ("other", "我都不上那门课了"),
    ]
)


BUGLOG_RECENT_FIRST = _build_recent_messages(
    [
        ("self", "那个直播今天开播"),
        ("self", "急死我了"),
        ("self", "看不到"),
        ("self", "我操"),
        ("self", "真的吗"),
        ("self", "真的啊"),
        ("self", "急死了"),
        ("self", "哪里看"),
        ("self", "流媒体上"),
        ("self", "坐等新剧上线"),
        ("self", "[捂脸]你还是那么抽象"),
        ("self", "上大学了没咋见你上线了"),
        ("other", "玩的少了"),
        ("self", "现在在玩那个潜水的"),
        ("self", "找个是？"),
        ("self", "真潜水吗？"),
        ("self", "还是？"),
        ("other", "就是那个潜水游戏"),
    ]
)


def test_buglog_prompt_focuses_on_latest_topic_shift():
    engine = LLMSuggestionEngine()
    prompt = engine._build_prompt(
        "topic_cooling",
        "maintain",
        {"recent_messages": BUGLOG_TOPIC_SHIFT},
    )
    recent_block = _extract_recent_block(prompt)

    assert "我都不上那门课了" in recent_block
    assert "这课还挂着" in recent_block
    assert "下个月才有生活费了" in recent_block
    assert "就是那个潜水游戏" not in recent_block
    assert "那个直播今天开播" not in recent_block


def test_buglog_prompt_keeps_current_game_topic_without_reordering():
    engine = LLMSuggestionEngine()
    prompt = engine._build_prompt(
        "topic_cooling",
        "maintain",
        {"recent_messages": list(reversed(BUGLOG_RECENT_FIRST))},
    )
    recent_block = _extract_recent_block(prompt)

    assert "就是那个潜水游戏" in recent_block
    assert "现在在玩那个潜水的" in recent_block
    assert recent_block.index("那个直播今天开播") < recent_block.index("就是那个潜水游戏")


def test_buglog_prompt_ignores_content_rules(monkeypatch):
    engine = LLMSuggestionEngine()

    monkeypatch.setattr(
        feedback_rule_extractor.FeedbackRuleExtractor,
        "get_active_rules",
        lambda self, display_name, account_wxid="": [
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


def test_buglog_dorm_annoyance_window_no_longer_triggers_emotion_shift():
    triggers = _update_tracker_with_friend_window(
        [
            ("这事居然解决了", 1, 0.7, 0.9),
            ("那还挺顺的", 1, 0.5, 0.9),
            ("还行吧", 1, 0.3, 0.85),
            ("我很讨厌吵闹的环境", -1, -0.7, 0.92),
            ("动画表情", 0, 0.0, 0.95),
        ]
    )

    assert TRIGGER_EMOTION_SHIFT not in [ev.trigger_type for ev in triggers]


def test_buglog_part_time_money_window_no_longer_triggers_emotion_shift():
    triggers = _update_tracker_with_friend_window(
        [
            ("前面还挺开心的", 1, 0.8, 0.9),
            ("感觉之后机会还挺多", 1, 0.6, 0.9),
            ("嗯还不错", 1, 0.4, 0.85),
            ("我打算去兼职赚点小钱", 0, 0.0, 0.95),
        ]
    )

    assert TRIGGER_EMOTION_SHIFT not in [ev.trigger_type for ev in triggers]


def test_replay_live_detect_trigger_returns_no_trigger_for_abroad_plan():
    trigger_type, trigger_context = detect_trigger(CASES["abroad_study_plan"]["messages"])

    assert trigger_type is None
    assert trigger_context == {}


def test_replay_live_detect_trigger_returns_no_trigger_for_part_time_money():
    trigger_type, trigger_context = detect_trigger(CASES["part_time_money"]["messages"])

    assert trigger_type is None
    assert trigger_context == {}


def test_list_cached_display_names_deduplicates_rows(monkeypatch):
    class _FakeCursor:
        def fetchall(self):
            return [
                {"display_name": "阿澄"},
                {"display_name": "阿澄"},
                {"display_name": "家人"},
                {"display_name": None},
            ]

    class _FakeConn:
        def execute(self, *_args, **_kwargs):
            return _FakeCursor()

    monkeypatch.setattr(db_connection, "get_db", lambda: _FakeConn())

    assert replay_live.list_cached_display_names() == ["阿澄", "家人"]


def test_run_multi_evaluation_aggregates_reports(monkeypatch):
    reports_by_name = {
        "阿澄": {
            "display_name": "阿澄",
            "generated_case_count": 2,
            "no_trigger_case_count": 4,
            "zero_emoji_cases_all_clean": True,
            "all_generated_cases_within_length_limit": True,
            "all_generated_cases_without_antipattern": True,
            "cases": [
                {"computed_trigger_type": "negative_streak", "speeches": ["确实烦", "先缓缓"]},
                {"computed_trigger_type": "no_trigger", "speeches": []},
            ],
        },
        "家人": {
            "display_name": "家人",
            "generated_case_count": 1,
            "no_trigger_case_count": 5,
            "zero_emoji_cases_all_clean": False,
            "all_generated_cases_within_length_limit": True,
            "all_generated_cases_without_antipattern": False,
            "cases": [
                {"computed_trigger_type": "positive_window", "speeches": ["好耶", "知道啦"]},
            ],
        },
    }

    monkeypatch.setattr(
        replay_live,
        "run_evaluation",
        lambda display_name: reports_by_name[display_name],
    )

    report = replay_live.run_multi_evaluation(["阿澄", "家人", "阿澄"])

    assert report["display_names"] == ["阿澄", "家人"]
    assert report["contact_count"] == 2
    assert report["generated_case_count"] == 3
    assert report["no_trigger_case_count"] == 9
    assert report["all_zero_emoji_cases_clean"] is False
    assert report["all_generated_cases_within_length_limit"] is True
    assert report["all_generated_cases_without_antipattern"] is False
    assert report["contact_summaries"][0]["sample_speeches"] == ["确实烦", "先缓缓"]
    assert report["contact_summaries"][1]["sample_speeches"] == ["好耶", "知道啦"]


def test_run_multi_evaluation_respects_explicit_empty_contacts(monkeypatch):
    monkeypatch.setattr(
        replay_live,
        "list_cached_display_names",
        lambda: ["阿澄"],
    )

    report = replay_live.run_multi_evaluation([])

    assert report["display_names"] == []
    assert report["contact_count"] == 0
    assert report["generated_case_count"] == 0
    assert report["no_trigger_case_count"] == 0
    assert report["contact_summaries"] == []
    assert report["reports"] == []


def test_save_report_uses_multi_prefix_for_batch_results(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(replay_live, "LOG_DIR", tmp_path)
    report = {
        "generated_at": 123456,
        "reports": [],
    }

    output_path = replay_live.save_report(report)

    assert output_path.name == "realtime_suggestion_eval_multi_123456.json"
    assert output_path.exists()


def test_fill_missing_history_sentiments_only_updates_missing_text_messages():
    messages = [
        {
            "id": 1,
            "timestamp": 100,
            "sender_attr": "other",
            "content": "最近有点烦",
            "message_type": 1,
            "sentiment": None,
        },
        {
            "id": 2,
            "timestamp": 101,
            "sender_attr": "self",
            "content": "动画表情",
            "message_type": 3,
            "sentiment": None,
        },
        {
            "id": 3,
            "timestamp": 102,
            "sender_attr": "other",
            "content": "还行",
            "message_type": 1,
            "sentiment": {"polarity": 0, "intensity": 0.0, "confidence": 1.0, "rules": []},
        },
    ]

    filled_count = replay_live.fill_missing_history_sentiments(
        messages,
        sentiment_analyzer=lambda texts: [
            {
                "polarity": -1,
                "intensity": -0.7,
                "confidence": 0.91,
                "rules_applied": ["测试规则"],
            }
        ],
    )

    assert filled_count == 1
    assert messages[0]["sentiment"]["polarity"] == -1
    assert messages[0]["sentiment"]["rules"] == ["测试规则"]
    assert messages[1]["sentiment"] is None
    assert messages[2]["sentiment"]["polarity"] == 0


def test_build_emotion_summary_treats_missing_sentiment_as_neutral():
    summary = replay_live.build_emotion_summary(
        [
            {"sender_attr": "other", "content": "图片", "sentiment": None},
            {"sender_attr": "other", "content": "有点累", "sentiment": {"polarity": -1, "intensity": -0.6}},
        ]
    )

    assert summary["window_size"] == 2
    assert summary["recent_polarities"] == [0, -1]
    assert summary["avg_polarity"] == -0.5


def test_message_content_for_eval_skips_binaryish_text():
    content = replay_live._message_content_for_eval(
        1,
        b'(\xff/\xff`F\x01U\r\x00\xd6\x9c[3pI',
    )

    assert content == ""


def test_select_real_history_case_entries_prefers_triggered_windows(monkeypatch):
    messages = replay_live.build_messages(
        [
            ("self", "前情1", 0),
            ("other", "前情2", 0),
            ("self", "前情3", 0),
            ("other", "普通窗口", 0),
            ("self", "继续聊", 0),
            ("other", "触发A", -1, -0.7, 0.9),
            ("self", "接一句", 0),
            ("other", "触发B", 1, 0.8, 0.9),
            ("self", "再接一句", 0),
            ("other", "普通收尾", 0),
        ]
    )

    def _fake_detect(window):
        latest = window[-1]["content"]
        if latest == "触发A":
            return "negative_streak", {"source": "test"}
        if latest == "触发B":
            return "positive_window", {"source": "test"}
        return None, {}

    monkeypatch.setattr(replay_live, "detect_trigger", _fake_detect)

    entries = replay_live.select_real_history_case_entries(
        "阿澄",
        messages,
        max_cases=3,
        window_size=4,
        trigger_limit=2,
        no_trigger_limit=1,
        min_gap=1,
    )

    assert len(entries) == 3
    assert [entry["computed_trigger"] for entry in entries[:2]] == [
        "positive_window",
        "negative_streak",
    ]
    assert entries[2]["computed_trigger"] is None


def test_run_real_history_multi_evaluation_aggregates_reports(monkeypatch):
    reports_by_name = {
        "阿澄": {
            "display_name": "阿澄",
            "mode": "real_history",
            "conversation_id": 1,
            "message_pool_size": 120,
            "generated_case_count": 2,
            "no_trigger_case_count": 2,
            "sentiment_filled_count": 12,
            "zero_emoji_cases_all_clean": True,
            "all_generated_cases_within_length_limit": True,
            "all_generated_cases_without_antipattern": True,
            "cases": [
                {
                    "computed_trigger_type": "negative_streak",
                    "notes": "窗口A",
                    "speeches": ["确实烦", "先缓缓"],
                },
                {
                    "computed_trigger_type": "no_trigger",
                    "notes": "窗口B",
                    "speeches": [],
                },
            ],
        },
        "家人": {
            "display_name": "家人",
            "mode": "real_history",
            "conversation_id": 2,
            "message_pool_size": 90,
            "generated_case_count": 1,
            "no_trigger_case_count": 3,
            "sentiment_filled_count": 5,
            "zero_emoji_cases_all_clean": True,
            "all_generated_cases_within_length_limit": True,
            "all_generated_cases_without_antipattern": False,
            "cases": [
                {
                    "computed_trigger_type": "positive_window",
                    "notes": "窗口C",
                    "speeches": ["那就好", "挺好的"],
                },
            ],
        },
    }

    monkeypatch.setattr(
        replay_live,
        "run_real_history_evaluation",
        lambda display_name, **kwargs: reports_by_name[display_name],
    )

    report = replay_live.run_real_history_multi_evaluation(["阿澄", "家人"])

    assert report["mode"] == "real_history_multi"
    assert report["contact_count"] == 2
    assert report["generated_case_count"] == 3
    assert report["no_trigger_case_count"] == 5
    assert report["total_sentiment_filled_count"] == 17
    assert report["all_generated_cases_without_antipattern"] is False
    assert report["contact_summaries"][0]["sample_windows"] == ["窗口A", "窗口B"]
    assert report["contact_summaries"][1]["sample_speeches"] == ["那就好", "挺好的"]


def test_save_report_uses_real_history_prefix(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(replay_live, "LOG_DIR", tmp_path)
    report = {
        "generated_at": 654321,
        "mode": "real_history_multi",
        "reports": [],
    }

    output_path = replay_live.save_report(report)

    assert output_path.name == "realtime_suggestion_eval_real_history_multi_654321.json"
    assert output_path.exists()


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
