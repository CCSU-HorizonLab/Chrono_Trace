"""Helpers for probing and recovering WeChat UIA accessibility on Windows."""

from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path
from typing import Callable, Iterable

from .detector import detect_running_wechat
from .native_uia import SHELL_ONLY_CLASS_NAMES

WECHAT_PROCESS_NAMES: tuple[str, ...] = (
    "Weixin.exe",
    "WeChat.exe",
    "WeChatAppEx.exe",
)

DEFAULT_WECHAT_EXE_CANDIDATES: tuple[Path, ...] = (
    Path(r"D:\Program files\Weixin\Weixin.exe"),
    Path(r"C:\Program Files\Tencent\WeChat\WeChat.exe"),
)


def default_narrator_path() -> str:
    windir = str(os.environ.get("WINDIR") or r"C:\Windows")
    return str(Path(windir) / "System32" / "Narrator.exe")


def _as_path(value: str | Path | None) -> Path | None:
    if not value:
        return None
    try:
        return Path(str(value))
    except Exception:
        return None


def is_meaningful_visible_descendant(
    class_name: str,
    control_type: str,
    automation_id: str,
) -> bool:
    return bool(
        automation_id
        or class_name not in SHELL_ONLY_CLASS_NAMES
        or control_type != "Pane"
    )


def classify_visible_descendants(
    visible_descendants: Iterable[tuple[str, str, str]],
) -> dict[str, int | str]:
    normalized = [
        (
            str(class_name or ""),
            str(control_type or ""),
            str(automation_id or ""),
        )
        for class_name, control_type, automation_id in visible_descendants
    ]
    meaningful_count = sum(
        1
        for class_name, control_type, automation_id in normalized
        if is_meaningful_visible_descendant(class_name, control_type, automation_id)
    )
    return {
        "status": "accessible" if meaningful_count > 0 else "shell_only",
        "visible_count": len(normalized),
        "meaningful_count": meaningful_count,
    }


def pick_wechat_launch_path(
    detected_exe_path: str = "",
    extra_candidates: Iterable[str | Path] | None = None,
) -> str:
    candidates: list[Path] = []
    for candidate in [detected_exe_path, *(extra_candidates or ()), *DEFAULT_WECHAT_EXE_CANDIDATES]:
        path = _as_path(candidate)
        if path is None:
            continue
        if path not in candidates:
            candidates.append(path)
    for path in candidates:
        try:
            if path.exists():
                return str(path)
        except Exception:
            continue
    return ""


def probe_wechat_uia() -> dict:
    payload = {
        "captured_at": int(time.time()),
        "status": "not_running",
        "wechat_version": "",
        "listener_profile": "",
        "hwnd": 0,
        "exe_path": "",
        "visible_count": 0,
        "meaningful_count": 0,
        "visible_descendants_sample": [],
        "error": "",
    }

    info = detect_running_wechat()
    payload["wechat_version"] = str(info.version or "")
    payload["listener_profile"] = str(info.listener_profile or "")
    payload["hwnd"] = int(info.hwnd or 0)
    payload["exe_path"] = str(info.exe_path or "")
    if not info.hwnd:
        return payload

    try:
        from pywinauto import Application
    except Exception as exc:
        payload["status"] = "probe_failed"
        payload["error"] = f"pywinauto_unavailable: {exc}"
        return payload

    try:
        app = Application(backend="uia").connect(handle=info.hwnd)
        win = app.window(handle=info.hwnd)
        win.wait("exists enabled visible ready", timeout=5)
        descendants = list(win.descendants())
    except Exception as exc:
        payload["status"] = "probe_failed"
        payload["error"] = f"connect_failed: {exc}"
        return payload

    visible_descendants: list[tuple[str, str, str]] = []
    sample: list[dict[str, str]] = []
    for item in descendants:
        try:
            if not item.is_visible():
                continue
            class_name = str(item.class_name() or "")
            control_type = str(getattr(item.element_info, "control_type", "") or "")
            automation_id = str(getattr(item.element_info, "automation_id", "") or "")
            name = str(item.window_text() or "")
        except Exception:
            continue
        visible_descendants.append((class_name, control_type, automation_id))
        if len(sample) < 20:
            sample.append(
                {
                    "class_name": class_name,
                    "control_type": control_type,
                    "automation_id": automation_id,
                    "name": name[:80],
                }
            )

    summary = classify_visible_descendants(visible_descendants)
    payload["status"] = str(summary["status"])
    payload["visible_count"] = int(summary["visible_count"])
    payload["meaningful_count"] = int(summary["meaningful_count"])
    payload["visible_descendants_sample"] = sample
    return payload


def _run_taskkill(image_name: str) -> dict:
    completed = subprocess.run(
        ["taskkill", "/IM", image_name, "/F"],
        capture_output=True,
        text=True,
        shell=False,
    )
    return {
        "image_name": image_name,
        "returncode": int(completed.returncode),
        "stdout": str(completed.stdout or "").strip(),
        "stderr": str(completed.stderr or "").strip(),
    }


def terminate_wechat_processes() -> list[dict]:
    return [_run_taskkill(image_name) for image_name in WECHAT_PROCESS_NAMES]


def terminate_narrator() -> dict:
    return _run_taskkill("Narrator.exe")


def launch_narrator(narrator_path: str = "") -> dict:
    path = narrator_path or default_narrator_path()
    if not Path(path).exists():
        return {
            "ok": False,
            "path": path,
            "error": "Narrator executable not found",
        }
    try:
        process = subprocess.Popen([path], shell=False)
    except Exception as exc:
        return {
            "ok": False,
            "path": path,
            "error": str(exc),
        }
    return {
        "ok": True,
        "path": path,
        "pid": int(process.pid or 0),
    }


def launch_wechat(exe_path: str) -> dict:
    if not exe_path:
        return {"ok": False, "path": "", "error": "WeChat executable path not resolved"}
    if not Path(exe_path).exists():
        return {"ok": False, "path": exe_path, "error": "WeChat executable not found"}
    try:
        process = subprocess.Popen([exe_path], shell=False)
    except Exception as exc:
        return {
            "ok": False,
            "path": exe_path,
            "error": str(exc),
        }
    return {
        "ok": True,
        "path": exe_path,
        "pid": int(process.pid or 0),
    }


def activate_wechat_window(hwnd: int) -> dict:
    """Best-effort foreground/restore for the current WeChat window without restarting it."""
    try:
        import win32con
        import win32gui
    except Exception as exc:
        return {
            "ok": False,
            "hwnd": int(hwnd or 0),
            "error": f"win32_unavailable: {exc}",
        }

    if not hwnd:
        return {
            "ok": False,
            "hwnd": 0,
            "error": "WeChat window handle not resolved",
        }

    try:
        if win32gui.IsIconic(hwnd):
            win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
        else:
            win32gui.ShowWindow(hwnd, win32con.SW_SHOW)
        win32gui.BringWindowToTop(hwnd)
        try:
            win32gui.SetForegroundWindow(hwnd)
        except Exception:
            pass
        return {
            "ok": True,
            "hwnd": int(hwnd),
        }
    except Exception as exc:
        return {
            "ok": False,
            "hwnd": int(hwnd),
            "error": str(exc),
        }


def recover_shell_only_wechat_uia(
    recover: bool = True,
    wechat_exe: str = "",
    narrator_path: str = "",
    recovery_mode: str = "relaunch_with_narrator",
    wait_after_focus: float = 0.8,
    wait_after_kill: float = 1.0,
    wait_after_narrator: float = 1.5,
    wait_after_launch: float = 6.0,
    probe_interval: float = 2.0,
    max_probes: int = 6,
    stop_narrator_after_check: bool = False,
    stop_narrator_on_success: bool = False,
    progress_callback: Callable[[str, str, dict], None] | None = None,
) -> dict:
    def emit_progress(step: str, message: str, extra: dict | None = None) -> None:
        if progress_callback is None:
            return
        try:
            progress_callback(step, message, dict(extra or {}))
        except Exception:
            pass

    payload = {
        "captured_at": int(time.time()),
        "recover_requested": bool(recover),
        "recovery_mode": str(recovery_mode or "relaunch_with_narrator"),
        "initial_probe": probe_wechat_uia(),
        "actions": [],
        "recovery_probes": [],
        "final_probe": {},
        "errors": [],
    }

    initial_probe = payload["initial_probe"]
    emit_progress(
        "initial_probe",
        "正在检查微信 UI 树状态...",
        {"status": initial_probe.get("status")},
    )
    if not recover:
        payload["final_probe"] = initial_probe
        return payload

    if initial_probe.get("status") != "shell_only":
        payload["actions"].append(
            {
                "step": "skip_recovery",
                "reason": f"initial_status={initial_probe.get('status')}",
            }
        )
        payload["final_probe"] = initial_probe
        return payload

    normalized_mode = str(recovery_mode or "relaunch_with_narrator").strip().lower()
    if normalized_mode in {"in_place", "gentle", "non_destructive"}:
        emit_progress(
            "activate_existing_wechat",
            "检测到微信 UI 树没有展开，正在尝试激活当前微信窗口并重新检测...",
            {"hwnd": int(initial_probe.get("hwnd") or 0)},
        )
        focus_result = activate_wechat_window(int(initial_probe.get("hwnd") or 0))
        payload["actions"].append(
            {
                "step": "activate_wechat_window",
                **focus_result,
            }
        )
        if not focus_result.get("ok"):
            payload["errors"].append(str(focus_result.get("error") or "Failed to activate WeChat window"))

        if wait_after_focus > 0:
            time.sleep(wait_after_focus)

        final_probe = None
        probe_count = max(1, int(max_probes or 1))
        for probe_index in range(probe_count):
            if probe_index > 0:
                payload["actions"].append(
                    {
                        "step": "re_activate_wechat_window",
                        "probe_index": probe_index + 1,
                        **activate_wechat_window(int(initial_probe.get("hwnd") or 0)),
                    }
                )
            current_probe = probe_wechat_uia()
            emit_progress(
                "probe_existing_wechat",
                "正在重新抓取微信 UI 树...",
                {"status": current_probe.get("status"), "probe_index": probe_index + 1},
            )
            current_probe["probe_index"] = probe_index + 1
            payload["recovery_probes"].append(current_probe)
            final_probe = current_probe
            if current_probe.get("status") == "accessible":
                break
            if probe_index + 1 < probe_count and probe_interval > 0:
                time.sleep(probe_interval)

        payload["final_probe"] = final_probe or probe_wechat_uia()
        return payload

    resolved_wechat_exe = pick_wechat_launch_path(
        detected_exe_path=str(initial_probe.get("exe_path") or ""),
        extra_candidates=[wechat_exe] if wechat_exe else [],
    )
    emit_progress(
        "prepare_relaunch",
        "检测到微信 UI 树没有展开，将尝试自动修复：关闭微信、打开讲述人并重新启动微信。",
        {"resolved_wechat_exe": resolved_wechat_exe},
    )
    payload["actions"].append(
        {
            "step": "resolve_wechat_exe",
            "requested_path": wechat_exe,
            "resolved_path": resolved_wechat_exe,
        }
    )
    if not resolved_wechat_exe:
        payload["errors"].append("Unable to resolve WeChat executable path for relaunch")
        payload["final_probe"] = initial_probe
        return payload

    emit_progress(
        "terminate_wechat",
        "正在自动关闭当前微信窗口...",
        {},
    )
    payload["actions"].append(
        {
            "step": "terminate_wechat",
            "results": terminate_wechat_processes(),
        }
    )
    if wait_after_kill > 0:
        time.sleep(wait_after_kill)

    emit_progress(
        "launch_narrator",
        "正在打开 Windows 讲述人...",
        {},
    )
    narrator_result = launch_narrator(narrator_path=narrator_path)
    payload["actions"].append(
        {
            "step": "launch_narrator",
            **narrator_result,
        }
    )
    if not narrator_result.get("ok"):
        payload["errors"].append(str(narrator_result.get("error") or "Failed to launch Narrator"))
    if wait_after_narrator > 0:
        time.sleep(wait_after_narrator)

    emit_progress(
        "launch_wechat",
        "正在重新打开微信，请在微信窗口完成登录。程序会在登录后继续抓取 UI 树...",
        {"resolved_wechat_exe": resolved_wechat_exe},
    )
    wechat_launch_result = launch_wechat(resolved_wechat_exe)
    payload["actions"].append(
        {
            "step": "launch_wechat",
            **wechat_launch_result,
        }
    )
    if not wechat_launch_result.get("ok"):
        payload["errors"].append(str(wechat_launch_result.get("error") or "Failed to launch WeChat"))
        payload["final_probe"] = probe_wechat_uia()
        if stop_narrator_after_check:
            payload["actions"].append(
                {
                    "step": "terminate_narrator",
                    "result": terminate_narrator(),
                }
            )
        return payload

    if wait_after_launch > 0:
        time.sleep(wait_after_launch)

    final_probe = None
    for probe_index in range(max(1, int(max_probes or 1))):
        current_probe = probe_wechat_uia()
        emit_progress(
            "probe_after_relaunch",
            "正在等待微信登录并继续抓取 UI 树...",
            {"status": current_probe.get("status"), "probe_index": probe_index + 1},
        )
        current_probe["probe_index"] = probe_index + 1
        payload["recovery_probes"].append(current_probe)
        final_probe = current_probe
        if current_probe.get("status") == "accessible":
            break
        if probe_index + 1 < max(1, int(max_probes or 1)) and probe_interval > 0:
            time.sleep(probe_interval)

    payload["final_probe"] = final_probe or probe_wechat_uia()

    if stop_narrator_on_success and payload["final_probe"].get("status") == "accessible":
        emit_progress(
            "terminate_narrator_on_success",
            "微信 UI 树已恢复，正在关闭讲述人...",
            {},
        )
        payload["actions"].append(
            {
                "step": "terminate_narrator_on_success",
                "result": terminate_narrator(),
            }
        )

    if stop_narrator_after_check:
        payload["actions"].append(
            {
                "step": "terminate_narrator",
                "result": terminate_narrator(),
            }
        )

    return payload
