"""微信进程管理工具（Windows 专属）。

探测运行中的微信窗口与版本、解析/启动/终止微信进程——服务密钥抓取
（keys/wx_key_win 找 PID、keys/flow_win 重启微信）等链路。win32 导入
全部函数内延迟，Linux 上调用返回空结果不报错。
"""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

logger = logging.getLogger(__name__)

WECHAT_PROCESS_NAMES: tuple[str, ...] = (
    "Weixin.exe",
    "WeChat.exe",
    "WeChatAppEx.exe",
)

DEFAULT_WECHAT_EXE_CANDIDATES: tuple[Path, ...] = (
    Path(r"D:\Program files\Weixin\Weixin.exe"),
    Path(r"C:\Program Files\Tencent\WeChat\WeChat.exe"),
)

WECHAT_EXE_BASENAMES: tuple[str, ...] = (
    "WeChat.exe",
    "Weixin.exe",
)

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


@dataclass
class WeChatVersionInfo:
    version: str = ""
    listener_profile: str = ""
    hwnd: int = 0
    exe_path: str = ""


# ---------- 运行探测 ----------

def _map_version_to_profile(
    version: str,
    hwnd: int,
    hwnd_class_name: str,
    exe_basename: str = "",
) -> str:
    version = str(version or "").strip()
    exe_basename = Path(str(exe_basename or "")).name.lower()
    if version.startswith("4.0.5"):
        return "wechat_405"
    if version.startswith("4.1."):
        return "wechat_41x"

    # UI fallback when file-version probing fails.
    if exe_basename == "weixin.exe" and hwnd:
        return "wechat_41x"
    if hwnd_class_name == "WeChatMainWndForPC":
        return "wechat_405"
    if hwnd_class_name == "Qt51514QWindowIcon" and hwnd:
        if exe_basename == "wechat.exe":
            return "wechat_405"
        if exe_basename == "weixin.exe":
            return "wechat_41x"
        return ""
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
        listener_profile=_map_version_to_profile(version, hwnd, hwnd_class_name, exe_path),
        hwnd=hwnd,
        exe_path=exe_path,
    )


# ---------- 启动路径解析 ----------

def _as_path(value: str | Path | None) -> Path | None:
    if not value:
        return None
    try:
        return Path(str(value))
    except Exception:
        return None


def _iter_related_wechat_paths(path: Path | None) -> Iterable[Path]:
    if path is None:
        return []

    candidates: list[Path] = [path]
    try:
        parent = path.parent
        grand_parent = parent.parent
    except Exception:
        parent = None
        grand_parent = None

    for base_dir in (parent, grand_parent):
        if base_dir is None:
            continue
        for exe_name in WECHAT_EXE_BASENAMES:
            candidates.append(base_dir / exe_name)
    return candidates


def _iter_registry_wechat_paths() -> Iterable[Path]:
    try:
        import winreg
    except Exception:
        return []

    subkeys = (
        r"Software\Microsoft\Windows\CurrentVersion\App Paths\WeChat.exe",
        r"Software\Microsoft\Windows\CurrentVersion\App Paths\Weixin.exe",
        r"Software\WOW6432Node\Microsoft\Windows\CurrentVersion\App Paths\WeChat.exe",
        r"Software\WOW6432Node\Microsoft\Windows\CurrentVersion\App Paths\Weixin.exe",
    )
    roots = []
    for root_name in ("HKEY_CURRENT_USER", "HKEY_LOCAL_MACHINE"):
        root = getattr(winreg, root_name, None)
        if root is not None:
            roots.append(root)

    results: list[Path] = []
    for root in roots:
        for subkey in subkeys:
            try:
                with winreg.OpenKey(root, subkey) as key:
                    value, _ = winreg.QueryValueEx(key, None)
            except Exception:
                continue
            path = _as_path(value)
            if path is not None:
                results.append(path)
                results.extend(_iter_related_wechat_paths(path))
    return results


def _iter_env_default_wechat_paths() -> Iterable[Path]:
    roots = [
        os.environ.get("ProgramFiles", r"C:\Program Files"),
        os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
        os.environ.get("LocalAppData", ""),
    ]
    relative_paths = (
        Path(r"Tencent\WeChat\WeChat.exe"),
        Path(r"Tencent\WeChat\Weixin.exe"),
        Path(r"Tencent\Weixin\Weixin.exe"),
        Path(r"WeChat\WeChat.exe"),
        Path(r"Weixin\Weixin.exe"),
    )

    results: list[Path] = []
    for root in roots:
        root_path = _as_path(root)
        if root_path is None:
            continue
        for relative_path in relative_paths:
            results.append(root_path / relative_path)
    results.extend(DEFAULT_WECHAT_EXE_CANDIDATES)
    return results


def _iter_path_search_candidates() -> Iterable[Path]:
    results: list[Path] = []
    for exe_name in WECHAT_EXE_BASENAMES:
        resolved = shutil.which(exe_name)
        path = _as_path(resolved)
        if path is not None:
            results.append(path)
    return results


def resolve_wechat_launch_path(
    detected_exe_path: str = "",
    extra_candidates: Iterable[str | Path] | None = None,
) -> dict:
    ordered_candidates: list[tuple[str, Path]] = []
    seen: set[str] = set()

    def add_candidate(source: str, candidate: str | Path | None) -> None:
        path = _as_path(candidate)
        if path is None:
            return
        key = str(path).strip().lower()
        if not key or key in seen:
            return
        seen.add(key)
        ordered_candidates.append((source, path))

    for candidate in _iter_related_wechat_paths(_as_path(detected_exe_path)):
        add_candidate("detected", candidate)
    for candidate in extra_candidates or ():
        for expanded in _iter_related_wechat_paths(_as_path(candidate)):
            add_candidate("extra", expanded)
    for candidate in _iter_registry_wechat_paths():
        add_candidate("registry", candidate)
    for candidate in _iter_path_search_candidates():
        add_candidate("path", candidate)
    for candidate in _iter_env_default_wechat_paths():
        add_candidate("default", candidate)

    checked_candidates: list[str] = []
    for source, path in ordered_candidates:
        checked_candidates.append(str(path))
        try:
            if path.exists():
                return {
                    "path": str(path),
                    "source": source,
                    "checked_candidates": checked_candidates,
                }
        except Exception:
            continue

    return {
        "path": "",
        "source": "",
        "checked_candidates": checked_candidates,
    }


def pick_wechat_launch_path(
    detected_exe_path: str = "",
    extra_candidates: Iterable[str | Path] | None = None,
) -> str:
    return str(
        resolve_wechat_launch_path(
            detected_exe_path=detected_exe_path,
            extra_candidates=extra_candidates,
        ).get("path")
        or ""
    )


# ---------- 进程启动/终止 ----------

def launch_wechat(exe_path: str) -> dict:
    if not exe_path:
        return {"ok": False, "path": "", "error": "WeChat executable path not resolved"}
    if not Path(exe_path).exists():
        return {"ok": False, "path": exe_path, "error": "WeChat executable not found"}
    try:
        process = subprocess.Popen([exe_path], shell=False)
        return {
            "ok": True,
            "path": exe_path,
            "pid": int(process.pid or 0),
            "launch_method": "popen",
        }
    except Exception as exc:
        first_error = str(exc)

    startfile = getattr(os, "startfile", None)
    if callable(startfile):
        try:
            startfile(exe_path)
            return {
                "ok": True,
                "path": exe_path,
                "pid": 0,
                "launch_method": "startfile",
            }
        except Exception as exc:
            first_error = f"{first_error}; startfile_failed: {exc}"

    try:
        completed = subprocess.run(
            ["cmd", "/c", "start", "", exe_path],
            capture_output=True,
            text=True,
            shell=False,
        )
        if completed.returncode == 0:
            return {
                "ok": True,
                "path": exe_path,
                "pid": 0,
                "launch_method": "cmd_start",
            }
        stderr_text = str(completed.stderr or completed.stdout or "").strip()
        if stderr_text:
            first_error = f"{first_error}; cmd_start_failed: {stderr_text}"
    except Exception as exc:
        first_error = f"{first_error}; cmd_start_exception: {exc}"

    return {
        "ok": False,
        "path": exe_path,
        "error": first_error,
    }


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
