"""Tests for WeChat UIA recovery helpers."""

from __future__ import annotations

import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.realtime.providers.recovery import (
    classify_visible_descendants,
    launch_narrator,
    launch_wechat,
    pick_wechat_launch_path,
)


def test_classify_visible_descendants_marks_shell_only_when_only_outer_panes_exist():
    result = classify_visible_descendants(
        [
            ("Qt51514QWindowIcon", "Pane", ""),
            ("MMUIRenderSubWindowHW", "Pane", ""),
        ]
    )

    assert result == {
        "status": "shell_only",
        "visible_count": 2,
        "meaningful_count": 0,
    }


def test_classify_visible_descendants_marks_accessible_when_meaningful_control_exists():
    result = classify_visible_descendants(
        [
            ("Qt51514QWindowIcon", "Pane", ""),
            ("mmui::MainView", "Group", "MainView"),
            ("mmui::XTableView", "List", "session_list"),
        ]
    )

    assert result == {
        "status": "accessible",
        "visible_count": 3,
        "meaningful_count": 2,
    }


def test_pick_wechat_launch_path_prefers_existing_detected_path_and_falls_back_to_candidates(tmp_path):
    fallback_exe = tmp_path / "Weixin.exe"
    fallback_exe.write_text("", encoding="utf-8")

    resolved = pick_wechat_launch_path(
        detected_exe_path="Z:/missing/Weixin.exe",
        extra_candidates=[fallback_exe],
    )

    assert resolved == str(fallback_exe)


def test_launch_helpers_return_structured_errors_when_process_start_fails(monkeypatch, tmp_path):
    narrator_exe = tmp_path / "Narrator.exe"
    wechat_exe = tmp_path / "Weixin.exe"
    narrator_exe.write_text("", encoding="utf-8")
    wechat_exe.write_text("", encoding="utf-8")

    monkeypatch.setattr(
        "app.services.realtime.providers.recovery.subprocess.Popen",
        lambda *args, **kwargs: (_ for _ in ()).throw(OSError("boom")),
    )

    narrator_result = launch_narrator(str(narrator_exe))
    wechat_result = launch_wechat(str(wechat_exe))

    assert narrator_result == {
        "ok": False,
        "path": str(narrator_exe),
        "error": "boom",
    }
    assert wechat_result == {
        "ok": False,
        "path": str(wechat_exe),
        "error": "boom",
    }
