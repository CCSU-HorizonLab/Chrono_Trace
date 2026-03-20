"""Quasi-production LLM replay for 阿澄's bug.log scenarios."""

from __future__ import annotations

import json
import os
import sys


sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.realtime.contact_profiler import ContactProfiler
from app.services.realtime.feedback_rule_extractor import FeedbackRuleExtractor
from app.services.realtime.historical_context import build_historical_context
from app.services.realtime.llm_engine import LLMSuggestionEngine
from app.services.realtime.self_profiler import SelfProfiler
from app.services.realtime.session_thread_service import SessionThreadService


DISPLAY_NAME = "阿澄"


def build_messages(items: list[tuple[str, str, int]]) -> list[dict]:
    return [
        {
            "id": index,
            "timestamp": index,
            "sender_attr": sender_attr,
            "content": content,
            "sentiment": {
                "polarity": polarity,
                "intensity": abs(polarity),
                "confidence": 0.9,
                "rules": [],
            },
        }
        for index, (sender_attr, content, polarity) in enumerate(items, start=1)
    ]


def build_emotion_summary(messages: list[dict]) -> dict:
    other_messages = [msg for msg in messages if msg.get("sender_attr") == "other"][-5:]
    if not other_messages:
        return {
            "window_size": 0,
            "avg_polarity": 0.0,
            "avg_intensity": 0.0,
            "trend": "neutral",
            "recent_polarities": [],
        }

    polarities = [msg["sentiment"]["polarity"] for msg in other_messages]
    intensities = [msg["sentiment"]["intensity"] for msg in other_messages]
    avg_polarity = sum(polarities) / len(polarities)
    if avg_polarity > 0.3:
        trend = "positive"
    elif avg_polarity < -0.3:
        trend = "negative"
    else:
        trend = "neutral"
    return {
        "window_size": len(other_messages),
        "avg_polarity": round(avg_polarity, 3),
        "avg_intensity": round(sum(intensities) / len(intensities), 3),
        "trend": trend,
        "recent_polarities": polarities,
    }


CASES = {
    "abroad_study_plan": {
        "trigger_type": "topic_cooling",
        "messages": build_messages(
            [
                ("self", "等我毕业再说吧。", 0),
                ("self", "挺好", 0),
                ("self", "毕业么 你打算考研还是就业啊", 0),
                ("other", "看能不能去外地发展", 0),
            ]
        ),
    },
    "dorm_annoyance": {
        "trigger_type": "emotion_shift",
        "messages": build_messages(
            [
                ("other", "我们被记也不会为难学委，毕竟知道是导员要求的，不燃学委也不抓...", 0),
                ("self", "所以说啊 我记别人 就没人跟我急眼的 这个哥们是黑皮 有点喜...", 0),
                ("self", "宿舍里熬夜打CS 大吼大叫", 0),
                ("self", "幸好大三换寝室了", 0),
                ("other", "我很讨厌体育队还有打游戏大吼大叫", -1),
                ("other", "动画表情", 0),
            ]
        ),
    },
    "part_time_money": {
        "trigger_type": "emotion_shift",
        "messages": build_messages(
            [
                ("self", "土死了，玩烂梗自以为美式的", -1),
                ("self", "长沙这边做软件开发6k 我干服务员都有4k[Emm] 薪资低...", 0),
                ("other", "我打算毕业去兼职赚点小钱", 0),
            ]
        ),
    },
}


def build_context(display_name: str, case_name: str, payload: dict) -> dict:
    recent_messages = payload["messages"]
    emotion_summary = build_emotion_summary(recent_messages)
    contact_profile = ContactProfiler().get_profile(display_name)
    self_profile = SelfProfiler().get_profile(display_name)
    rules = FeedbackRuleExtractor().get_active_rules(display_name)
    memories = SessionThreadService().retrieve_relevant_memories(display_name, recent_messages)

    ctx = {
        "recent_messages": recent_messages,
        "emotion_summary": emotion_summary,
        "historical_context": build_historical_context(
            contact_profile=None if not contact_profile or contact_profile.get("expired") else contact_profile["profile"],
            emotion_summary=emotion_summary,
            recent_messages=recent_messages,
        ),
        "display_name": display_name,
        "trigger_context": {
            "source": "buglog_live_replay",
            "case": case_name,
            "active_rules_count": len(rules),
        },
    }
    if contact_profile and not contact_profile.get("expired"):
        ctx["contact_profile"] = contact_profile["profile"]
    if self_profile and not self_profile.get("expired"):
        ctx["self_profile"] = self_profile["profile"]
    if memories:
        ctx["relevant_memories"] = memories
    return ctx


def main() -> None:
    engine = LLMSuggestionEngine(timeout=90)
    for case_name, payload in CASES.items():
        ctx = build_context(DISPLAY_NAME, case_name, payload)
        result = engine.generate(payload["trigger_type"], "maintain", ctx)
        print(f"\n=== {case_name} ===")
        print(
            json.dumps(
                {
                    "trigger_type": payload["trigger_type"],
                    "emotion_summary": ctx["emotion_summary"],
                    "summary": result.summary,
                    "speeches": result.speeches,
                    "thought_process": result.thought_process,
                    "reply": result.reply,
                },
                ensure_ascii=False,
                indent=2,
            )
        )


if __name__ == "__main__":
    main()
