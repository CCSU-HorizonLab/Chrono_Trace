"""Tests for implicit feedback rule extraction."""

import os
import sys


sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.realtime.feedback_rule_extractor import FeedbackRuleExtractor


def test_compare_and_extract_prefers_heuristic_short_ack(monkeypatch):
    extractor = FeedbackRuleExtractor()
    saved_rules = []

    monkeypatch.setattr(
        extractor,
        "save_rule",
        lambda **kwargs: saved_rules.append(kwargs),
    )

    def _should_not_call_llm(*args, **kwargs):
        raise AssertionError("LLM fallback should not run when heuristic rule is available")

    monkeypatch.setattr(extractor, "_llm_compare", _should_not_call_llm)

    result = extractor.compare_and_extract(
        ai_speeches=["好呀 那你先去忙吧", "没事 我等你回"],
        user_actual_message="行",
        display_name="阿澄",
    )

    assert result is not None
    assert result["source"] == "heuristic"
    assert any("简短肯定" in item["rule"] for item in result["rules"])
    assert any("简短肯定" in item["rule_text"] for item in saved_rules)


def test_compare_and_extract_detects_voice_preference(monkeypatch):
    extractor = FeedbackRuleExtractor()
    saved_rules = []

    monkeypatch.setattr(
        extractor,
        "save_rule",
        lambda **kwargs: saved_rules.append(kwargs),
    )

    result = extractor.compare_and_extract(
        ai_speeches=["你先说吧", "晚点再聊"],
        user_actual_message="语音",
        user_message_type=34,
        display_name="阿澄",
    )

    assert result is not None
    assert result["rule"] == "用户这类场景更爱用语音回复，不会打长文字"
    assert saved_rules[0]["rule_text"] == "用户这类场景更爱用语音回复，不会打长文字"


def test_compare_and_extract_falls_back_to_llm_when_no_heuristic_signal(monkeypatch):
    extractor = FeedbackRuleExtractor()
    saved_rules = []
    llm_calls = []

    monkeypatch.setattr(
        extractor,
        "save_rule",
        lambda **kwargs: saved_rules.append(kwargs),
    )

    def _fake_llm_compare(ai_speeches, user_message):
        llm_calls.append((ai_speeches, user_message))
        return {
            "rule": "用户更常用口语短句，不写完整书面句",
            "confidence": 0.74,
            "scope": "contact",
        }

    monkeypatch.setattr(extractor, "_llm_compare", _fake_llm_compare)

    result = extractor.compare_and_extract(
        ai_speeches=["今天应该问题不大", "要不你先看看"],
        user_actual_message="最近忙疯了",
        display_name="阿澄",
    )

    assert llm_calls == [(["今天应该问题不大", "要不你先看看"], "最近忙疯了")]
    assert result["rule"] == "用户更常用口语短句，不写完整书面句"
    assert saved_rules[0]["rule_text"] == "用户更常用口语短句，不写完整书面句"


def test_analyze_feedback_classifies_adopted_without_rule(monkeypatch):
    extractor = FeedbackRuleExtractor()

    def _should_not_call_llm(*args, **kwargs):
        raise AssertionError("LLM fallback should not run for adopted messages")

    monkeypatch.setattr(extractor, "_llm_compare", _should_not_call_llm)

    result = extractor.analyze_feedback(
        ai_speeches=["今天应该问题不大", "要不你先看看"],
        user_actual_message="今天应该问题不大",
        display_name="阿澄",
    )

    assert result["outcome"] == "adopted"
    assert result["rules"] == []
    assert result["selected_speech"] == "今天应该问题不大"
