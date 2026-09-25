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


class WeChatKeyCaptureSession:
    """Background capture session which reports when the database Hook is ready."""

    def __init__(
        self,
        *,
        timeout_seconds: int = 120,
        account_wxid: str = "",
        wechat_start_wait_seconds: int = 30,
        hook_install_retry_seconds: int = 20,
    ):
        self.timeout_seconds = max(1, int(timeout_seconds or 120))
        self.account_wxid = str(account_wxid or "")
        # 重启流程刚拉起微信时，进程出现与模块加载完成之间存在窗口期，
        # 两个宽限预算让会话在这段窗口内持续等待/重试而不是立刻失败。
        self.wechat_start_wait_seconds = max(0, int(wechat_start_wait_seconds or 0))
        self.hook_install_retry_seconds = max(0, int(hook_install_retry_seconds or 0))
        self._lock = threading.Lock()
        self._ready = threading.Event()
        self._thread: threading.Thread | None = None
        self._status = "preparing"
        self._message = "正在准备数据库密钥监听。"
        self._result: dict[str, Any] | None = None

    def start(self, ready_timeout_seconds: int | None = None) -> dict[str, Any]:
        """Start capture and wait only until Hook installation succeeds or fails.

        ``ready_timeout_seconds=None`` derives the wait budget from the startup
        grace windows so callers never time out before the session itself
        has finished waiting for WeChat to (re)start.
        """
        with self._lock:
            if self._thread is None:
                self._thread = threading.Thread(
                    target=self._run,
                    name="wechat-db-key-capture",
                    daemon=True,
                )
                self._thread.start()

        if ready_timeout_seconds is None:
            ready_timeout_seconds = (
                self.wechat_start_wait_seconds + self.hook_install_retry_seconds + 10
            )
        if not self._ready.wait(timeout=max(1, int(ready_timeout_seconds))):
            return {
                "ok": False,
                "status": "failed",
                "code": "hook_prepare_timeout",
                "error": "安装数据库密钥监听超时。",
            }
        return self.snapshot()

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            payload = {
                "ok": self._status not in {"failed", "timed_out"},
                "status": self._status,
                "message": self._message,
                "account_wxid": self.account_wxid,
            }
            if self._result:
                payload.update(self._result)
            return payload

    def _set_result(self, status: str, message: str, result: dict[str, Any] | None = None) -> None:
        with self._lock:
            self._status = status
            self._message = message
            self._result = dict(result or {})

    def _run(self) -> None:
        extension = WeChatKeyProvider._load_extension()
        if extension is None:
            self._set_result(
                "failed",
                "未安装 wx_key 自动取密钥组件，请使用手动输入密钥。",
                {"code": "extension_missing", "error": "未安装 wx_key 自动取密钥组件，请使用手动输入密钥。"},
            )
            self._ready.set()
            return

        # 微信可能刚被重启流程拉起：进程尚未出现时持续等待，
        # 避免上一环节刚关闭/启动微信就直接判定“微信未运行”。
        pid: int | None = None
        error = ""
        process_deadline = time.monotonic() + self.wechat_start_wait_seconds
        while True:
            pid, error = WeChatKeyProvider._find_wechat_pid()
            if pid:
                break
            if time.monotonic() >= process_deadline:
                self._set_result("failed", error, {"code": "wechat_not_running", "error": error})
                self._ready.set()
                return
            self._set_result("preparing", "正在等待微信进程启动…")
            time.sleep(0.5)

        acquired = False
        try:
            with WeChatKeyProvider._hook_lock:
                # 进程已存在但模块可能还没加载完（版本信息暂时读不到），
                # 在宽限窗口内持续重试安装 Hook，等微信初始化完成。
                init_deadline = time.monotonic() + self.hook_install_retry_seconds
                while True:
                    init_detail = ""
                    try:
                        acquired = bool(extension.initialize_hook(pid))
                        if not acquired:
                            init_detail = WeChatKeyProvider._last_error(extension)
                    except Exception as exc:
                        logger.warning("wx_key initialize_hook failed: %s", exc)
                        init_detail = WeChatKeyProvider._last_error(extension) or str(exc)
                        acquired = False

                    if acquired:
                        break

                    if time.monotonic() >= init_deadline:
                        self._set_result(
                            "failed",
                            init_detail,
                            {"code": "hook_initialize_failed", "error": init_detail, "pid": pid},
                        )
                        return
                    self._set_result("preparing", "微信正在启动，等待初始化完成后安装密钥监听…")
                    time.sleep(0.5)

                self._set_result(
                    "hook_ready",
                    "数据库密钥监听已安装，请在微信中完成登录。",
                    {"pid": pid},
                )
                self._ready.set()
                deadline = time.monotonic() + self.timeout_seconds
                while time.monotonic() < deadline:
                    try:
                        payload = extension.poll_key_data()
                    except Exception as exc:
                        logger.warning("wx_key poll_key_data failed: %s", exc)
                        self._set_result(
                            "failed",
                            "读取数据库密钥监听数据失败。",
                            {"code": "hook_poll_failed", "error": str(exc), "pid": pid},
                        )
                        return

                    candidate = payload.get("key") if isinstance(payload, dict) else None
                    candidate = str(candidate or "").strip()
                    if _DB_KEY_RE.fullmatch(candidate):
                        self._set_result(
                            "captured",
                            "已捕获数据库密钥，正在验证。",
                            {"db_key": candidate.lower(), "pid": pid},
                        )
                        return
                    time.sleep(0.1)

                timeout_error = "等待微信登录触发数据库密钥超时，请改用手动输入密钥。"
                self._set_result(
                    "timed_out",
                    timeout_error,
                    {"code": "capture_timeout", "error": timeout_error, "pid": pid},
                )
        finally:
            if not self._ready.is_set():
                self._ready.set()
            if acquired:
                try:
                    extension.cleanup_hook()
                except Exception:
                    logger.debug("wx_key cleanup_hook failed", exc_info=True)


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
            from ...realtime.providers.detector import detect_running_wechat
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

    def create_capture_session(
        self,
        timeout_seconds: int = 120,
        account_wxid: str = "",
        wechat_start_wait_seconds: int = 30,
        hook_install_retry_seconds: int = 20,
    ) -> WeChatKeyCaptureSession:
        """Create a session that reports once the Hook has been installed."""
        return WeChatKeyCaptureSession(
            timeout_seconds=timeout_seconds,
            account_wxid=account_wxid,
            wechat_start_wait_seconds=wechat_start_wait_seconds,
            hook_install_retry_seconds=hook_install_retry_seconds,
        )
