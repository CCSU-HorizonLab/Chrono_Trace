"""微信密钥捕获（登录引导/状态机/会话查询）——从 bridge.py 拆出（步骤 3 mixin）。

Bridge 继承此 Mixin，方法名不变、前端 API 面与测试零破坏。
"""
from __future__ import annotations

import logging
import time
from typing import Any

logger = logging.getLogger(__name__)


import sys, uuid
from ...services.wechat.account_settings import update_wechat_account_import_state

class KeyCaptureApiMixin:
    """微信密钥捕获（登录引导/状态机/会话查询）"""

    def verify_wechat_key(
        self,
        db_key: str,
        custom_paths: dict[str, str] | None = None,
        account_wxid: str = "",
    ) -> dict[str, Any]:
        """
        验证微信数据库密钥是否有效
        
        Args:
            db_key: 32位hex密钥字符串
            
        Returns:
            {"ok": True} 或 {"ok": False, "error": "..."}
        """
        preferred_paths = custom_paths or self._get_wechat_custom_paths(account_wxid)
        result = self.wechat_service.verify_key(db_key, preferred_paths)
        if result.get("ok") and preferred_paths:
            resolved_wxid = str(preferred_paths.get("account_wxid") or preferred_paths.get("current_user") or self._resolve_account_wxid(account_wxid))
            if resolved_wxid:
                with self._settings_lock:
                    update_wechat_account_import_state(
                        self.settings,
                        resolved_wxid,
                        db_key=db_key,
                        wechat_dir=str(preferred_paths.get("wechat_dir") or "") or None,
                        source="custom" if custom_paths else None,
                    )
                    self._save_settings()
        return result

    def capture_wechat_db_key(
        self,
        account_wxid: str = "",
        timeout_seconds: int = 60,
    ) -> dict[str, Any]:
        """Automatically capture, verify, and persist the active account DB key."""
        try:
            from ...services.wechat.keys import create_key_provider

            provider = create_key_provider(
                wechat_dir=self._key_scan_wechat_dir(account_wxid)
            )
            result = provider.capture_db_key(
                timeout_seconds=timeout_seconds,
                account_wxid=account_wxid,
            )
            if not result.get("ok"):
                return result
            return self._finalize_captured_wechat_db_key(result, account_wxid)
        except Exception as exc:
            logger.error("[Bridge] automatic WeChat DB key capture failed: %s", exc, exc_info=True)
            return {
                "ok": False,
                "code": "capture_failed",
                "error": str(exc),
                "account_wxid": str(account_wxid or ""),
            }

    def _finalize_captured_wechat_db_key(
        self,
        result: dict[str, Any],
        account_wxid: str = "",
    ) -> dict[str, Any]:
        """Verify and persist a key captured by either synchronous or session flow."""
        db_key = str(result.get("db_key") or "").strip().lower()
        key_type = str(result.get("key_type") or "passphrase").strip() or "passphrase"
        raw_keys = result.get("raw_keys") if key_type == "raw" else None
        preferred_paths = self._get_wechat_custom_paths(account_wxid)
        verified = self.wechat_service.verify_key(
            db_key, preferred_paths, key_type=key_type, raw_keys=raw_keys
        )
        if not verified.get("ok"):
            return {
                **result,
                "ok": False,
                "code": "key_verification_failed",
                "error": verified.get("error") or "自动获取的密钥无法验证当前数据库",
            }

        resolved_paths = preferred_paths
        if not resolved_paths:
            try:
                resolved_paths = self.wechat_service.resolve_wechat_paths()
            except Exception:
                resolved_paths = None

        resolved_wxid = str(
            (resolved_paths or {}).get("account_wxid")
            or (resolved_paths or {}).get("current_user")
            or self._resolve_account_wxid(account_wxid)
            or ""
        ).strip()
        if resolved_wxid:
            with self._settings_lock:
                update_wechat_account_import_state(
                    self.settings,
                    resolved_wxid,
                    db_key=db_key,
                    key_type=key_type,
                    raw_keys=raw_keys if key_type == "raw" else {},
                    wechat_dir=str((resolved_paths or {}).get("wechat_dir") or "") or None,
                )
                self._save_settings()

        return {
            **result,
            "ok": True,
            "db_key": db_key,
            "account_wxid": resolved_wxid,
        }

    def get_wechat_key_capture_status(self) -> dict[str, Any]:
        """Inspect whether WeChat is at its login screen or already logged in."""
        try:
            if sys.platform != "win32":
                # Linux：无需重启微信，只需「退出登录后重新登录」触发断点
                from ...services.wechat.keys.gdb_linux import find_linux_wechat_pids

                pids = find_linux_wechat_pids()
                return {
                    "ok": True,
                    "running": bool(pids),
                    "login_state": "logged_in" if pids else "not_running",
                    "processes": [{"pid": p} for p in pids],
                    "restart_required": False,
                }
            from ...services.wechat.keys.flow_win import inspect_wechat_login_state

            return inspect_wechat_login_state()
        except Exception as exc:
            logger.error("[Bridge] inspect WeChat key-capture state failed: %s", exc, exc_info=True)
            return {
                "ok": False,
                "running": False,
                "login_state": "unknown",
                "processes": [],
                "error": str(exc),
            }

    def restart_wechat_for_key_capture(self) -> dict[str, Any]:
        """Restart WeChat for key capture after the frontend obtains confirmation."""
        if sys.platform != "win32":
            # Linux 密钥捕获不需要重启微信（静态内存断点等待重新登录即可）
            return {
                "ok": True,
                "restarted": False,
                "restart_required": False,
                "message": "Linux 无需重启微信，请在微信中退出登录后重新登录。",
            }
        try:
            from ...services.wechat.keys.flow_win import restart_wechat_for_key_capture

            return restart_wechat_for_key_capture()
        except Exception as exc:
            logger.error("[Bridge] restart WeChat for key capture failed: %s", exc, exc_info=True)
            return {
                "ok": False,
                "code": "restart_failed",
                "error": str(exc),
            }

    def start_wechat_db_key_capture(
        self,
        account_wxid: str = "",
        timeout_seconds: int = 120,
    ) -> dict[str, Any]:
        """Install the Hook and return as soon as it is ready for a login event."""
        try:
            from ...services.wechat.keys import create_key_provider

            provider = create_key_provider(
                wechat_dir=self._key_scan_wechat_dir(account_wxid)
            )
            session = provider.create_capture_session(
                timeout_seconds=timeout_seconds,
                account_wxid=account_wxid,
            )
            initial = session.start()
            if initial.get("status") not in {"hook_ready", "captured"}:
                return initial

            session_id = uuid.uuid4().hex
            now_ms = int(time.time() * 1000)
            with self._wechat_key_capture_lock:
                self._wechat_key_capture_sessions[session_id] = {
                    "session": session,
                    "account_wxid": str(account_wxid or ""),
                    "final_result": None,
                    "created_at": now_ms,
                    "updated_at": now_ms,
                }
            # 新增条目时顺带清理过期会话（锁外调用，避免锁内嵌套死锁）
            self._prune_task_dicts()
            return {
                **initial,
                "ok": True,
                "session_id": session_id,
            }
        except Exception as exc:
            logger.error("[Bridge] start WeChat DB key capture failed: %s", exc, exc_info=True)
            return {
                "ok": False,
                "status": "failed",
                "code": "capture_start_failed",
                "error": str(exc),
            }

    def get_wechat_db_key_capture_session(self, session_id: str) -> dict[str, Any]:
        """Return Hook progress; verify and persist the key once it is captured."""
        with self._wechat_key_capture_lock:
            entry = self._wechat_key_capture_sessions.get(str(session_id or ""))
        if not entry:
            return {
                "ok": False,
                "status": "failed",
                "code": "capture_session_not_found",
                "error": "数据库密钥获取会话不存在或已失效。",
            }

        session = entry["session"]
        snapshot = session.snapshot()
        if snapshot.get("status") != "captured":
            return snapshot

        with self._wechat_key_capture_lock:
            final_result = entry.get("final_result")
            if final_result is None:
                final_result = self._finalize_captured_wechat_db_key(
                    snapshot,
                    str(entry.get("account_wxid") or ""),
                )
                entry["final_result"] = final_result
                entry["updated_at"] = int(time.time() * 1000)

        return {
            **final_result,
            "status": "completed" if final_result.get("ok") else "failed",
            "message": "数据库密钥已验证，正在开始导入。"
            if final_result.get("ok")
            else str(final_result.get("error") or "数据库密钥验证失败。"),
        }

