"""Tests for WeChat UIA debug helpers."""

from __future__ import annotations

import os
import sys


sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.realtime.providers.debug_tools import (
    collect_visible_item_diagnostics,
    serialize_control_tree,
)
from app.webview.bridge import Bridge


class FakeRect:
    def __init__(self, left: int, top: int, right: int, bottom: int):
        self.left = left
        self.top = top
        self.right = right
        self.bottom = bottom


class FakeElementInfo:
    def __init__(self, control_type: str, automation_id: str, runtime_id: list[int]):
        self.control_type = control_type
        self.automation_id = automation_id
        self.runtime_id = runtime_id


class FakeNode:
    def __init__(
        self,
        name: str,
        control_type: str,
        class_name: str,
        automation_id: str,
        runtime_id: list[int],
        rect: FakeRect,
        children: list["FakeNode"] | None = None,
        visible: bool = True,
    ):
        self._name = name
        self._class_name = class_name
        self._children = children or []
        self._visible = visible
        self._rect = rect
        self.element_info = FakeElementInfo(control_type, automation_id, runtime_id)

    def window_text(self):
        return self._name

    def class_name(self):
        return self._class_name

    def children(self):
        return list(self._children)

    def rectangle(self):
        return self._rect

    def is_visible(self):
        return self._visible


class FakeProvider:
    def __init__(self, items):
        self._items = items

    def _iter_chat_items(self):
        return list(self._items)

    def _looks_like_system_item(self, item, text, class_name):
        del item, class_name
        return text.endswith("14:08")

    def _resolve_sender_attr(self, item):
        return getattr(item, "_sender_attr", "")

    def _resolve_message_type(self, class_name, text):
        del class_name
        return "file" if "文件" in text else "text"


def test_serialize_control_tree_includes_metadata_and_children():
    child = FakeNode(
        name="Chat List",
        control_type="List",
        class_name="ChatListView",
        automation_id="chat-list",
        runtime_id=[1, 2],
        rect=FakeRect(10, 20, 200, 400),
    )
    root = FakeNode(
        name="WeChat",
        control_type="Window",
        class_name="WeChatMainWndForPC",
        automation_id="main-window",
        runtime_id=[1],
        rect=FakeRect(0, 0, 800, 600),
        children=[child],
    )

    payload = serialize_control_tree(root, max_depth=3, max_nodes=10)

    assert payload["name"] == "WeChat"
    assert payload["control_type"] == "Window"
    assert payload["class_name"] == "WeChatMainWndForPC"
    assert payload["automation_id"] == "main-window"
    assert payload["runtime_id"] == [1]
    assert payload["rectangle"]["right"] == 800
    assert payload["children"][0]["name"] == "Chat List"
    assert payload["children"][0]["runtime_id"] == [1, 2]


def test_collect_visible_item_diagnostics_includes_sender_and_system_info():
    system_item = FakeNode(
        name="2025年12月17日 14:08",
        control_type="ListItem",
        class_name="mmui::ChatItemView",
        automation_id="",
        runtime_id=[42, 1],
        rect=FakeRect(0, 0, 120, 24),
    )
    message_item = FakeNode(
        name="文件 测试.txt 1.0K",
        control_type="ListItem",
        class_name="mmui::ChatBubbleItemView",
        automation_id="",
        runtime_id=[42, 2],
        rect=FakeRect(50, 30, 220, 80),
    )
    message_item._sender_attr = "self"

    diagnostics = collect_visible_item_diagnostics(FakeProvider([system_item, message_item]))

    assert diagnostics[0]["is_system"] is True
    assert diagnostics[0]["sender_attr"] == "system"
    assert diagnostics[1]["is_system"] is False
    assert diagnostics[1]["sender_attr"] == "self"
    assert diagnostics[1]["message_type"] == "file"
    assert diagnostics[1]["timestamp_label"] == "2025年12月17日 14:08"


def test_bridge_debug_dump_wechat_uia_delegates_to_snapshot_builder(monkeypatch):
    bridge = Bridge.__new__(Bridge)
    captured = {}

    def fake_dump(talker_display_name: str, max_depth: int, max_nodes: int):
        captured["talker_display_name"] = talker_display_name
        captured["max_depth"] = max_depth
        captured["max_nodes"] = max_nodes
        return {
            "path": "backend/data/logs/wechat_uia_dump_test.json",
            "messages": [{"content": "hello"}],
            "tree": {"name": "WeChat"},
            "errors": [],
        }

    monkeypatch.setattr(
        "app.services.realtime.providers.debug_tools.dump_wechat_uia_snapshot",
        fake_dump,
    )

    result = bridge.debug_dump_wechat_uia("Alice", max_depth=0, max_nodes=10)

    assert result["ok"] is True
    assert result["path"].endswith("wechat_uia_dump_test.json")
    assert result["messages"][0]["content"] == "hello"
    assert result["tree"]["name"] == "WeChat"
    assert captured == {
        "talker_display_name": "Alice",
        "max_depth": 1,
        "max_nodes": 50,
    }
