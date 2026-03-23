"""Tests for realtime provider selection and compatibility shims."""

from __future__ import annotations

import os
import sys


sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.realtime.providers.base import (
    UINotAccessibleError,
    UnsupportedWeChatVersionError,
)
from app.services.realtime.providers.detector import _map_version_to_profile
from app.services.realtime.providers.factory import RealtimeProviderFactory
from app.services.realtime.providers.native_uia import _classify_bubble_midpoint
from app.services.realtime.providers.models import (
    RealtimeMessage,
    WeChatVersionInfo,
    build_message_hash,
)


def test_build_message_hash_is_stable():
    first = build_message_hash(
        "wechat_41x",
        "friend",
        "text",
        "  hello   world ",
        123,
        "abc",
    )
    second = build_message_hash(
        "wechat_41x",
        "friend",
        "text",
        "hello world",
        123,
        "abc",
    )
    third = build_message_hash(
        "wechat_41x",
        "friend",
        "text",
        "hello world",
        124,
        "abc",
    )

    assert first == second
    assert first != third


def test_realtime_message_exposes_compatibility_properties():
    msg = RealtimeMessage(
        runtime_id="r1",
        sender_attr="self",
        content="hi",
        message_type="text",
        timestamp_label="12:34",
        timestamp=1234,
        message_hash="hash1",
    )

    assert msg.id == "r1"
    assert msg.hash == "hash1"
    assert msg.type == "text"
    assert msg.time == "12:34"
    assert msg.CreateTime == "12:34"
    assert msg.is_self is True


def test_detector_maps_qt_window_to_405_profile():
    assert _map_version_to_profile("4.0.5.23", 68924, "Qt51514QWindowIcon") == "wechat_405"


def test_bubble_midpoint_classification_distinguishes_friend_self_and_center():
    width = 567
    assert _classify_bubble_midpoint(120, width) == "friend"
    assert _classify_bubble_midpoint(430, width) == "self"
    assert _classify_bubble_midpoint(285, width) == ""


def test_factory_auto_prefers_native_provider(monkeypatch):
    monkeypatch.setattr(
        "app.services.realtime.providers.factory.detect_running_wechat",
        lambda: WeChatVersionInfo(version="4.1.2.0", listener_profile="wechat_41x", hwnd=101),
    )

    def native_init(self):
        self.account_name = "native"

    def wxauto_init(self):
        raise AssertionError("wxauto fallback should not be used")

    monkeypatch.setattr(
        "app.services.realtime.providers.native_uia.NativeUIARealtimeProvider.initialize",
        native_init,
    )
    monkeypatch.setattr(
        "app.services.realtime.providers.factory.NativeUIARealtimeProvider.initialize",
        native_init,
    )
    monkeypatch.setattr(
        "app.services.realtime.providers.wxauto_provider.WxautoRealtimeProvider.initialize",
        wxauto_init,
    )
    monkeypatch.setattr(
        "app.services.realtime.providers.factory.WxautoRealtimeProvider.initialize",
        wxauto_init,
    )

    provider = RealtimeProviderFactory.create("auto")

    assert provider.backend_name == "native_uia"
    assert provider.listener_profile == "wechat_41x"
    assert provider.wechat_version == "4.1.2.0"


def test_factory_auto_falls_back_to_wxauto(monkeypatch):
    monkeypatch.setattr(
        "app.services.realtime.providers.factory.detect_running_wechat",
        lambda: WeChatVersionInfo(version="4.0.5.18", listener_profile="wechat_405", hwnd=202),
    )

    def native_init(self):
        raise UINotAccessibleError("ui_not_accessible")

    def wxauto_init(self):
        self.account_name = "fallback"

    monkeypatch.setattr(
        "app.services.realtime.providers.native_uia.NativeUIARealtimeProvider.initialize",
        native_init,
    )
    monkeypatch.setattr(
        "app.services.realtime.providers.factory.NativeUIARealtimeProvider.initialize",
        native_init,
    )
    monkeypatch.setattr(
        "app.services.realtime.providers.wxauto_provider.WxautoRealtimeProvider.initialize",
        wxauto_init,
    )
    monkeypatch.setattr(
        "app.services.realtime.providers.factory.WxautoRealtimeProvider.initialize",
        wxauto_init,
    )

    provider = RealtimeProviderFactory.create("auto")

    assert provider.backend_name == "wxauto"
    assert provider.listener_profile == "wechat_405"
    assert provider.wechat_version == "4.0.5.18"


def test_factory_rejects_unsupported_versions(monkeypatch):
    monkeypatch.setattr(
        "app.services.realtime.providers.factory.detect_running_wechat",
        lambda: WeChatVersionInfo(version="3.9.12.1", listener_profile="", hwnd=303),
    )

    try:
        RealtimeProviderFactory.create("auto")
    except UnsupportedWeChatVersionError as exc:
        assert "unsupported_wechat_version" in str(exc)
    else:
        raise AssertionError("Expected UnsupportedWeChatVersionError")
