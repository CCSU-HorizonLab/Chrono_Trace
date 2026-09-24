"""Windows-side preparation for the explicit WeChat database-key capture flow.

The Hook itself lives in :mod:`key_provider`.  This module only determines the
visible login state and, after an explicit frontend confirmation, restarts
WeChat so the Hook can be installed before the next login event.
"""

from __future__ import annotations

from pathlib import Path
import time
from typing import Any


PROCESS_NAMES = {"wechat.exe", "weixin.exe"}
LOGIN_TEXTS = ("扫码登录", "登录", "手机号登录", "二维码")
LOGGED_IN_TEXTS = ("聊天", "通讯录", "发现", "朋友圈", "文件传输助手")


def _list_wechat_processes() -> list[dict[str, Any]]:
    try:
        import win32api
        import win32con
        import win32process
    except Exception as exc:  # pragma: no cover - Windows-only runtime
        return [{"error": f"Windows 进程检测不可用：{exc}"}]

    access = win32con.PROCESS_QUERY_INFORMATION | win32con.PROCESS_VM_READ
    processes: list[dict[str, Any]] = []
    for candidate_pid in win32process.EnumProcesses():
        handle = None
        try:
            handle = win32api.OpenProcess(access, False, int(candidate_pid))
            exe_path = str(win32process.GetModuleFileNameEx(handle, 0) or "")
            name = Path(exe_path).name
            if name.lower() in PROCESS_NAMES:
                processes.append({"pid": int(candidate_pid), "name": name, "exe_path": exe_path})
        except Exception:
            continue
        finally:
            if handle is not None:
                try:
                    win32api.CloseHandle(handle)
                except Exception:
                    pass
    return sorted(processes, key=lambda item: int(item["pid"]))


def _window_texts(pids: set[int]) -> list[str]:
    """Read visible window labels only; failure intentionally yields no labels."""
    try:
        import win32gui
        import win32process
    except Exception:  # pragma: no cover - Windows-only runtime
        return []

    texts: list[str] = []
    top_level_handles: list[int] = []

    def collect(hwnd: int) -> None:
        try:
            if win32gui.IsWindowVisible(hwnd):
                text = str(win32gui.GetWindowText(hwnd) or "").strip()
                if text:
                    texts.append(text)
        except Exception:
            pass

    def top_level(hwnd: int, _lparam: int) -> bool:
        try:
            if not win32gui.IsWindowVisible(hwnd):
                return True
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            if int(pid) not in pids:
                return True
            top_level_handles.append(int(hwnd))
            collect(hwnd)
            win32gui.EnumChildWindows(hwnd, lambda child, _: (collect(child), True)[1], 0)
        except Exception:
            pass
        return True

    try:
        win32gui.EnumWindows(top_level, 0)
    except Exception:
        return []

    # Recent Weixin builds render most controls in one Qt child window, where
    # Win32 text is empty.  UIA provides the stable navigation labels needed
    # to distinguish the login page from an already logged-in main window.
    try:
        from pywinauto import Application

        for hwnd in top_level_handles:
            window = Application(backend="uia").connect(handle=hwnd).window(handle=hwnd)
            for control in window.descendants():
                try:
                    if not control.is_visible():
                        continue
                    text = str(control.window_text() or "").strip()
                    if text:
                        texts.append(text)
                except Exception:
                    continue
    except Exception:
        pass
    return texts


def inspect_wechat_login_state() -> dict[str, Any]:
    """Return a conservative visible-state classification for the capture UI."""
    processes = _list_wechat_processes()
    errors = [str(item.get("error") or "") for item in processes if item.get("error")]
    processes = [item for item in processes if item.get("pid")]
    if not processes:
        return {
            "ok": not errors,
            "running": False,
            "login_state": "not_running",
            "processes": [],
            "error": errors[0] if errors else "",
        }

    labels = _window_texts({int(item["pid"]) for item in processes})
    joined = "\n".join(labels)
    if any(marker in joined for marker in LOGGED_IN_TEXTS):
        login_state = "logged_in"
    elif any(marker in joined for marker in LOGIN_TEXTS):
        login_state = "login_required"
    else:
        # Never treat an unrecognised UI as logged in: this avoids an
        # unexpected forced shutdown when the UI changes in a future release.
        login_state = "unknown"

    return {
        "ok": True,
        "running": True,
        "login_state": login_state,
        "processes": processes,
        "window_label_count": len(labels),
        "error": "",
    }


def restart_wechat_for_key_capture(wait_seconds: float = 30.0) -> dict[str, Any]:
    """Restart WeChat after a frontend confirmation and wait for its login UI.

    Callers must obtain the user's confirmation before invoking this function.
    It deliberately does not install a Hook; the caller does that immediately
    after this function returns so the UI can present login instructions.
    """
    from ..realtime.providers.recovery import (
        launch_wechat,
        resolve_wechat_launch_path,
        terminate_wechat_processes,
    )

    before = inspect_wechat_login_state()
    detected_path = ""
    for process in before.get("processes") or []:
        detected_path = str(process.get("exe_path") or "")
        if detected_path:
            break
    resolved = resolve_wechat_launch_path(detected_exe_path=detected_path)
    exe_path = str(resolved.get("path") or "")
    if not exe_path:
        return {
            "ok": False,
            "code": "wechat_executable_not_found",
            "error": "未找到微信启动程序，已取消关闭微信。",
            "checked_candidates": resolved.get("checked_candidates") or [],
        }

    termination = terminate_wechat_processes()
    close_deadline = time.monotonic() + max(1.0, float(wait_seconds or 15.0))
    while time.monotonic() < close_deadline:
        if not inspect_wechat_login_state().get("running"):
            break
        time.sleep(0.25)
    if inspect_wechat_login_state().get("running"):
        return {
            "ok": False,
            "code": "wechat_close_failed",
            "error": "微信进程未能完全关闭，请手动退出微信后重试。",
            "termination": termination,
        }

    launched = launch_wechat(exe_path)
    if not launched.get("ok"):
        return {
            "ok": False,
            "code": "wechat_launch_failed",
            "error": str(launched.get("error") or "微信启动失败"),
            "termination": termination,
        }

    start_deadline = time.monotonic() + max(1.0, float(wait_seconds or 15.0))
    while time.monotonic() < start_deadline:
        state = inspect_wechat_login_state()
        if state.get("running"):
            return {
                "ok": True,
                "state": state,
                "launch": launched,
                "termination": termination,
            }
        time.sleep(0.25)
    return {
        "ok": False,
        "code": "wechat_start_timeout",
        "error": "微信已启动但未能检测到登录窗口，请手动启动微信后重试。",
        "termination": termination,
        "launch": launched,
    }
