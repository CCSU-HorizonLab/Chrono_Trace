"""按联系人建议配置：settings 分键、缺省回落、旧全局键废弃不读。"""

import os
import sys


sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import app.services.realtime.monitor_service as msmod
from app.services.realtime.monitor_service import (
    SUGGESTION_CONFIG_DEFAULTS,
    load_suggestion_config_for_contact,
    suggestion_config_settings_key,
)


def test_settings_key_per_conversation():
    assert suggestion_config_settings_key(5) == "suggestion_config:5"
    assert suggestion_config_settings_key(0) == "suggestion_config:0"


def test_load_per_contact_overrides_defaults(monkeypatch):
    monkeypatch.setattr(msmod, "load_settings_from_file", lambda: {
        "suggestion_config:5": {"trigger_mode": "manual", "auto_rate_limit": "30", "bogus": 1},
    })
    config = load_suggestion_config_for_contact(5)
    assert config["trigger_mode"] == "manual"
    assert config["auto_rate_limit"] == 30      # 字符串数字归整
    assert "bogus" not in config                # 白名单外字段不进配置
    assert config["intent"] == SUGGESTION_CONFIG_DEFAULTS["intent"]


def test_missing_contact_falls_back_to_defaults(monkeypatch):
    monkeypatch.setattr(msmod, "load_settings_from_file", lambda: {})
    for conv_id in (0, 6):
        assert load_suggestion_config_for_contact(conv_id) == dict(SUGGESTION_CONFIG_DEFAULTS)


def test_legacy_global_key_not_read(monkeypatch):
    """旧全局键（顶层 trigger_mode/intent）已废弃：不进按联系人配置。"""
    monkeypatch.setattr(msmod, "load_settings_from_file", lambda: {
        "trigger_mode": "full_auto", "intent": "intimate",
    })
    assert load_suggestion_config_for_contact(7) == dict(SUGGESTION_CONFIG_DEFAULTS)
