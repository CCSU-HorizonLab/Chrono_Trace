"""Automatic WeChat database-key capture through the optional ``wx_key`` extension.

The extension is intentionally loaded lazily.  Chrono Trace must continue to
support manual key entry when the native extension is not installed or when
the running WeChat process cannot be hooked.
"""

from __future__ import annotations

import importlib
import logging
from pathlib import Path
import re
import threading
import time
from typing import Any

logger = logging.getLogger(__name__)

_DB_KEY_RE = re.compile(r"^[0-9a-fA-F]{64}$")


class WeChatKeyProvider:
    """Capture a database key from the currently running WeChat process."""

    _hook_lock = threading.Lock()

    @staticmethod
    def _load_extension() -> Any:
        try:
            return importlib.import_module("wx_key")
        except Exception as exc:  # pragma: no cover - depends on local install
            logger.info("wx_key extension unavailable: %s", exc)
            return None

    @staticmethod
    def _find_wechat_pid() -> tuple[int | None, str]:
        """Use the existing Windows WeChat detector and resolve its PID."""
        try:
            from ..realtime.providers.detector import detect_running_wechat
            import win32api
            import win32con
            import win32process
        except Exception as exc:  # pragma: no cover - Windows-only runtime
            return None, f"微信进程检测不可用: {exc}"

        try:
            info = detect_running_wechat()
            hwnd = int(getattr(info, "hwnd", 0) or 0)
            if hwnd:
                _, pid = win32process.GetWindowThreadProcessId(hwnd)
                if pid:
                    return int(pid), ""

            # Some Weixin builds expose no matching top-level window.  Fall
            # back to the executable path so minimized/login windows still
            # participate in the same automatic flow.
            access = win32con.PROCESS_QUERY_INFORMATION | win32con.PROCESS_VM_READ
            for candidate_pid in win32process.EnumProcesses():
                handle = None
                try:
                    handle = win32api.OpenProcess(access, False, int(candidate_pid))
                    exe_path = str(win32process.GetModuleFileNameEx(handle, 0) or "")
                    if Path(exe_path).name.lower() in {"wechat.exe", "weixin.exe"}:
                        return int(candidate_pid), ""
                except Exception:
                    continue
                finally:
                    if handle is not None:
                        try:
                            win32api.CloseHandle(handle)
                        except Exception:
                            pass

            return None, "未检测到正在运行的微信进程"
        except Exception as exc:
            logger.debug("Unable to resolve WeChat PID", exc_info=True)
            return None, f"获取微信进程 PID 失败: {exc}"

    @staticmethod
    def _last_error(extension: Any) -> str:
        try:
            message = str(extension.get_last_error_msg() or "").strip()
            if message:
                return message
        except Exception:
            pass
        return "微信数据库密钥 Hook 初始化失败"

    def capture_db_key(
        self,
        timeout_seconds: int = 60,
        account_wxid: str = "",
    ) -> dict[str, Any]:
        """Capture and return a validated 64-character hex database key.

        This method only uses the database-key Hook API.  Image-key APIs are
        deliberately not called here.
        """
        extension = self._load_extension()
        if extension is None:
            return {
                "ok": False,
                "code": "extension_missing",
                "error": "未安装 wx_key 自动取密钥组件，请使用手动输入密钥",
                "account_wxid": str(account_wxid or ""),
            }

        pid, error = self._find_wechat_pid()
        if not pid:
            return {
                "ok": False,
                "code": "wechat_not_running",
                "error": error,
                "account_wxid": str(account_wxid or ""),
            }

        timeout = max(1, int(timeout_seconds or 60))
        acquired = False
        try:
            with self._hook_lock:
                try:
                    acquired = bool(extension.initialize_hook(pid))
                except Exception as exc:
                    logger.warning("wx_key initialize_hook failed: %s", exc)
                    return {
                        "ok": False,
                        "code": "hook_initialize_failed",
                        "error": self._last_error(extension),
                        "detail": str(exc),
                        "pid": pid,
                        "account_wxid": str(account_wxid or ""),
                    }

                if not acquired:
                    return {
                        "ok": False,
                        "code": "hook_initialize_failed",
                        "error": self._last_error(extension),
                        "pid": pid,
                        "account_wxid": str(account_wxid or ""),
                    }

                deadline = time.monotonic() + timeout
                while time.monotonic() < deadline:
                    try:
                        payload = extension.poll_key_data()
                    except Exception as exc:
                        logger.warning("wx_key poll_key_data failed: %s", exc)
                        return {
                            "ok": False,
                            "code": "hook_poll_failed",
                            "error": str(exc),
                            "pid": pid,
                            "account_wxid": str(account_wxid or ""),
                        }

                    candidate = payload.get("key") if isinstance(payload, dict) else None
                    candidate = str(candidate or "").strip()
                    if _DB_KEY_RE.fullmatch(candidate):
                        return {
                            "ok": True,
                            "db_key": candidate.lower(),
                            "pid": pid,
                            "account_wxid": str(account_wxid or ""),
                        }
                    time.sleep(0.1)

                return {
                    "ok": False,
                    "code": "capture_timeout",
                    "error": "等待微信产生数据库密钥超时，请重新登录微信后重试",
                    "pid": pid,
                    "account_wxid": str(account_wxid or ""),
                }
        finally:
            if acquired:
                try:
                    extension.cleanup_hook()
                except Exception:
                    logger.debug("wx_key cleanup_hook failed", exc_info=True)
