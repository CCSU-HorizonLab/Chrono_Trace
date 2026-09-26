"""Tests for realtime provider selection and compatibility shims."""

from __future__ import annotations

import os
import sys
from types import SimpleNamespace

import pytest


sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.realtime.providers.base import (
    ProviderInitError,
    UINotAccessibleError,
    UnsupportedWeChatVersionError,
)
from app.services.realtime.providers.detector import _map_version_to_profile
from app.services.realtime.providers.factory import (
    RealtimeProviderFactory,
    normalize_listener_backend,
)
from app.services.realtime.providers.native_uia import (
    NativeUIARealtimeProvider,
    _classify_bubble_midpoint,
    _merge_rect_clusters,
    _resolve_primary_active_midpoint,
)
from app.services.realtime.providers.models import (
    RealtimeMessage,
    WeChatVersionInfo,
    build_message_hash,
)


class _FakeUIAItem:
    def __init__(
        self,
        class_name: str,
        control_type: str = "Pane",
        automation_id: str = "",
        visible: bool = True,
        text: str = "",
        rect: tuple[int, int, int, int] = (0, 0, 0, 0),
        children: list | None = None,
    ):
        self._class_name = class_name
        self._visible = visible
        self._text = text
        self._rect = SimpleNamespace(left=rect[0], top=rect[1], right=rect[2], bottom=rect[3])
        self._children = list(children or [])
        self.element_info = SimpleNamespace(
            control_type=control_type,
            automation_id=automation_id,
        )

    def is_visible(self):
        return self._visible

    def class_name(self):
        return self._class_name

    def window_text(self):
        return self._text

    def rectangle(self):
        return self._rect

    def children(self, control_type=None):
        if control_type is None:
            return list(self._children)
        return [
            child
            for child in self._children
            if getattr(getattr(child, "element_info", None), "control_type", None) == control_type
        ]


class _FakeUIAWindow:
    def __init__(self, descendants):
        self._descendants = list(descendants)

    def descendants(self, **_kwargs):
        return list(self._descendants)


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


@pytest.mark.skipif(sys.platform != "win32", reason="win32 窗口探测专属")
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


@pytest.mark.skipif(sys.platform != "win32", reason="win32 窗口探测专属")
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


def test_merge_rect_clusters_combines_nearby_spans_and_preserves_distant_noise():
    clusters = _merge_rect_clusters(
        [
            (32, 84, 400),
            (92, 226, 1800),
            (468, 486, 120),
        ],
        gap_tolerance=18,
    )

    assert clusters == [
        (32, 226, 2200),
        (468, 486, 120),
    ]


def test_normalize_listener_backend_maps_legacy_values_to_native_uia():
    # 平台默认：Windows native_uia，Linux db_watch（阶段三移植）
    expected_default = "native_uia" if sys.platform == "win32" else "db_watch"
    assert normalize_listener_backend(None) == expected_default
    assert normalize_listener_backend("") == expected_default
    # auto/wxauto 收敛到平台默认（Linux=db_watch——此前硬编码 native_uia 导致错路由）
    assert normalize_listener_backend("auto") == expected_default
    assert normalize_listener_backend("wxauto") == expected_default
    assert normalize_listener_backend("native_uia") == "native_uia"
    assert normalize_listener_backend("db_watch") == "db_watch"


@pytest.mark.skipif(sys.platform != 'win32', reason='auto/wxauto 在 Linux 收敛 db_watch')
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


@pytest.mark.skipif(sys.platform != 'win32', reason='auto/wxauto 在 Linux 收敛 db_watch')
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


@pytest.mark.skipif(sys.platform != 'win32', reason='auto/wxauto 在 Linux 收敛 db_watch')
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


def test_native_provider_rejects_shell_only_uia_tree():
    provider = NativeUIARealtimeProvider("wechat_41x", wechat_version="4.1.8.29", hwnd=101)
    provider._main_window = _FakeUIAWindow(
        [
            _FakeUIAItem("Qt51514QWindowIcon"),
            _FakeUIAItem("MMUIRenderSubWindowHW"),
        ]
    )

    with pytest.raises(UINotAccessibleError, match="ui_not_accessible"):
        provider._ensure_accessible_tree(attempts=1, delay=0.0)


def test_native_provider_accepts_meaningful_uia_descendant_beside_shell_panes():
    provider = NativeUIARealtimeProvider("wechat_41x", wechat_version="4.1.8.29", hwnd=101)
    provider._main_window = _FakeUIAWindow(
        [
            _FakeUIAItem("Qt51514QWindowIcon"),
            _FakeUIAItem("MMUIRenderSubWindowHW"),
            _FakeUIAItem("Edit", control_type="Edit", automation_id="search_input"),
        ]
    )

    provider._ensure_accessible_tree(attempts=1, delay=0.0)


def test_native_provider_open_chat_requires_expected_header_confirmation(monkeypatch):
    provider = NativeUIARealtimeProvider("wechat_41x", wechat_version="4.1.8.29", hwnd=101)
    provider._main_window = object()

    class _FakeSessionEntry:
        def click_input(self):
            return True

    monkeypatch.setattr(provider, "_ensure_accessible_tree", lambda *args, **kwargs: None)
    monkeypatch.setattr(provider, "activate_main_window", lambda: True)
    monkeypatch.setattr(provider, "_find_session_entry", lambda display_name: _FakeSessionEntry())
    monkeypatch.setattr(provider, "_find_chat_list", lambda: object())
    monkeypatch.setattr(provider, "_iter_direct_chat_items", lambda: [object()])
    monkeypatch.setattr(provider, "_refresh_chat_rect", lambda items=None: None)
    monkeypatch.setattr(provider, "_is_target_chat_active", lambda display_name: False)
    monkeypatch.setattr(provider, "_visible_header_texts", lambda: ["ss"])
    monkeypatch.setattr("app.services.realtime.providers.native_uia.time.sleep", lambda _seconds: None)

    with pytest.raises(ProviderInitError, match="Unable to confirm target chat '昕（农1.10）'"):
        provider.open_chat("昕", expected_display_name="昕（农1.10）")


def test_native_provider_find_search_edit_skips_chat_input_and_prefers_left_search_box(monkeypatch):
    provider = NativeUIARealtimeProvider("wechat_41x", wechat_version="4.1.8.29", hwnd=101)
    session_list = _FakeUIAItem(
        "mmui::XTableView",
        control_type="List",
        automation_id="session_list",
        text="会话",
        rect=(338, 242, 638, 972),
    )
    search_edit = _FakeUIAItem(
        "mmui::XValidatorTextEdit",
        control_type="Edit",
        rect=(388, 200, 573, 225),
    )
    chat_input = _FakeUIAItem(
        "mmui::ChatInputField",
        control_type="Edit",
        automation_id="chat_input_field",
        rect=(665, 835, 1343, 907),
    )
    monkeypatch.setattr(provider, "_visible_descendants", lambda control_type=None: [chat_input, search_edit] if control_type == "Edit" else [])
    monkeypatch.setattr(provider, "_find_session_list", lambda: session_list)

    result = provider._find_search_edit()

    assert result is search_edit


def test_native_provider_focus_search_does_not_blind_type_when_search_edit_is_missing(monkeypatch):
    provider = NativeUIARealtimeProvider("wechat_41x", wechat_version="4.1.8.29", hwnd=101)
    calls = []

    def fake_send_keys(keys, **kwargs):
        calls.append((keys, kwargs))

    monkeypatch.setattr(provider, "_import_backend", lambda: (object(), fake_send_keys))
    monkeypatch.setattr(provider, "activate_main_window", lambda: True)
    monkeypatch.setattr(provider, "_find_search_edit", lambda: None)
    monkeypatch.setattr("app.services.realtime.providers.native_uia.time.sleep", lambda _seconds: None)

    result = provider._focus_search_and_open("昕农110")

    assert result is False
    assert [item[0] for item in calls] == ["^f"]


def test_native_provider_find_session_entry_uses_session_list_instead_of_chat_bubble(monkeypatch):
    provider = NativeUIARealtimeProvider("wechat_41x", wechat_version="4.1.8.29", hwnd=101)
    session_item = _FakeUIAItem(
        "mmui::ChatSessionCell",
        control_type="ListItem",
        automation_id="session_item_昕（农1.10）",
        text="昕（农1.10） 已置顶 [动画表情] 昨天 18:12",
        rect=(338, 322, 638, 402),
    )
    monkeypatch.setattr(provider, "_iter_session_items", lambda: [session_item])

    result = provider._find_session_entry("昕（农1.10）")

    assert result is session_item


def test_native_provider_recall_notice_does_not_replace_current_time_label(monkeypatch):
    provider = NativeUIARealtimeProvider("wechat_41x", wechat_version="4.1.8.29", hwnd=101)

    class _FakeChatItem:
        def __init__(self, text: str, class_name: str, runtime_id: str):
            self._text = text
            self._class_name = class_name
            self.element_info = SimpleNamespace(runtime_id=runtime_id)

        def class_name(self):
            return self._class_name

        def window_text(self):
            return self._text

    items = [
        _FakeChatItem("12:28", "mmui::ChatTimeSeparator", "rt-1"),
        _FakeChatItem("你撤回了一条消息 重新编辑", "mmui::ChatSystemNotice", "rt-2"),
        _FakeChatItem("今天晚上", "mmui::ChatBubbleItemView", "rt-3"),
    ]

    monkeypatch.setattr(provider, "_iter_chat_items", lambda: items)
    monkeypatch.setattr(provider, "_resolve_sender_attr", lambda item: "" if "System" in item.class_name() or "Time" in item.class_name() else "self")
    monkeypatch.setattr(provider, "_resolve_message_type", lambda class_name, text: "system" if "System" in class_name or "Time" in class_name else "text")

    messages = provider.list_visible_messages()

    assert len(messages) == 3
    assert messages[0].is_system is True
    assert messages[0].time == "12:28"
    assert messages[1].is_system is True
    assert messages[1].content == "你撤回了一条消息 重新编辑"
    assert messages[1].time == "12:28"
    assert messages[2].time == "12:28"


def test_native_provider_red_packet_receive_notice_is_treated_as_system_message(monkeypatch):
    provider = NativeUIARealtimeProvider("wechat_41x", wechat_version="4.1.8.29", hwnd=101)

    class _FakeChatItem:
        def __init__(self, text: str, class_name: str, runtime_id: str):
            self._text = text
            self._class_name = class_name
            self.element_info = SimpleNamespace(runtime_id=runtime_id)

        def class_name(self):
            return self._class_name

        def window_text(self):
            return self._text

    items = [
        _FakeChatItem("20:07", "mmui::ChatTimeSeparator", "rt-1"),
        _FakeChatItem("你领取了听（农1.10）的红包", "mmui::ChatBubbleItemView", "rt-2"),
        _FakeChatItem("我是殷杰", "mmui::ChatBubbleItemView", "rt-3"),
    ]

    monkeypatch.setattr(provider, "_iter_chat_items", lambda: items)
    monkeypatch.setattr(provider, "_resolve_sender_attr", lambda item: "self")
    monkeypatch.setattr(provider, "_resolve_message_type", lambda class_name, text: "text")

    messages = provider.list_visible_messages()

    assert len(messages) == 3
    assert messages[1].is_system is True
    assert messages[1].sender_attr == "system"
    assert messages[1].content == "你领取了听（农1.10）的红包"
    assert messages[1].time == "20:07"
    assert messages[2].is_system is False


def test_native_provider_resolve_sender_prefers_informative_descendants_over_full_row(monkeypatch):
    provider = NativeUIARealtimeProvider("wechat_41x", wechat_version="4.1.8.29", hwnd=101)
    provider._chat_rect = (0, 0, 1000, 800)

    class _Rect:
        def __init__(self, left: int, right: int, top: int = 0, bottom: int = 80):
            self.left = left
            self.right = right
            self.top = top
            self.bottom = bottom

    class _Node:
        def __init__(self, left: int, right: int):
            self._rect = _Rect(left, right)

        def is_visible(self):
            return True

        def rectangle(self):
            return self._rect

    class _Item:
        def descendants(self):
            return [
                _Node(0, 1000),   # full-row container, should be ignored
                _Node(640, 930),  # actual right-side bubble span
            ]

        def rectangle(self):
            return _Rect(0, 1000)

    screenshot_calls = {"count": 0}

    def fake_screenshot(_item):
        screenshot_calls["count"] += 1
        return ""

    monkeypatch.setattr(provider, "_resolve_sender_attr_from_screenshot", fake_screenshot)

    sender_attr = provider._resolve_sender_attr(_Item())

    assert sender_attr == "self"
    assert screenshot_calls["count"] == 0


def test_native_provider_resolve_sender_prefers_left_dominant_cluster_over_right_noise(monkeypatch):
    provider = NativeUIARealtimeProvider("wechat_41x", wechat_version="4.1.8.29", hwnd=101)
    provider._chat_rect = (0, 0, 1000, 800)

    class _Rect:
        def __init__(self, left: int, right: int, top: int = 0, bottom: int = 80):
            self.left = left
            self.right = right
            self.top = top
            self.bottom = bottom

    class _Node:
        def __init__(self, left: int, right: int, top: int = 0, bottom: int = 80):
            self._rect = _Rect(left, right, top, bottom)

        def is_visible(self):
            return True

        def rectangle(self):
            return self._rect

    class _Item:
        def descendants(self):
            return [
                _Node(0, 1000, 0, 80),   # full-row container
                _Node(40, 92, 12, 64),   # avatar
                _Node(104, 262, 12, 68), # left bubble
                _Node(868, 892, 18, 36), # tiny right noise
            ]

        def rectangle(self):
            return _Rect(0, 1000)

    screenshot_calls = {"count": 0}

    def fake_screenshot(_item):
        screenshot_calls["count"] += 1
        return ""

    monkeypatch.setattr(provider, "_resolve_sender_attr_from_screenshot", fake_screenshot)

    sender_attr = provider._resolve_sender_attr(_Item())

    assert sender_attr == "friend"
    assert screenshot_calls["count"] == 0


def test_native_provider_sender_screenshot_uses_all_screens(monkeypatch):
    provider = NativeUIARealtimeProvider("wechat_41x", wechat_version="4.1.8.29", hwnd=101)

    class _Rect:
        left = -1200
        top = 100
        right = -900
        bottom = 180

    class _Item:
        def rectangle(self):
            return _Rect()

    class _FakeImage:
        def convert(self, _mode):
            return self

        def getpixel(self, pos):
            x, _y = pos
            if 210 <= x <= 250:
                return (120, 210, 110)
            return (245, 245, 245)

    calls = []

    def fake_grab(**kwargs):
        calls.append(kwargs)
        return _FakeImage()

    monkeypatch.setattr("PIL.ImageGrab.grab", fake_grab)

    sender_attr = provider._resolve_sender_attr_from_screenshot(_Item())

    assert sender_attr == "self"
    assert calls[0]["all_screens"] is True


@pytest.mark.skipif(sys.platform != 'win32', reason='版本门禁属 native_uia 路径')
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
