"""floating_tracker 单测：显示服务器降级选择与 NullTracker 契约。"""
from __future__ import annotations

import sys
from pathlib import Path

backend_root = Path(__file__).parent.parent
sys.path.insert(0, str(backend_root))

from app.services.realtime.floating_tracker import NullTracker, create_tracker


def test_wayland_without_display_degrades_to_null(monkeypatch):
    monkeypatch.setenv("XDG_SESSION_TYPE", "wayland")
    monkeypatch.delenv("DISPLAY", raising=False)
    assert isinstance(create_tracker(), NullTracker)


def test_xlib_unavailable_falls_back_to_null(monkeypatch):
    # X11 会话但 python-xlib 缺失/不可导入：降级而不是抛错
    monkeypatch.setenv("XDG_SESSION_TYPE", "x11")
    monkeypatch.setitem(sys.modules, "Xlib", None)
    assert isinstance(create_tracker(), NullTracker)


def test_wayland_with_display_still_tries_x11(monkeypatch):
    # Wayland 下若存在 X 兼容层（DISPLAY 可用）仍尝试 X11；导入失败再降级
    monkeypatch.setenv("XDG_SESSION_TYPE", "wayland")
    monkeypatch.setenv("DISPLAY", ":0")
    monkeypatch.setitem(sys.modules, "Xlib", None)
    assert isinstance(create_tracker(), NullTracker)


def test_null_tracker_contract():
    tracker = NullTracker()
    assert tracker.find() is None
    assert tracker.workarea is None
