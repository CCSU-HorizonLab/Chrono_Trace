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
    resolve_wechat_launch_path,
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


def test_resolve_wechat_launch_path_checks_registry_path_and_system_path(monkeypatch, tmp_path):
    registry_exe = tmp_path / "registry" / "WeChat.exe"
    registry_exe.parent.mkdir(parents=True, exist_ok=True)
    registry_exe.write_text("", encoding="utf-8")
    path_exe = tmp_path / "path" / "Weixin.exe"
    path_exe.parent.mkdir(parents=True, exist_ok=True)
    path_exe.write_text("", encoding="utf-8")

    monkeypatch.setattr(
        "app.services.realtime.providers.recovery._iter_registry_wechat_paths",
        lambda: [registry_exe],
    )
    monkeypatch.setattr(
        "app.services.realtime.providers.recovery._iter_path_search_candidates",
        lambda: [path_exe],
    )
    monkeypatch.setattr(
        "app.services.realtime.providers.recovery._iter_env_default_wechat_paths",
        lambda: [],
    )

    resolved = resolve_wechat_launch_path(detected_exe_path="", extra_candidates=None)

    assert resolved["path"] == str(registry_exe)
    assert resolved["source"] == "registry"
    assert str(registry_exe) in resolved["checked_candidates"]


def test_launch_helpers_return_structured_errors_when_process_start_fails(monkeypatch, tmp_path):
    narrator_exe = tmp_path / "Narrator.exe"
    wechat_exe = tmp_path / "Weixin.exe"
    narrator_exe.write_text("", encoding="utf-8")
    wechat_exe.write_text("", encoding="utf-8")

    monkeypatch.setattr(
        "app.services.realtime.providers.recovery.subprocess.Popen",
        lambda *args, **kwargs: (_ for _ in ()).throw(OSError("boom")),
    )
    monkeypatch.setattr(
        "app.services.realtime.providers.recovery.wait_for_process",
        lambda **kwargs: {
            "status": "not_running",
            "image_name": kwargs.get("image_name", ""),
            "pid": kwargs.get("pid", 0),
            "rows": [],
            "error": "",
            "attempts": 1,
            "timeout": kwargs.get("timeout", 0),
            "probe_interval": kwargs.get("probe_interval", 0),
            "verified": False,
        },
    )
    monkeypatch.setattr(
        "app.services.realtime.providers.recovery.os.startfile",
        lambda _path: (_ for _ in ()).throw(OSError("startfile boom")),
        raising=False,
    )
    monkeypatch.setattr(
        "app.services.realtime.providers.recovery.subprocess.run",
        lambda *args, **kwargs: (_ for _ in ()).throw(OSError("run boom")),
    )

    narrator_result = launch_narrator(str(narrator_exe))
    wechat_result = launch_wechat(str(wechat_exe))

    assert narrator_result["ok"] is False
    assert narrator_result["path"] == str(narrator_exe)
    assert "boom" in narrator_result["error"]
    assert wechat_result["ok"] is False
    assert wechat_result["path"] == str(wechat_exe)
    assert "boom" in str(wechat_result["error"])


def test_launch_narrator_verifies_process_is_running(monkeypatch, tmp_path):
    narrator_exe = tmp_path / "Narrator.exe"
    narrator_exe.write_text("", encoding="utf-8")

    class FakeProcess:
        pid = 4321

    monkeypatch.setattr(
        "app.services.realtime.providers.recovery.subprocess.Popen",
        lambda *args, **kwargs: FakeProcess(),
    )
    calls = {"count": 0}

    def fake_verify(pid=0):
        calls["count"] += 1
        if calls["count"] == 1:
            return {
                "status": "not_running",
                "image_name": "Narrator.exe",
                "pid": 0,
                "rows": [],
                "error": "",
                "attempts": 1,
                "timeout": 3.0,
                "probe_interval": 0.25,
                "verified": False,
            }
        return {
            "status": "running",
            "image_name": "Narrator.exe",
            "pid": pid,
            "rows": [{"image_name": "Narrator.exe", "pid": pid}],
            "error": "",
            "attempts": 2,
            "timeout": 3.0,
            "probe_interval": 0.25,
            "verified": True,
        }

    monkeypatch.setattr(
        "app.services.realtime.providers.recovery._verify_narrator_running",
        fake_verify,
    )

    narrator_result = launch_narrator(str(narrator_exe))

    assert narrator_result["ok"] is True
    assert narrator_result["pid"] == 4321
    assert narrator_result["verification"]["verified"] is True


def test_launch_narrator_prefers_existing_running_process(monkeypatch, tmp_path):
    narrator_exe = tmp_path / "Narrator.exe"
    narrator_exe.write_text("", encoding="utf-8")
    process_calls = []

    monkeypatch.setattr(
        "app.services.realtime.providers.recovery._verify_narrator_running",
        lambda pid=0: {
            "status": "running",
            "image_name": "Narrator.exe",
            "pid": pid or 2468,
            "rows": [{"image_name": "Narrator.exe", "pid": pid or 2468}],
            "error": "",
            "attempts": 1,
            "timeout": 3.0,
            "probe_interval": 0.25,
            "verified": True,
        },
    )
    monkeypatch.setattr(
        "app.services.realtime.providers.recovery.subprocess.Popen",
        lambda *args, **kwargs: process_calls.append((args, kwargs)),
    )

    narrator_result = launch_narrator(str(narrator_exe))

    assert narrator_result["ok"] is True
    assert narrator_result["launch_method"] == "already_running"
    assert narrator_result["pid"] == 2468
    assert process_calls == []


def test_launch_narrator_falls_back_to_startfile_when_createprocess_needs_elevation(monkeypatch, tmp_path):
    narrator_exe = tmp_path / "Narrator.exe"
    narrator_exe.write_text("", encoding="utf-8")
    state = {"verified": 0, "startfile_calls": 0}

    monkeypatch.setattr(
        "app.services.realtime.providers.recovery.subprocess.Popen",
        lambda *args, **kwargs: (_ for _ in ()).throw(OSError("[WinError 740] 请求的操作需要提升。")),
    )

    def fake_verify(pid=0):
        if state["verified"] == 0:
            state["verified"] += 1
            return {
                "status": "not_running",
                "image_name": "Narrator.exe",
                "pid": pid,
                "rows": [],
                "error": "",
                "attempts": 1,
                "timeout": 3.0,
                "probe_interval": 0.25,
                "verified": False,
            }
        return {
            "status": "running",
            "image_name": "Narrator.exe",
            "pid": 8642,
            "rows": [{"image_name": "Narrator.exe", "pid": 8642}],
            "error": "",
            "attempts": 2,
            "timeout": 3.0,
            "probe_interval": 0.25,
            "verified": True,
        }

    monkeypatch.setattr(
        "app.services.realtime.providers.recovery._verify_narrator_running",
        fake_verify,
    )
    monkeypatch.setattr(
        "app.services.realtime.providers.recovery.os.startfile",
        lambda _path: state.__setitem__("startfile_calls", state["startfile_calls"] + 1),
        raising=False,
    )

    narrator_result = launch_narrator(str(narrator_exe))

    assert narrator_result["ok"] is True
    assert narrator_result["launch_method"] == "startfile"
    assert narrator_result["pid"] == 8642
    assert state["startfile_calls"] == 1


def test_launch_narrator_returns_error_when_process_cannot_be_verified(monkeypatch, tmp_path):
    narrator_exe = tmp_path / "Narrator.exe"
    narrator_exe.write_text("", encoding="utf-8")

    class FakeProcess:
        pid = 9876

    monkeypatch.setattr(
        "app.services.realtime.providers.recovery.subprocess.Popen",
        lambda *args, **kwargs: FakeProcess(),
    )
    monkeypatch.setattr(
        "app.services.realtime.providers.recovery._verify_narrator_running",
        lambda pid=0: {
            "status": "not_running",
            "image_name": "Narrator.exe",
            "pid": pid,
            "rows": [],
            "error": "",
            "attempts": 4,
            "timeout": 3.0,
            "probe_interval": 0.25,
            "verified": False,
        },
    )

    narrator_result = launch_narrator(str(narrator_exe))

    assert narrator_result["ok"] is False
    assert narrator_result["pid"] == 0
    assert narrator_result["verification"]["verified"] is False
    assert "could not be verified" in narrator_result["error"]


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
    assert any(step == "launch_narrator" for step, _message, _extra in progress)
    assert any(step == "terminate_wechat" for step, _message, _extra in progress)
    assert any(step == "launch_wechat" for step, _message, _extra in progress)
    assert any(step == "probe_after_relaunch" for step, _message, _extra in progress)
    assert any(action["step"] == "terminate_narrator_on_success" for action in payload["actions"])


def test_relaunch_recovery_aborts_when_narrator_launch_cannot_be_verified(monkeypatch):
    progress = []

    monkeypatch.setattr(
        "app.services.realtime.providers.recovery.probe_wechat_uia",
        lambda: {
            "status": "shell_only",
            "hwnd": 1357,
            "exe_path": r"C:\Program Files\Tencent\WeChat\WeChat.exe",
        },
    )
    monkeypatch.setattr(
        "app.services.realtime.providers.recovery.resolve_wechat_launch_path",
        lambda detected_exe_path="", extra_candidates=None: {
            "path": r"C:\Program Files\Tencent\WeChat\WeChat.exe",
            "source": "registry",
            "checked_candidates": [r"C:\Program Files\Tencent\WeChat\WeChat.exe"],
        },
    )
    monkeypatch.setattr(
        "app.services.realtime.providers.recovery.terminate_wechat_processes",
        lambda: (_ for _ in ()).throw(AssertionError("should not terminate wechat when narrator is unverified")),
    )
    monkeypatch.setattr(
        "app.services.realtime.providers.recovery.launch_narrator",
        lambda narrator_path="": {
            "ok": False,
            "path": narrator_path or r"C:\Windows\System32\Narrator.exe",
            "pid": 11,
            "verification": {
                "status": "not_running",
                "verified": False,
                "pid": 11,
                "rows": [],
                "error": "",
            },
            "error": "Narrator launch could not be verified (status=not_running)",
        },
    )
    monkeypatch.setattr(
        "app.services.realtime.providers.recovery.wait_for_process",
        lambda **kwargs: {
            "status": "not_running",
            "image_name": kwargs.get("image_name", "Narrator.exe"),
            "pid": kwargs.get("pid", 0),
            "rows": [],
            "error": "",
            "attempts": 3,
            "timeout": kwargs.get("timeout", 0),
            "probe_interval": kwargs.get("probe_interval", 0),
            "verified": False,
        },
    )
    monkeypatch.setattr(
        "app.services.realtime.providers.recovery.launch_wechat",
        lambda exe_path: (_ for _ in ()).throw(AssertionError("should not relaunch wechat when narrator is unverified")),
    )
    monkeypatch.setattr("app.services.realtime.providers.recovery.time.sleep", lambda _seconds: None)

    payload = recover_shell_only_wechat_uia(
        recover=True,
        recovery_mode="relaunch_with_narrator",
        wait_after_kill=0,
        wait_after_narrator=0,
        wait_after_launch=0,
        probe_interval=0,
        max_probes=1,
        progress_callback=lambda step, message, extra: progress.append((step, message, dict(extra))),
    )

    assert payload["final_probe"]["status"] == "shell_only"
    assert "Narrator launch could not be verified" in payload["errors"][0]
    assert any(step == "abort_before_terminate" for step, _message, _extra in progress)
    assert any(action["step"] == "abort_before_terminate" for action in payload["actions"])
    assert any(action["step"] == "wait_for_manual_narrator" for action in payload["actions"])
    assert not any(action["step"] == "terminate_wechat" for action in payload["actions"])


def test_relaunch_recovery_waits_for_manual_narrator_then_continues(monkeypatch):
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
        "app.services.realtime.providers.recovery.resolve_wechat_launch_path",
        lambda detected_exe_path="", extra_candidates=None: {
            "path": r"C:\Program Files\Tencent\WeChat\WeChat.exe",
            "source": "registry",
            "checked_candidates": [r"C:\Program Files\Tencent\WeChat\WeChat.exe"],
        },
    )
    monkeypatch.setattr(
        "app.services.realtime.providers.recovery.launch_narrator",
        lambda narrator_path="": {
            "ok": False,
            "path": narrator_path or r"C:\Windows\System32\Narrator.exe",
            "pid": 0,
            "verification": {"status": "not_running", "verified": False, "rows": [], "error": ""},
            "error": "Narrator launch could not be verified (status=not_running)",
        },
    )
    monkeypatch.setattr(
        "app.services.realtime.providers.recovery.wait_for_process",
        lambda **kwargs: {
            "status": "running",
            "image_name": kwargs.get("image_name", "Narrator.exe"),
            "pid": 5566,
            "rows": [{"image_name": "Narrator.exe", "pid": 5566}],
            "error": "",
            "attempts": 2,
            "timeout": kwargs.get("timeout", 0),
            "probe_interval": kwargs.get("probe_interval", 0),
            "verified": True,
        },
    )
    monkeypatch.setattr(
        "app.services.realtime.providers.recovery.terminate_wechat_processes",
        lambda: [{"image_name": "WeChat.exe", "returncode": 0, "stdout": "", "stderr": ""}],
    )
    monkeypatch.setattr(
        "app.services.realtime.providers.recovery.launch_wechat",
        lambda exe_path: {"ok": True, "path": exe_path, "pid": 22},
    )
    monkeypatch.setattr("app.services.realtime.providers.recovery.time.sleep", lambda _seconds: None)

    payload = recover_shell_only_wechat_uia(
        recover=True,
        recovery_mode="relaunch_with_narrator",
        wait_after_kill=0,
        wait_after_narrator=0,
        wait_after_launch=0,
        probe_interval=0,
        max_probes=1,
        manual_narrator_timeout=5,
        manual_narrator_probe_interval=0,
        progress_callback=lambda step, message, extra: progress.append((step, message, dict(extra))),
    )

    assert payload["final_probe"]["status"] == "accessible"
    assert any(step == "wait_manual_narrator" for step, _message, _extra in progress)
    assert any(step == "manual_narrator_ready" for step, _message, _extra in progress)
    assert any(action["step"] == "wait_for_manual_narrator" and action["ok"] is True for action in payload["actions"])
    assert any(action["step"] == "terminate_wechat" for action in payload["actions"])


def test_relaunch_recovery_aborts_before_terminating_wechat_when_launch_path_unresolved(monkeypatch):
    monkeypatch.setattr(
        "app.services.realtime.providers.recovery.probe_wechat_uia",
        lambda: {
            "status": "shell_only",
            "hwnd": 1357,
            "exe_path": "",
        },
    )
    monkeypatch.setattr(
        "app.services.realtime.providers.recovery.resolve_wechat_launch_path",
        lambda detected_exe_path="", extra_candidates=None: {
            "path": "",
            "source": "",
            "checked_candidates": [r"C:\Missing\WeChat.exe"],
        },
    )
    monkeypatch.setattr(
        "app.services.realtime.providers.recovery.terminate_wechat_processes",
        lambda: (_ for _ in ()).throw(AssertionError("should not terminate wechat before launch path is resolved")),
    )
    monkeypatch.setattr("app.services.realtime.providers.recovery.time.sleep", lambda _seconds: None)

    payload = recover_shell_only_wechat_uia(
        recover=True,
        recovery_mode="relaunch_with_narrator",
        wait_after_kill=0,
        wait_after_narrator=0,
        wait_after_launch=0,
        probe_interval=0,
        max_probes=1,
    )

    assert payload["final_probe"]["status"] == "shell_only"
    assert "Unable to resolve WeChat executable path for relaunch" in payload["errors"]
    assert any(action["step"] == "abort_before_terminate" for action in payload["actions"])
    assert not any(action["step"] == "terminate_wechat" for action in payload["actions"])
