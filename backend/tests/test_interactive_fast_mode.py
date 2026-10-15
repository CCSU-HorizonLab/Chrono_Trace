"""交互调用快速模式测试：reasoning_effort 默认/开关/extra_body 优先级，
/no_think 旧 Qwen3 门控，及四条交互链路的 payload 接线。"""

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.realtime.llm_http import (
    apply_deep_call_effort,
    apply_interactive_fast_mode,
    interactive_fast_mode_enabled,
    is_legacy_qwen3,
    is_reasoning_model,
)


# ===== 判定 =====


def test_is_reasoning_model_tags():
    assert is_reasoning_model("Qwen3.5-9B")
    assert is_reasoning_model("deepseek-r1")
    assert is_reasoning_model("qwq-32b")
    assert not is_reasoning_model("deepseek-chat")
    assert not is_reasoning_model("qwen2.5:7b")
    assert not is_reasoning_model("")


def test_is_legacy_qwen3_only_30_series():
    assert is_legacy_qwen3("qwen3-235b-a22b")
    assert is_legacy_qwen3("Qwen3-Coder-30B")
    assert not is_legacy_qwen3("qwen3.5-9b")
    assert not is_legacy_qwen3("qwen3.6-72b")
    assert not is_legacy_qwen3("deepseek-r1")


# ===== 快速模式参数合并 =====


@pytest.fixture(autouse=True)
def _hermetic_settings(monkeypatch):
    """隔离真实设置文件：默认设置下开关为开（真机上用户可能关过）。"""
    import app.services.wechat.account_settings as account_settings

    monkeypatch.setattr(account_settings, "load_settings_from_file", lambda: {})


def _config(model_id="qwen3.5-9b", extra_body=None):
    cfg = {"model_id": model_id}
    if extra_body is not None:
        cfg["extra_body"] = extra_body
    return cfg


def test_fast_mode_default_low_for_reasoning_model():
    payload = apply_interactive_fast_mode({}, _config())
    assert payload["reasoning_effort"] == "low"


def test_fast_mode_skips_non_reasoning_model():
    payload = apply_interactive_fast_mode({}, _config(model_id="deepseek-chat"))
    assert "reasoning_effort" not in payload


def test_fast_mode_respects_off_switch(monkeypatch):
    import app.services.wechat.account_settings as account_settings

    monkeypatch.setattr(
        account_settings,
        "load_settings_from_file",
        lambda: {"llm_fast_suggestion_mode": False},
    )
    assert interactive_fast_mode_enabled() is False
    payload = apply_interactive_fast_mode({}, _config())
    assert "reasoning_effort" not in payload


def test_fast_mode_extra_body_wins_over_default():
    payload = apply_interactive_fast_mode(
        {},
        _config(extra_body='{"reasoning_effort": "high", "reasoning_budget_tokens": 2048}'),
    )
    assert payload["reasoning_effort"] == "high"
    assert payload["reasoning_budget_tokens"] == 2048


def test_fast_mode_invalid_extra_body_ignored():
    payload = apply_interactive_fast_mode({}, _config(extra_body="{不是json"))
    assert payload["reasoning_effort"] == "low"  # 非法 JSON 不炸，回落默认


def test_fast_mode_non_dict_extra_body_ignored():
    payload = apply_interactive_fast_mode({}, _config(extra_body='["a", 1]'))
    assert payload == {"reasoning_effort": "low"}


# ===== 深度调用定档：RAG 事实抽取 / 关系评估 =====


def test_deep_call_effort_medium_not_gated_by_fast_mode(monkeypatch):
    """深度链路固定 medium：快速模式开关关闭也不回落网关默认档。"""
    import app.services.wechat.account_settings as account_settings

    monkeypatch.setattr(
        account_settings,
        "load_settings_from_file",
        lambda: {"llm_fast_suggestion_mode": False},
    )
    payload = apply_deep_call_effort({}, _config())
    assert payload["reasoning_effort"] == "medium"


def test_deep_call_effort_skips_non_reasoning_and_respects_extra_body():
    assert "reasoning_effort" not in apply_deep_call_effort({}, _config(model_id="deepseek-chat"))
    payload = apply_deep_call_effort(
        {}, _config(extra_body='{"reasoning_effort": "high"}')
    )
    assert payload["reasoning_effort"] == "high"


def test_relationship_llm_payload_carries_medium():
    from app.services.analysis.relationship_llm_service import RelationshipLLMService

    calls = []

    def fake_http(**kw):
        calls.append(kw["payload"])
        return {"choices": [{"message": {"content": "{}"}}]}

    svc = RelationshipLLMService(
        {"api_base_url": "http://127.0.0.1:11434/v1", "model_id": "qwen3.5-9b", "api_key": ""},
        http=fake_http,
    )
    svc._call_chat([{"role": "user", "content": "评估"}])

    assert calls[0]["reasoning_effort"] == "medium"


def test_rag_fact_llm_payload_carries_medium(monkeypatch):
    import app.services.realtime.rag.fact_llm as factllm

    calls = []

    def fake_post(**kw):
        calls.append(kw["payload"])
        return {"choices": [{"message": {"content": "{}"}}]}

    monkeypatch.setattr(factllm, "post_json_with_retries", fake_post)

    adapter = factllm.LLMFactExtractorAdapter(
        {"api_base_url": "http://127.0.0.1:11434/v1", "model_id": "qwen3.5-9b", "api_key": ""}
    )
    adapter._call_chat([{"role": "user", "content": "抽取"}], max_tokens=6144)

    assert calls[0]["reasoning_effort"] == "medium"


# ===== 接线：群日报 =====


def test_group_summary_payload_carries_fast_mode(monkeypatch):
    import app.services.analysis.group_summary_service as gsmod

    calls = []

    def fake_post(**kw):
        calls.append(kw["payload"])
        return {"choices": [{"message": {"content": "1. 主要话题：测试"}}]}

    monkeypatch.setattr(gsmod, "post_json_with_retries", fake_post)

    text = gsmod.GroupSummaryService._call_llm(
        {"api_base_url": "http://127.0.0.1:11434/v1", "model_id": "qwen3.5-9b", "api_key": ""},
        days=7,
        lines=["2026-10-14", "阿强: 样本"],
        conversation_id=1,
    )

    assert "主要话题" in text
    assert calls[0]["reasoning_effort"] == "low"


def test_group_summary_payload_respects_extra_body(monkeypatch):
    import app.services.analysis.group_summary_service as gsmod

    calls = []

    def fake_post(**kw):
        calls.append(kw["payload"])
        return {"choices": [{"message": {"content": "ok"}}]}

    monkeypatch.setattr(gsmod, "post_json_with_retries", fake_post)

    gsmod.GroupSummaryService._call_llm(
        {
            "api_base_url": "http://127.0.0.1:11434/v1",
            "model_id": "qwen3.5-9b",
            "api_key": "",
            "extra_body": '{"reasoning_budget_tokens": 4096}',
        },
        days=1,
        lines=["样本"],
        conversation_id=1,
    )

    assert calls[0]["reasoning_effort"] == "low"
    assert calls[0]["reasoning_budget_tokens"] == 4096


# ===== 接线：问问微信 =====


def test_history_qa_payload_carries_fast_mode(monkeypatch):
    import app.services.analysis.history_qa_service as hqmod
    import app.services.realtime.rag.fact_llm as factllm

    monkeypatch.setattr(
        factllm,
        "get_active_model_config",
        lambda: {"api_base_url": "http://127.0.0.1:11434/v1", "model_id": "qwen3.5-9b", "api_key": ""},
    )

    calls = []

    def fake_post(**kw):
        calls.append(kw["payload"])
        return {"choices": [{"message": {"content": "回答[1]"}}]}

    monkeypatch.setattr(hqmod, "post_json_with_retries", fake_post)

    records = [{"message_id": 1, "timestamp": 1700000000, "is_sender": 0, "text": "样本"}]
    answer = hqmod.HistoryQAService()._call_llm(1, "问什么", records)

    assert answer == "回答[1]"
    assert calls[0]["reasoning_effort"] == "low"


# ===== 接线：实时建议（llm_client） =====


@pytest.fixture
def engine():
    from app.services.realtime.llm_engine import LLMSuggestionEngine

    return LLMSuggestionEngine()


def _fake_urlopen_factory(captured):
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
                        {"message": {"content": '{"reply":"","thought_process":"ok","summary":"ok","speeches":["hi"]}'}}
                    ],
                    "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
                }
            ).encode("utf-8")

    def fake_urlopen(req, timeout=0):
        captured["payload"] = json.loads(req.data.decode("utf-8"))
        return DummyResponse()

    return fake_urlopen


def test_suggestion_call_payload_and_nothink_gating(monkeypatch, engine):
    captured = {}
    monkeypatch.setattr("urllib.request.urlopen", _fake_urlopen_factory(captured))
    monkeypatch.setattr(engine, "_validate_model_id", lambda model_id, base_url, api_key="": model_id)
    monkeypatch.setattr(engine, "_supports_json_mode", lambda cfg, url: False)

    base_cfg = {"api_base_url": "http://192.168.103.112:8004/v1", "api_key": "", "max_tokens": 256}

    # Qwen3.5：请求参数走 reasoning_effort=low，system 不再前置 /no_think
    engine._call_api({**base_cfg, "model_id": "qwen3.5-9b"}, "测试")
    assert captured["payload"]["reasoning_effort"] == "low"
    assert not captured["payload"]["messages"][0]["content"].startswith("/no_think")

    # 旧 Qwen3（3.0 系）：保留 /no_think 兼容
    engine._call_api({**base_cfg, "model_id": "qwen3-235b-a22b"}, "测试")
    assert captured["payload"]["messages"][0]["content"].startswith("/no_think")

    # 非思考模型：两个通道都不触发
    engine._call_api({**base_cfg, "model_id": "deepseek-chat"}, "测试")
    assert "reasoning_effort" not in captured["payload"]
    assert not captured["payload"]["messages"][0]["content"].startswith("/no_think")
