"""WeChat desktop version detection for realtime providers."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Iterable

from .models import WeChatVersionInfo

logger = logging.getLogger(__name__)

WINDOW_CLASS_CANDIDATES: tuple[str, ...] = (
    "WeChatMainWndForPC",
    "WeChatMainWndForPC_New",
    "WeChat",
    "Qt51514QWindowIcon",
)

WINDOW_EXE_BASENAMES: tuple[str, ...] = (
    "wechat.exe",
    "weixin.exe",
    "wechatappex.exe",
)


def _iter_window_classes() -> Iterable[str]:
    for cls_name in WINDOW_CLASS_CANDIDATES:
        yield cls_name


def _map_version_to_profile(version: str, hwnd: int, hwnd_class_name: str) -> str:
    version = str(version or "").strip()
    if version.startswith("4.0.5"):
        return "wechat_405"
    if version.startswith("4.1."):
        return "wechat_41x"

    # UI fallback when file-version probing fails.
    if hwnd_class_name == "WeChatMainWndForPC":
        return "wechat_405"
    if hwnd_class_name == "Qt51514QWindowIcon" and hwnd:
        return "wechat_405"
    if hwnd_class_name in {"WeChatMainWndForPC_New", "WeChat"} and hwnd:
        return "wechat_41x"
    return ""


def _get_exe_path(hwnd: int):
    try:
        import win32api
        import win32con
        import win32process
    except Exception:
        return ""

    try:
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        process = win32api.OpenProcess(
            win32con.PROCESS_QUERY_INFORMATION | win32con.PROCESS_VM_READ,
            False,
            pid,
        )
        try:
            return win32process.GetModuleFileNameEx(process, 0)
        finally:
            try:
                win32api.CloseHandle(process)
            except Exception:
                pass
    except Exception as exc:
        logger.debug("Unable to resolve WeChat executable path for hwnd=%s: %s", hwnd, exc)
        return ""


def _iter_matching_windows():
    try:
        import win32gui
    except Exception:
        return []

    matches = []

    def callback(hwnd, _):
        try:
            if not win32gui.IsWindowVisible(hwnd):
                return
            class_name = str(win32gui.GetClassName(hwnd) or "")
            title = str(win32gui.GetWindowText(hwnd) or "")
        except Exception:
            return

        exe_path = _get_exe_path(hwnd)
        exe_name = Path(exe_path).name.lower()
        title_lower = title.lower()
        looks_like_wechat = (
            class_name in WINDOW_CLASS_CANDIDATES
            or exe_name in WINDOW_EXE_BASENAMES
            or title in {"微信", "WeChat"}
            or "wechat" in title_lower
        )
        if not looks_like_wechat:
            return

        matches.append(
            {
                "hwnd": int(hwnd),
                "class_name": class_name,
                "title": title,
                "exe_path": exe_path,
                "exe_name": exe_name,
            }
        )

    win32gui.EnumWindows(callback, None)
    return matches


def _select_best_window(candidates) -> dict[str, str | int] | None:
    if not candidates:
        return None

    def score(item):
        value = 0
        if item["class_name"] in {"WeChatMainWndForPC", "WeChatMainWndForPC_New", "WeChat"}:
            value += 30
        if item["class_name"] == "Qt51514QWindowIcon":
            value += 25
        if item["exe_name"] in {"wechat.exe", "weixin.exe"}:
            value += 20
        if item["title"] in {"微信", "WeChat"}:
            value += 10
        if item["exe_name"] == "wechatappex.exe":
            value -= 10
        return value

    return max(candidates, key=score)


def detect_running_wechat() -> WeChatVersionInfo:
    """Detect the active desktop WeChat version and supported listener profile."""
    try:
        import win32api
    except Exception as exc:  # pragma: no cover - import depends on runtime OS
        logger.debug("WeChat runtime detection unavailable: %s", exc)
        return WeChatVersionInfo()

    selected = _select_best_window(_iter_matching_windows())
    if not selected:
        return WeChatVersionInfo()

    hwnd = int(selected["hwnd"])
    hwnd_class_name = str(selected["class_name"])
    exe_path = str(selected["exe_path"])
    version = ""

    if exe_path:
        try:
            info = win32api.GetFileVersionInfo(exe_path, "\\")
            ms = info["FileVersionMS"]
            ls = info["FileVersionLS"]
            version = ".".join(
                str(part)
                for part in (
                    win32api.HIWORD(ms),
                    win32api.LOWORD(ms),
                    win32api.HIWORD(ls),
                    win32api.LOWORD(ls),
                )
            )
        except Exception as exc:
            logger.debug("Unable to read WeChat executable version: %s", exc)

    return WeChatVersionInfo(
        version=version,
        listener_profile=_map_version_to_profile(version, hwnd, hwnd_class_name),
        hwnd=hwnd,
        exe_path=exe_path,
    )
