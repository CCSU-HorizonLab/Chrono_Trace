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
    recover_shell_only_wechat_uia,
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


def test_in_place_recovery_only_reactivates_existing_wechat_and_reprobes(monkeypatch):
    probes = iter(
        [
            {
                "status": "shell_only",
                "hwnd": 2468,
                "exe_path": r"C:\Program Files\Tencent\WeChat\WeChat.exe",
            },
            {
                "status": "accessible",
                "hwnd": 2468,
                "exe_path": r"C:\Program Files\Tencent\WeChat\WeChat.exe",
            },
        ]
    )
    activation_calls = []

    monkeypatch.setattr(
        "app.services.realtime.providers.recovery.probe_wechat_uia",
        lambda: dict(next(probes)),
    )
    monkeypatch.setattr(
        "app.services.realtime.providers.recovery.activate_wechat_window",
        lambda hwnd: activation_calls.append(hwnd) or {"ok": True, "hwnd": hwnd},
    )
    monkeypatch.setattr("app.services.realtime.providers.recovery.time.sleep", lambda _seconds: None)
    monkeypatch.setattr(
        "app.services.realtime.providers.recovery.terminate_wechat_processes",
        lambda: (_ for _ in ()).throw(AssertionError("should not terminate wechat in in_place mode")),
    )
    monkeypatch.setattr(
        "app.services.realtime.providers.recovery.launch_narrator",
        lambda narrator_path="": (_ for _ in ()).throw(AssertionError("should not launch narrator in in_place mode")),
    )
    monkeypatch.setattr(
        "app.services.realtime.providers.recovery.launch_wechat",
        lambda exe_path: (_ for _ in ()).throw(AssertionError("should not relaunch wechat in in_place mode")),
    )

    payload = recover_shell_only_wechat_uia(
        recover=True,
        recovery_mode="in_place",
        wait_after_focus=0,
        probe_interval=0,
        max_probes=2,
    )

    assert payload["recovery_mode"] == "in_place"
    assert activation_calls == [2468]
    assert payload["actions"][0]["step"] == "activate_wechat_window"
    assert payload["final_probe"]["status"] == "accessible"
    assert payload["errors"] == []


def test_relaunch_recovery_reports_progress_and_stops_narrator_on_success(monkeypatch):
    probes = iter(
        [
            {
                "status": "shell_only",
                "hwnd": 1357,
                "exe_path": r"C:\Program Files\Tencent\WeChat\WeChat.exe",
            },
            {
                "status": "accessible",
                "hwnd": 2468,
                "exe_path": r"C:\Program Files\Tencent\WeChat\WeChat.exe",
            },
        ]
    )
    progress = []

    monkeypatch.setattr(
        "app.services.realtime.providers.recovery.probe_wechat_uia",
        lambda: dict(next(probes)),
    )
    monkeypatch.setattr(
        "app.services.realtime.providers.recovery.pick_wechat_launch_path",
        lambda detected_exe_path="", extra_candidates=None: detected_exe_path or r"C:\Program Files\Tencent\WeChat\WeChat.exe",
    )
    monkeypatch.setattr(
        "app.services.realtime.providers.recovery.terminate_wechat_processes",
        lambda: [{"image_name": "WeChat.exe", "returncode": 0, "stdout": "", "stderr": ""}],
    )
    monkeypatch.setattr(
        "app.services.realtime.providers.recovery.launch_narrator",
        lambda narrator_path="": {"ok": True, "path": narrator_path or r"C:\Windows\System32\Narrator.exe", "pid": 11},
    )
    monkeypatch.setattr(
        "app.services.realtime.providers.recovery.launch_wechat",
        lambda exe_path: {"ok": True, "path": exe_path, "pid": 22},
    )
    monkeypatch.setattr(
        "app.services.realtime.providers.recovery.terminate_narrator",
        lambda: {"image_name": "Narrator.exe", "returncode": 0, "stdout": "", "stderr": ""},
    )
    monkeypatch.setattr("app.services.realtime.providers.recovery.time.sleep", lambda _seconds: None)

    payload = recover_shell_only_wechat_uia(
        recover=True,
        recovery_mode="relaunch_with_narrator",
        wait_after_kill=0,
        wait_after_narrator=0,
        wait_after_launch=0,
        probe_interval=0,
        max_probes=2,
        stop_narrator_on_success=True,
        progress_callback=lambda step, message, extra: progress.append((step, message, dict(extra))),
    )

    assert payload["final_probe"]["status"] == "accessible"
    assert any(step == "terminate_wechat" for step, _message, _extra in progress)
    assert any(step == "launch_narrator" for step, _message, _extra in progress)
    assert any(step == "launch_wechat" for step, _message, _extra in progress)
    assert any(step == "probe_after_relaunch" for step, _message, _extra in progress)
    assert any(action["step"] == "terminate_narrator_on_success" for action in payload["actions"])
