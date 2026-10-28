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

    def _fake_llm_compare(ai_speeches, user_message, account_wxid=""):
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


class TestLlmCompareRedactionRedline:
    """远程对比脱敏红线：发送前脱敏、失败即阻断、本地模型豁免。"""

    @staticmethod
    def _remote_model():
        return {
            "name": "远程", "provider": "deepseek", "model_id": "deepseek-chat",
            "api_base_url": "https://api.deepseek.com/v1", "api_key": "sk-x",
        }

    def _capture_request(self, monkeypatch, captured):
        import json as _json

        class _Resp:
            def read(self):
                return _json.dumps({
                    "choices": [{"message": {
                        "content": '{"rule": "口语短句", "confidence": 0.7, "scope": "contact"}'
                    }}]
                }).encode()

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        class _Req:
            def __init__(self, url, data=None, headers=None, method=None):
                captured.append(_json.loads(data))

        monkeypatch.setattr(
            "urllib.request.urlopen", lambda req, timeout=None: _Resp()
        )
        monkeypatch.setattr("urllib.request.Request", _Req)

    def test_remote_compare_redacts_pii_before_send(self, monkeypatch):
        """远程模型：用户消息中的手机号在 payload 里必须是占位符。"""
        import sqlite3
        extractor = FeedbackRuleExtractor()
        monkeypatch.setattr(extractor, "_get_active_model", lambda: self._remote_model())

        import app.db.connection as db_connection
        conn = sqlite3.connect(":memory:")
        monkeypatch.setattr(db_connection, "get_db", lambda: conn)

        captured = []
        self._capture_request(monkeypatch, captured)
        result = extractor._llm_compare(
            ["要不要先吃饭"], "打我电话13800138000", account_wxid="acct"
        )
        assert result and result["rule"] == "口语短句"
        sent = captured[0]["messages"][1]["content"]
        assert "13800138000" not in sent
        assert "[PHONE_" in sent

    def test_redaction_failure_blocks_remote_send(self, monkeypatch):
        """脱敏失败：不发送任何请求，返回 None（红线阻断）。"""
        extractor = FeedbackRuleExtractor()
        monkeypatch.setattr(extractor, "_get_active_model", lambda: self._remote_model())

        import app.services.realtime.privacy_redactor as prmod
        def _boom(*a, **k):
            raise RuntimeError("db 不可用")
        monkeypatch.setattr(prmod.PrivacyRedactor, "redact", _boom)

        captured = []
        self._capture_request(monkeypatch, captured)
        assert extractor._llm_compare(["话术"], "消息", account_wxid="acct") is None
        assert captured == []  # 未出网

    def test_local_model_skips_redaction(self, monkeypatch):
        """本地模型（回环地址）不出网到远程，无需脱敏。"""
        extractor = FeedbackRuleExtractor()
        local = dict(self._remote_model(), api_base_url="http://127.0.0.1:11434/v1")
        monkeypatch.setattr(extractor, "_get_active_model", lambda: local)

        captured = []
        self._capture_request(monkeypatch, captured)
        result = extractor._llm_compare(["话术"], "消息", account_wxid="acct")
        assert result is not None
        assert "消息" in captured[0]["messages"][1]["content"]
