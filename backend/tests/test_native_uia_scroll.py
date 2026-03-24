"""Regression tests for native UIA backfill scrolling granularity."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.realtime.providers.native_uia import NativeUIARealtimeProvider


class FakeChatList:
    def __init__(self, fail_scroll=False, fail_wheel=False):
        self.fail_scroll = fail_scroll
        self.fail_wheel = fail_wheel
        self.calls = []

    def scroll(self, direction, amount, count=1, retry_interval=0.1):
        self.calls.append(("scroll", direction, amount, count))
        if self.fail_scroll:
            raise RuntimeError("scroll unavailable")
        return self

    def wheel_mouse_input(self, wheel_dist=1):
        self.calls.append(("wheel", wheel_dist))
        if self.fail_wheel:
            raise RuntimeError("wheel unavailable")
        return self

    def type_keys(self, keys, pause=0.05):
        self.calls.append(("type_keys", keys))
        return self


def test_native_uia_scroll_up_prefers_line_scroll_over_page_jump():
    provider = NativeUIARealtimeProvider(listener_profile="wechat_41x")
    provider._chat_list = FakeChatList()

    assert provider.scroll_up(wheel_times=3) is True
    assert provider._chat_list.calls[0] == ("scroll", "up", "line", 3)
    assert all(call[0] != "type_keys" for call in provider._chat_list.calls)


def test_native_uia_scroll_down_prefers_line_scroll_over_page_jump():
    provider = NativeUIARealtimeProvider(listener_profile="wechat_41x")
    provider._chat_list = FakeChatList()

    assert provider.scroll_down(wheel_times=2) is True
    assert provider._chat_list.calls[0] == ("scroll", "down", "line", 2)
    assert all(call[0] != "type_keys" for call in provider._chat_list.calls)


def test_native_uia_scroll_up_falls_back_to_page_only_after_line_and_wheel_fail():
    provider = NativeUIARealtimeProvider(listener_profile="wechat_41x")
    provider._chat_list = FakeChatList(fail_scroll=True, fail_wheel=True)

    assert provider.scroll_up(wheel_times=1) is True
    assert provider._chat_list.calls == [
        ("scroll", "up", "line", 1),
        ("wheel", 1),
        ("type_keys", "{PGUP}"),
    ]
