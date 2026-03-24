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
from app.services.realtime.providers.factory import (
    RealtimeProviderFactory,
    normalize_listener_backend,
)
from app.services.realtime.providers.native_uia import (
    _classify_bubble_midpoint,
    _resolve_primary_active_midpoint,
)
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


def test_detector_maps_qt_window_to_405_profile_when_exe_matches_legacy_client():
    assert (
        _map_version_to_profile(
            "",
            68924,
            "Qt51514QWindowIcon",
            r"C:\Program Files\Tencent\WeChat\WeChat.exe",
        )
        == "wechat_405"
    )


def test_detector_maps_qt_window_to_41x_profile_when_exe_matches_weixin_client():
    assert (
        _map_version_to_profile(
            "",
            68924,
            "Qt51514QWindowIcon",
            r"D:\Program files\Weixin\Weixin.exe",
        )
        == "wechat_41x"
    )


def test_bubble_midpoint_classification_distinguishes_friend_self_and_center():
    width = 567
    assert _classify_bubble_midpoint(120, width) == "friend"
    assert _classify_bubble_midpoint(430, width) == "self"
    assert _classify_bubble_midpoint(285, width) == ""


def test_primary_active_midpoint_prefers_main_right_cluster_over_edge_noise():
    width = 723
    column_activity = [0] * width
    column_activity[0] = 70
    for index in range(500, 641):
        column_activity[index] = 45
    for index in range(660, 692):
        column_activity[index] = 24

    active_mid = _resolve_primary_active_midpoint(column_activity, width, active_threshold=7)

    assert active_mid is not None
    assert _classify_bubble_midpoint(active_mid, width) == "self"


def test_primary_active_midpoint_prefers_main_left_cluster_over_edge_noise():
    width = 723
    column_activity = [0] * width
    column_activity[0] = 70
    for index in range(27, 71):
        column_activity[index] = 43
    for index in range(104, 109):
        column_activity[index] = 16
    for index in range(125, 138):
        column_activity[index] = 13

    active_mid = _resolve_primary_active_midpoint(column_activity, width, active_threshold=7)

    assert active_mid is not None
    assert _classify_bubble_midpoint(active_mid, width) == "friend"


def test_normalize_listener_backend_maps_legacy_values_to_native_uia():
    assert normalize_listener_backend(None) == "native_uia"
    assert normalize_listener_backend("") == "native_uia"
    assert normalize_listener_backend("auto") == "native_uia"
    assert normalize_listener_backend("wxauto") == "native_uia"
    assert normalize_listener_backend("native_uia") == "native_uia"


def test_factory_auto_prefers_native_provider(monkeypatch):
    monkeypatch.setattr(
        "app.services.realtime.providers.factory.detect_running_wechat",
        lambda: WeChatVersionInfo(version="4.1.2.0", listener_profile="wechat_41x", hwnd=101),
    )

    def native_init(self):
        self.account_name = "native"

    monkeypatch.setattr(
        "app.services.realtime.providers.native_uia.NativeUIARealtimeProvider.initialize",
        native_init,
    )
    monkeypatch.setattr(
        "app.services.realtime.providers.factory.NativeUIARealtimeProvider.initialize",
        native_init,
    )

    provider = RealtimeProviderFactory.create("auto")

    assert provider.backend_name == "native_uia"
    assert provider.listener_profile == "wechat_41x"
    assert provider.wechat_version == "4.1.2.0"


def test_factory_legacy_wxauto_setting_still_resolves_to_native_provider(monkeypatch):
    monkeypatch.setattr(
        "app.services.realtime.providers.factory.detect_running_wechat",
        lambda: WeChatVersionInfo(version="4.0.5.18", listener_profile="wechat_405", hwnd=202),
    )

    def native_init(self):
        self.account_name = "native"

    monkeypatch.setattr(
        "app.services.realtime.providers.native_uia.NativeUIARealtimeProvider.initialize",
        native_init,
    )
    monkeypatch.setattr(
        "app.services.realtime.providers.factory.NativeUIARealtimeProvider.initialize",
        native_init,
    )

    provider = RealtimeProviderFactory.create("wxauto")

    assert provider.backend_name == "native_uia"
    assert provider.listener_profile == "wechat_405"
    assert provider.wechat_version == "4.0.5.18"


def test_factory_native_errors_are_not_silently_fallbacked(monkeypatch):
    monkeypatch.setattr(
        "app.services.realtime.providers.factory.detect_running_wechat",
        lambda: WeChatVersionInfo(version="4.1.2.0", listener_profile="wechat_41x", hwnd=202),
    )

    def native_init(self):
        raise UINotAccessibleError("ui_not_accessible")

    monkeypatch.setattr(
        "app.services.realtime.providers.native_uia.NativeUIARealtimeProvider.initialize",
        native_init,
    )
    monkeypatch.setattr(
        "app.services.realtime.providers.factory.NativeUIARealtimeProvider.initialize",
        native_init,
    )

    try:
        RealtimeProviderFactory.create("auto")
    except UINotAccessibleError as exc:
        assert "ui_not_accessible" in str(exc)
    else:
        raise AssertionError("Expected UINotAccessibleError")


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
