"""Tests for the project-local wxauto4 compatibility shim."""

from __future__ import annotations

import os
import sys


sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import wxauto4 as wxauto4_module

from wxauto4 import WeChat


class FakeProvider:
    backend_name = "native_uia"
    listener_profile = "wechat_41x"
    wechat_version = "4.1.3.0"
    account_name = "tester"

    def __init__(self):
        self.opened = []
        self.scrolled_up = []
        self.scrolled_down = []

    def get_hwnd(self):
        return 99

    def open_chat(self, display_name):
        self.opened.append(display_name)
        return True

    def list_visible_messages(self):
        return ["m1", "m2"]

    def scroll_up(self, wheel_times=2):
        self.scrolled_up.append(wheel_times)
        return True

    def scroll_down(self, wheel_times=4):
        self.scrolled_down.append(wheel_times)
        return True

    def close(self):
        return None


def test_local_wxauto4_shim_delegates_to_provider(monkeypatch):
    provider = FakeProvider()
    monkeypatch.setattr(wxauto4_module.RealtimeProviderFactory, "create", lambda backend=None: provider)

    wx = WeChat(start_listener=False)

    assert wx.backend_name == "native_uia"
    assert wx.listener_profile == "wechat_41x"
    assert wx.wechat_version == "4.1.3.0"
    assert wx.nickname == "tester"
    assert wx._api.HWND == 99

    assert wx.ChatWith("Alice") is True
    assert provider.opened == ["Alice"]
    assert wx.GetAllMessage() == ["m1", "m2"]
    assert wx.ChatBox.msgbox.WheelUp(wheelTimes=3) is True
    assert wx.ChatBox.msgbox.WheelDown(wheelTimes=5) is True
    assert provider.scrolled_up == [3]
    assert provider.scrolled_down == [5]
