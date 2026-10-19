"""Tests for WeChat process helpers (wechat_proc_win)."""

from __future__ import annotations

import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

from app.services.wechat.wechat_proc_win import (
    launch_wechat,
    pick_wechat_launch_path,
    resolve_wechat_launch_path,
)

pytestmark = pytest.mark.skipif(
    sys.platform != "win32", reason="微信进程工具链依赖 Windows"
)


def test_pick_wechat_launch_path_prefers_existing_detected_path_and_falls_back_to_candidates(tmp_path):
    fallback_exe = tmp_path / "Weixin.exe"
    fallback_exe.write_text("", encoding="utf-8")

    resolved = pick_wechat_launch_path(
        detected_exe_path="Z:/missing/Weixin.exe",
        extra_candidates=[fallback_exe],
    )

    assert resolved == str(fallback_exe)


def test_resolve_wechat_launch_path_checks_registry_path_and_system_path(monkeypatch, tmp_path):
    registry_exe = tmp_path / "registry" / "WeChat.exe"
    registry_exe.parent.mkdir(parents=True, exist_ok=True)
    registry_exe.write_text("", encoding="utf-8")
    path_exe = tmp_path / "path" / "Weixin.exe"
    path_exe.parent.mkdir(parents=True, exist_ok=True)
    path_exe.write_text("", encoding="utf-8")

    monkeypatch.setattr(
        "app.services.wechat.wechat_proc_win._iter_registry_wechat_paths",
        lambda: [registry_exe],
    )
    monkeypatch.setattr(
        "app.services.wechat.wechat_proc_win._iter_path_search_candidates",
        lambda: [path_exe],
    )
    monkeypatch.setattr(
        "app.services.wechat.wechat_proc_win._iter_env_default_wechat_paths",
        lambda: [],
    )

    resolved = resolve_wechat_launch_path(detected_exe_path="", extra_candidates=None)

    assert resolved["path"] == str(registry_exe)
    assert resolved["source"] == "registry"
    assert str(registry_exe) in resolved["checked_candidates"]


def test_launch_wechat_returns_structured_errors_when_process_start_fails(monkeypatch, tmp_path):
    wechat_exe = tmp_path / "Weixin.exe"
    wechat_exe.write_text("", encoding="utf-8")

    monkeypatch.setattr(
        "app.services.wechat.wechat_proc_win.subprocess.Popen",
        lambda *args, **kwargs: (_ for _ in ()).throw(OSError("boom")),
    )
    monkeypatch.setattr(
        "app.services.wechat.wechat_proc_win.os.startfile",
        lambda _path: (_ for _ in ()).throw(OSError("startfile boom")),
        raising=False,
    )
    monkeypatch.setattr(
        "app.services.wechat.wechat_proc_win.subprocess.run",
        lambda *args, **kwargs: (_ for _ in ()).throw(OSError("run boom")),
    )

    result = launch_wechat(str(wechat_exe))

    assert result["ok"] is False
    assert result["path"] == str(wechat_exe)
    assert "boom" in str(result["error"])
