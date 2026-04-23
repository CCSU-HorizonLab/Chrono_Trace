"""Helpers for probing and recovering WeChat UIA accessibility on Windows."""

from __future__ import annotations

import csv
import io
import os
import shutil
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

WECHAT_EXE_BASENAMES: tuple[str, ...] = (
    "WeChat.exe",
    "Weixin.exe",
)
NARRATOR_PROCESS_NAME = "Narrator.exe"


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
    return str(
        resolve_wechat_launch_path(
            detected_exe_path=detected_exe_path,
            extra_candidates=extra_candidates,
        ).get("path")
        or ""
    )


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
    return _run_taskkill(NARRATOR_PROCESS_NAME)


def probe_process(
    *,
    image_name: str = "",
    pid: int = 0,
) -> dict:
    args = ["tasklist", "/FO", "CSV", "/NH"]
    if image_name:
        args.extend(["/FI", f"IMAGENAME eq {image_name}"])
    if pid:
        args.extend(["/FI", f"PID eq {int(pid)}"])

    try:
        completed = subprocess.run(
            args,
            capture_output=True,
            text=True,
            shell=False,
        )
    except Exception as exc:
        return {
            "status": "probe_failed",
            "image_name": str(image_name or ""),
            "pid": int(pid or 0),
            "rows": [],
            "error": str(exc),
        }

    stdout_text = str(completed.stdout or "").strip()
    stderr_text = str(completed.stderr or "").strip()
    if completed.returncode != 0 and not stdout_text:
        return {
            "status": "probe_failed",
            "image_name": str(image_name or ""),
            "pid": int(pid or 0),
            "rows": [],
            "error": stderr_text or f"tasklist exited with code {completed.returncode}",
        }

    if stdout_text.startswith("INFO:"):
        return {
            "status": "not_running",
            "image_name": str(image_name or ""),
            "pid": int(pid or 0),
            "rows": [],
            "error": "",
        }

    rows: list[dict[str, str | int]] = []
    try:
        reader = csv.reader(io.StringIO(stdout_text))
        for raw_row in reader:
            if len(raw_row) < 2:
                continue
            image_value = str(raw_row[0] or "").strip()
            try:
                row_pid = int(str(raw_row[1] or "0").replace(",", ""))
            except Exception:
                row_pid = 0
            rows.append(
                {
                    "image_name": image_value,
                    "pid": row_pid,
                }
            )
    except Exception as exc:
        return {
            "status": "probe_failed",
            "image_name": str(image_name or ""),
            "pid": int(pid or 0),
            "rows": [],
            "error": f"parse_failed: {exc}",
        }

    return {
        "status": "running" if rows else "not_running",
        "image_name": str(image_name or ""),
        "pid": int(pid or 0),
        "rows": rows,
        "error": "",
    }


def wait_for_process(
    *,
    image_name: str = "",
    pid: int = 0,
    timeout: float = 3.0,
    probe_interval: float = 0.25,
) -> dict:
    deadline = time.time() + max(0.0, float(timeout or 0.0))
    last_probe = probe_process(image_name=image_name, pid=pid)
    attempts = 1
    while last_probe.get("status") == "not_running" and time.time() < deadline:
        if probe_interval > 0:
            time.sleep(probe_interval)
        last_probe = probe_process(image_name=image_name, pid=pid)
        attempts += 1
    return {
        **last_probe,
        "attempts": attempts,
        "timeout": float(timeout or 0.0),
        "probe_interval": float(probe_interval or 0.0),
        "verified": last_probe.get("status") == "running",
    }


def _verify_narrator_running(pid: int = 0) -> dict:
    return wait_for_process(
        image_name=NARRATOR_PROCESS_NAME,
        pid=int(pid or 0),
        timeout=3.0,
        probe_interval=0.25,
    )


def _build_narrator_launch_error(verification: dict, fallback_errors: list[str]) -> str:
    status = str(verification.get("status") or "unknown")
    verification_error = str(verification.get("error") or "").strip()
    details = [item for item in fallback_errors if str(item or "").strip()]
    if verification_error:
        details.append(verification_error)
    if details:
        return "; ".join(details)
    return f"Narrator launch could not be verified (status={status})"


def launch_narrator(narrator_path: str = "") -> dict:
    path = narrator_path or default_narrator_path()
    if not Path(path).exists():
        return {
            "ok": False,
            "path": path,
            "error": "Narrator executable not found",
        }

    existing_verification = _verify_narrator_running()
    if existing_verification.get("verified"):
        running_rows = existing_verification.get("rows") or []
        existing_pid = 0
        if running_rows and isinstance(running_rows[0], dict):
            existing_pid = int(running_rows[0].get("pid") or 0)
        return {
            "ok": True,
            "path": path,
            "pid": existing_pid,
            "launch_method": "already_running",
            "verification": existing_verification,
        }

    fallback_errors: list[str] = []

    try:
        process = subprocess.Popen([path], shell=False)
        verification = _verify_narrator_running(int(process.pid or 0))
        if verification.get("verified"):
            return {
                "ok": True,
                "path": path,
                "pid": int(process.pid or 0),
                "launch_method": "popen",
                "verification": verification,
            }
        fallback_errors.append(_build_narrator_launch_error(verification, []))
    except Exception as exc:
        fallback_errors.append(str(exc))

    startfile = getattr(os, "startfile", None)
    if callable(startfile):
        try:
            startfile(path)
            verification = _verify_narrator_running()
            if verification.get("verified"):
                running_rows = verification.get("rows") or []
                started_pid = 0
                if running_rows and isinstance(running_rows[0], dict):
                    started_pid = int(running_rows[0].get("pid") or 0)
                return {
                    "ok": True,
                    "path": path,
                    "pid": started_pid,
                    "launch_method": "startfile",
                    "verification": verification,
                }
            fallback_errors.append("startfile_unverified")
        except Exception as exc:
            fallback_errors.append(f"startfile_failed: {exc}")

    try:
        completed = subprocess.run(
            ["cmd", "/c", "start", "", path],
            capture_output=True,
            text=True,
            shell=False,
        )
        if completed.returncode == 0:
            verification = _verify_narrator_running()
            if verification.get("verified"):
                running_rows = verification.get("rows") or []
                started_pid = 0
                if running_rows and isinstance(running_rows[0], dict):
                    started_pid = int(running_rows[0].get("pid") or 0)
                return {
                    "ok": True,
                    "path": path,
                    "pid": started_pid,
                    "launch_method": "cmd_start",
                    "verification": verification,
                }
            fallback_errors.append("cmd_start_unverified")
        else:
            stderr_text = str(completed.stderr or completed.stdout or "").strip()
            fallback_errors.append(f"cmd_start_failed: {stderr_text or completed.returncode}")
    except Exception as exc:
        fallback_errors.append(f"cmd_start_exception: {exc}")

    try:
        escaped_path = path.replace("'", "''")
        completed = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                f"Start-Process -FilePath '{escaped_path}'",
            ],
            capture_output=True,
            text=True,
            shell=False,
        )
        if completed.returncode == 0:
            verification = _verify_narrator_running()
            if verification.get("verified"):
                running_rows = verification.get("rows") or []
                started_pid = 0
                if running_rows and isinstance(running_rows[0], dict):
                    started_pid = int(running_rows[0].get("pid") or 0)
                return {
                    "ok": True,
                    "path": path,
                    "pid": started_pid,
                    "launch_method": "powershell_start_process",
                    "verification": verification,
                }
            fallback_errors.append("powershell_start_process_unverified")
        else:
            stderr_text = str(completed.stderr or completed.stdout or "").strip()
            fallback_errors.append(f"powershell_start_process_failed: {stderr_text or completed.returncode}")
    except Exception as exc:
        fallback_errors.append(f"powershell_start_process_exception: {exc}")

    final_verification = _verify_narrator_running()
    return {
        "ok": False,
        "path": path,
        "pid": int((final_verification.get("rows") or [{}])[0].get("pid") or 0) if final_verification.get("rows") else 0,
        "verification": final_verification,
        "error": _build_narrator_launch_error(final_verification, fallback_errors),
    }


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
    manual_narrator_timeout: float = 90.0,
    manual_narrator_probe_interval: float = 1.0,
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

    resolution = resolve_wechat_launch_path(
        detected_exe_path=str(initial_probe.get("exe_path") or ""),
        extra_candidates=[wechat_exe] if wechat_exe else [],
    )
    resolved_wechat_exe = str(resolution.get("path") or "")
    emit_progress(
        "prepare_relaunch",
        "检测到微信 UI 树没有展开，将尝试自动修复：关闭微信、打开讲述人并重新启动微信。",
        {
            "resolved_wechat_exe": resolved_wechat_exe,
            "resolution_source": resolution.get("source") or "",
        },
    )
    payload["actions"].append(
        {
            "step": "resolve_wechat_exe",
            "requested_path": wechat_exe,
            "resolved_path": resolved_wechat_exe,
            "resolution_source": resolution.get("source") or "",
            "checked_candidates": list(resolution.get("checked_candidates") or []),
        }
    )
    if not resolved_wechat_exe:
        payload["errors"].append("Unable to resolve WeChat executable path for relaunch")
        payload["actions"].append(
            {
                "step": "abort_before_terminate",
                "reason": "wechat_launch_path_unresolved",
            }
        )
        emit_progress(
            "abort_before_terminate",
            "未找到可用的微信启动路径，本次不会自动关闭微信。请手动确认微信安装位置后再重试。",
            {},
        )
        payload["final_probe"] = initial_probe
        return payload

    emit_progress(
        "launch_narrator",
        "正在确认 Windows 讲述人已启动...",
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
        emit_progress(
            "wait_manual_narrator",
            "未能自动打开 Windows 讲述人。请现在手动打开讲述人；程序会在讲述人就绪后继续关闭并重新打开微信。",
            {
                "verification_status": (
                    (narrator_result.get("verification") or {}).get("status") or "unknown"
                ),
            },
        )
        manual_verification = wait_for_process(
            image_name=NARRATOR_PROCESS_NAME,
            timeout=float(manual_narrator_timeout or 0.0),
            probe_interval=float(manual_narrator_probe_interval or 0.0),
        )
        payload["actions"].append(
            {
                "step": "wait_for_manual_narrator",
                "ok": bool(manual_verification.get("verified")),
                "verification": manual_verification,
            }
        )
        if not manual_verification.get("verified"):
            payload["errors"].append(str(narrator_result.get("error") or "Failed to launch Narrator"))
            payload["actions"].append(
                {
                    "step": "abort_before_terminate",
                    "reason": "manual_narrator_timeout",
                    "verification": manual_verification,
                }
            )
            emit_progress(
                "abort_before_terminate",
                "等待讲述人就绪超时，本次自动修复已停止，本次不会自动关闭微信。",
                {
                    "verification_status": str(manual_verification.get("status") or "unknown"),
                },
            )
            payload["final_probe"] = probe_wechat_uia()
            if stop_narrator_after_check:
                payload["actions"].append(
                    {
                        "step": "terminate_narrator",
                        "result": terminate_narrator(),
                    }
                )
            return payload
        narrator_result = {
            "ok": True,
            "path": str(narrator_result.get("path") or narrator_path or default_narrator_path()),
            "pid": int((manual_verification.get("rows") or [{}])[0].get("pid") or 0) if manual_verification.get("rows") else 0,
            "launch_method": "manual_wait",
            "verification": manual_verification,
        }
        emit_progress(
            "manual_narrator_ready",
            "已检测到讲述人就绪，正在继续自动修复。",
            {"pid": narrator_result.get("pid", 0)},
        )
    if wait_after_narrator > 0:
        time.sleep(wait_after_narrator)

    emit_progress(
        "terminate_wechat",
        "讲述人已确认启动，正在自动关闭当前微信窗口...",
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
