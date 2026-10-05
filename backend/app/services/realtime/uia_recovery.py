"""Windows UIA recovery: detection and auto-recovery.

Extracted from monitor_service.py (step 4A). Windows-specific (lazy win32 imports).
"""
from __future__ import annotations

import logging
import time
from typing import Any

logger = logging.getLogger(__name__)


from .providers.base import UINotAccessibleError
_print = print

class UiaRecoveryMixin:
    """UIA recovery: shell detection / auto/manual recovery."""

    def _bring_wechat_to_front(self):
        """使用 Win32 API 将微信窗口强制置顶到所有窗口之上"""
        try:
            import ctypes
            import time as _time

            user32 = ctypes.windll.user32

            # 优先从当前监听后端获取已有的窗口句柄（最可靠）
            hwnd = None
            if self.wx and hasattr(self.wx, '_api') and hasattr(self.wx._api, 'HWND'):
                hwnd = self.wx._api.HWND
                _print(f"[置顶] 从当前监听后端获取到窗口句柄: {hwnd}")

            # fallback: 按类名搜索
            if not hwnd:
                for cls_name in ('WeChatMainWndForPC', 'WeChat', 'WeChatMainWndForPC_New', 'Qt51514QWindowIcon'):
                    hwnd = user32.FindWindowW(cls_name, None)
                    if hwnd:
                        _print(f"[置顶] 通过类名 {cls_name} 找到窗口句柄: {hwnd}")
                        break
            
            if not hwnd:
                _print("⚠️ 未找到微信窗口句柄，请手动切换到微信")
                return False

            # 如果窗口最小化，先恢复
            SW_RESTORE = 9
            if user32.IsIconic(hwnd):
                user32.ShowWindow(hwnd, SW_RESTORE)
                _time.sleep(0.3)

            # 使用 SetWindowPos + HWND_TOPMOST 强制置顶
            HWND_TOPMOST = -1
            HWND_NOTOPMOST = -2
            SWP_NOMOVE = 0x0002
            SWP_NOSIZE = 0x0001
            SWP_SHOWWINDOW = 0x0040

            # 步骤1: 临时设为 TOPMOST（强制到所有窗口之上）
            user32.SetWindowPos(
                hwnd, HWND_TOPMOST,
                0, 0, 0, 0,
                SWP_NOMOVE | SWP_NOSIZE | SWP_SHOWWINDOW
            )

            _time.sleep(0.5)

            # 步骤2: 取消 TOPMOST（恢复正常，不永久置顶）
            user32.SetWindowPos(
                hwnd, HWND_NOTOPMOST,
                0, 0, 0, 0,
                SWP_NOMOVE | SWP_NOSIZE | SWP_SHOWWINDOW
            )

            user32.SetForegroundWindow(hwnd)
            for _ in range(15):
                if user32.GetForegroundWindow() == hwnd:
                    break
                _time.sleep(0.1)
            _time.sleep(0.3)

            _print("✅ 微信窗口已强制置顶到最前方")
            return True

        except Exception as e:
            _print(f"⚠️ 自动置顶微信窗口失败: {e}，请手动切换")
            return False

    def _reset_wechat_instance(self):
        """Reset the cached listener instance so the next retry starts clean."""
        if self.wx is not None:
            try:
                stop_listening = getattr(self.wx, 'StopListening', None)
                if callable(stop_listening):
                    stop_listening()
            except Exception:
                pass
        self.provider = None
        self.wx = None
        self._provider_name = ''
        self._listener_profile = ''
        self._wechat_version = ''

    def _create_wechat_instance(self):
        """Create a fresh realtime provider instance."""
        try:
            from backend.wxauto4 import WeChat
        except ModuleNotFoundError:
            from wxauto4 import WeChat

        self._reset_wechat_instance()
        self.wx = WeChat(start_listener=False, backend=self._listener_backend)
        self.provider = getattr(self.wx, '_provider', None)
        self._provider_name = getattr(self.wx, 'backend_name', '')
        self._listener_profile = getattr(self.wx, 'listener_profile', '')
        self._wechat_version = getattr(self.wx, 'wechat_version', '')
        nickname = getattr(self.wx, 'nickname', '')
        if nickname:
            _print(
                "[RealtimeMonitorService] 监听后端初始化成功, "
                f"backend={self._provider_name or 'unknown'}, "
                f"profile={self._listener_profile or 'unknown'}, "
                f"version={self._wechat_version or 'unknown'}, "
                f"当前账号: {nickname}"
            )
        return self.wx

    def _clear_uia_manual_restart_guard(self) -> None:
        self._uia_manual_restart_guard_until = 0.0
        self._uia_manual_restart_guard_reason = ""
        self._uia_manual_restart_guard_phase = ""

    def _has_active_uia_manual_restart_guard(self) -> bool:
        guard_until = float(getattr(self, "_uia_manual_restart_guard_until", 0.0) or 0.0)
        if guard_until <= 0:
            return False
        if time.time() >= guard_until:
            self._clear_uia_manual_restart_guard()
            return False
        return True

    def _set_uia_manual_restart_guard(
        self,
        *,
        phase: str = "",
        reason: str = "",
        duration_seconds: float | None = None,
    ) -> None:
        duration = float(duration_seconds or self._UIA_MANUAL_RESTART_GUARD_SECONDS)
        self._uia_manual_restart_guard_until = time.time() + max(1.0, duration)
        self._uia_manual_restart_guard_phase = str(phase or "")
        self._uia_manual_restart_guard_reason = str(reason or "")

    def _build_uia_manual_restart_guard_guidance(
        self,
        *,
        include_prefix: bool = True,
    ) -> str:
        remaining_seconds = max(
            1,
            int(float(getattr(self, "_uia_manual_restart_guard_until", 0.0) or 0.0) - time.time()),
        )
        prefix = ""
        if include_prefix:
            prefix = "微信界面当前不可访问（UIA 树没有展开，只能看到外层壳窗口）。"
        return (
            f"{prefix}程序刚执行过一次自动修复并关闭过微信。"
            f"为避免你手动打开微信后又被程序再次关闭，接下来约 {remaining_seconds} 秒内不会再次自动关闭微信。"
            "请保持 Windows 讲述人（Narrator）开启，手动打开并登录微信，确认微信主界面稳定显示后再重试。"
        )

    def _extract_uia_recovery_snapshot(self) -> dict:
        payload = dict(self._last_uia_recovery or {})
        actions = payload.get("actions") or []
        if not isinstance(actions, list):
            actions = []

        action_steps = [
            str(action.get("step") or "")
            for action in actions
            if isinstance(action, dict) and str(action.get("step") or "")
        ]
        launch_narrator_action = next(
            (
                action
                for action in actions
                if isinstance(action, dict) and str(action.get("step") or "") == "launch_narrator"
            ),
            {},
        )
        abort_action = next(
            (
                action
                for action in actions
                if isinstance(action, dict) and str(action.get("step") or "") == "abort_before_terminate"
            ),
            {},
        )
        manual_wait_action = next(
            (
                action
                for action in actions
                if isinstance(action, dict) and str(action.get("step") or "") == "wait_for_manual_narrator"
            ),
            {},
        )
        final_probe = payload.get("final_probe") or {}
        final_status = str(final_probe.get("status") or "")
        terminated_wechat = "terminate_wechat" in action_steps

        verification_payload = (
            manual_wait_action.get("verification")
            or launch_narrator_action.get("verification")
            or {}
        )
        if not isinstance(verification_payload, dict):
            verification_payload = {}
        narrator_verification = {
            "ok": bool(manual_wait_action.get("ok") if manual_wait_action else launch_narrator_action.get("ok")),
            "path": str(launch_narrator_action.get("path") or ""),
            "pid": int(
                (manual_wait_action.get("verification") or {}).get("pid")
                or launch_narrator_action.get("pid")
                or 0
            ),
            "status": str(verification_payload.get("status") or ""),
            "verified": bool(verification_payload.get("verified")),
            "attempts": int(verification_payload.get("attempts") or 0),
            "error": str(
                verification_payload.get("error")
                or launch_narrator_action.get("error")
                or ""
            ),
        }

        summary = ""
        if action_steps:
            if abort_action:
                abort_reason = str(abort_action.get("reason") or "")
                if abort_reason == "manual_narrator_timeout":
                    summary = "等待手动打开讲述人超时，本次自动修复已停止。"
                else:
                    summary = "讲述人尚未就绪，本次自动修复已暂停。"
            elif final_status == "accessible":
                if narrator_verification["verified"]:
                    summary = "讲述人已验证启动，微信 UI 树已恢复。"
                else:
                    summary = "微信 UI 树已恢复。"
            elif terminated_wechat:
                if narrator_verification["verified"]:
                    summary = f"讲述人已验证启动，但微信 UI 树仍未恢复（{final_status or 'unknown'}）。"
                else:
                    summary = f"自动修复已执行，但微信 UI 树仍未恢复（{final_status or 'unknown'}）。"
            elif final_status:
                summary = f"自动修复结束，当前 UIA 状态为 {final_status}。"

        return {
            "summary": summary,
            "final_status": final_status,
            "phase": str(payload.get("phase") or ""),
            "source_error": str(payload.get("source_error") or ""),
            "action_steps": action_steps,
            "aborted": bool(abort_action),
            "abort_reason": str(abort_action.get("reason") or ""),
            "narrator_verification": narrator_verification,
        }

    def _attempt_auto_recover_shell_only_uia(self, phase: str, error_text: str = "") -> bool:
        """Mark shell-only UIA recovery as pending and wait for explicit user confirmation."""
        if self._has_active_uia_manual_restart_guard():
            self._uia_recovery_required = False
            self._uia_recovery_in_progress = False
            self._uia_recovery_context = {}
            self._chat_error = self._build_uia_manual_restart_guard_guidance()
            _print(
                "[RealtimeMonitorService] shell-only UIA 再次出现，但当前处于手动重开保护期，"
                f"不再自动关闭微信 (phase={phase}, error={error_text})"
            )
            return False

        if self._uia_recovery_attempts >= 1:
            _print("[RealtimeMonitorService] UIA 自动修复已尝试过，跳过重复恢复")
            return False

        self._uia_recovery_attempts += 1
        self._uia_recovery_required = True
        self._uia_recovery_in_progress = False
        self._uia_recovery_context = {
            "phase": phase,
            "error_text": error_text,
        }
        self._chat_error = (
            "检测到微信 UI 树没有展开。请先确认自动修复；确认后程序会关闭微信、打开讲述人并重新启动微信。"
        )
        _print(
            f"[RealtimeMonitorService] 检测到 shell-only UIA，等待用户确认自动修复 "
            f"(phase={phase}, error={error_text})"
        )
        return False

    def run_confirmed_uia_recovery(self) -> dict:
        """Run the UIA recovery flow after the user confirms it in the frontend."""
        if self._uia_recovery_in_progress:
            return {
                "success": False,
                "message": "自动修复正在进行中",
                "error": "自动修复正在进行中",
            }

        if not self._uia_recovery_required and not self._uia_recovery_context:
            return {
                "success": False,
                "message": "当前没有待确认的自动修复任务",
                "error": "当前没有待确认的自动修复任务",
            }

        try:
            from .providers.recovery import recover_shell_only_wechat_uia
        except Exception as exc:
            _print(f"[RealtimeMonitorService] 无法加载 UIA 恢复模块: {exc}")
            return {
                "success": False,
                "message": "无法加载自动修复模块",
                "error": str(exc),
            }

        self._uia_recovery_required = False
        self._uia_recovery_in_progress = True
        self._chat_error = "已确认自动修复，正在准备关闭微信并启动讲述人..."

        def on_progress(step: str, message: str, extra: dict) -> None:
            del extra
            self._chat_error = message
            _print(f"[RealtimeMonitorService] UIA 自动修复进度[{step}]: {message}")

        try:
            payload = recover_shell_only_wechat_uia(
                recover=True,
                recovery_mode="relaunch_with_narrator",
                wait_after_launch=3.0,
                probe_interval=3.0,
                max_probes=20,
                stop_narrator_on_success=True,
                progress_callback=on_progress,
            )
        except Exception as exc:
            self._uia_recovery_in_progress = False
            self._chat_error = self._build_shell_only_uia_guidance(auto_attempted=True)
            _print(f"[RealtimeMonitorService] UIA 自动修复执行异常: {exc}")
            return {
                "success": False,
                "message": "自动修复执行异常",
                "error": self._chat_error,
            }
        payload["phase"] = str((self._uia_recovery_context or {}).get("phase", ""))
        payload["source_error"] = str((self._uia_recovery_context or {}).get("error_text", ""))
        self._last_uia_recovery = payload
        self._uia_recovery_in_progress = False
        self._uia_recovery_context = {}
        actions = payload.get("actions") or []
        terminated_wechat = any(
            str(action.get("step") or "") == "terminate_wechat"
            for action in actions
            if isinstance(action, dict)
        )

        final_probe = payload.get("final_probe") or {}
        if final_probe.get("status") == "accessible":
            _print("[RealtimeMonitorService] 微信 UIA 自动修复成功，继续初始化监听后端")
            self._clear_uia_manual_restart_guard()
            self._chat_error = ""
            recovery_snapshot = self._extract_uia_recovery_snapshot()
            return {
                "success": True,
                "message": "自动修复成功",
                "final_status": final_probe.get("status"),
                "uia_recovery_summary": recovery_snapshot.get("summary", ""),
                "uia_recovery_actions": recovery_snapshot.get("action_steps", []),
                "uia_recovery_aborted": recovery_snapshot.get("aborted", False),
                "narrator_verification": recovery_snapshot.get("narrator_verification", {}),
            }

        if terminated_wechat:
            self._set_uia_manual_restart_guard(
                phase=payload.get("phase") or "",
                reason=str(final_probe.get("status") or "") or "unknown",
            )
            final_status_text = str(final_probe.get("status") or "").strip()
            self._chat_error = (
                (f"当前检测状态：{final_status_text}。" if final_status_text else "")
                + self._build_uia_manual_restart_guard_guidance()
            )
        else:
            recovery_snapshot = self._extract_uia_recovery_snapshot()
            abort_reason = str(recovery_snapshot.get("abort_reason") or "")
            if abort_reason == "manual_narrator_timeout":
                self._chat_error = (
                    "程序正在等待你手动打开 Windows 讲述人，但在限定时间内没有检测到讲述人就绪。"
                    "请先手动打开讲述人，再重新执行自动修复。"
                )
            elif abort_reason == "narrator_launch_unverified":
                self._chat_error = (
                    "程序未能自动打开 Windows 讲述人。请先手动打开讲述人，"
                    "确认讲述人已经运行后，再重新执行自动修复。"
                )
            else:
                self._chat_error = (
                    "程序尚未自动关闭微信，因为这台电脑上没有解析到可用的微信启动路径。"
                    + self._build_shell_only_uia_guidance(
                        auto_attempted=False,
                        final_status=str(final_probe.get("status") or ""),
                        include_prefix=False,
                    )
                )
        _print(
            "[RealtimeMonitorService] 微信 UIA 自动修复失败: "
            f"final_status={final_probe.get('status')}, errors={payload.get('errors')}"
        )
        recovery_snapshot = self._extract_uia_recovery_snapshot()
        return {
            "success": False,
            "message": "自动修复失败",
            "error": self._chat_error,
            "final_status": final_probe.get("status"),
            "uia_recovery_summary": recovery_snapshot.get("summary", ""),
            "uia_recovery_actions": recovery_snapshot.get("action_steps", []),
            "uia_recovery_aborted": recovery_snapshot.get("aborted", False),
            "narrator_verification": recovery_snapshot.get("narrator_verification", {}),
        }

    def _create_wechat_instance_with_recovery(self, phase: str) -> None:
        try:
            self._create_wechat_instance()
            self._clear_uia_manual_restart_guard()
            return
        except Exception as exc:
            error_text = str(exc)
            if isinstance(exc, UINotAccessibleError) or ('ui_not_accessible' in error_text.lower()):
                self._attempt_auto_recover_shell_only_uia(phase=phase, error_text=error_text)
            raise

    def _format_listener_init_error(self, exc: Exception) -> str:
        error_text = str(exc)
        if isinstance(exc, UINotAccessibleError) or ('ui_not_accessible' in error_text.lower()):
            if self._has_active_uia_manual_restart_guard():
                return "微信窗口已找到，但" + self._build_uia_manual_restart_guard_guidance(include_prefix=False)
            if self._last_uia_recovery:
                final_probe = self._last_uia_recovery.get("final_probe") or {}
                final_status = final_probe.get("status") or "unknown"
                actions = self._last_uia_recovery.get("actions") or []
                terminated_wechat = any(
                    str(action.get("step") or "") == "terminate_wechat"
                    for action in actions
                    if isinstance(action, dict)
                )
                if not terminated_wechat:
                    return (
                        "微信窗口已找到，但当前这次启动只暴露了外层壳窗口。"
                        "程序没有自动关闭微信，因为当前机器上未确认到可用的微信启动路径。"
                        + self._build_shell_only_uia_guidance(
                            auto_attempted=False,
                            final_status=final_status,
                            include_prefix=False,
                        )
                    )
                return (
                    "微信窗口已找到，但当前这次启动只暴露了外层壳窗口。"
                    f"程序已尝试自动修复，当前状态: {final_status}。"
                    + self._build_shell_only_uia_guidance(auto_attempted=True, include_prefix=False)
                )
            return "微信窗口已找到，但" + self._build_shell_only_uia_guidance(auto_attempted=False)
        return f'请确保微信已启动并登录: {error_text}'

    def _build_shell_only_uia_guidance(
        self,
        auto_attempted: bool,
        final_status: str = "",
        include_prefix: bool = True,
    ) -> str:
        prefix = ""
        if include_prefix:
            prefix = "微信界面当前不可访问（UIA 树没有展开，只能看到外层壳窗口）。"
        attempted = "程序已尝试自动修复（关闭微信、打开讲述人并重新启动微信），但仍未恢复。" if auto_attempted else ""
        final_status_text = f"当前检测状态：{final_status}。" if final_status else ""
        return (
            f"{prefix}{attempted}{final_status_text}"
            "请按顺序手动处理：先完全退出微信，保持 Windows 讲述人（Narrator）开启，"
            "再手动重新打开并登录微信，确认微信主界面正常显示后回到时痕再试。"
        )

    def _get_foreground_window_info(self) -> dict:
        """Return basic diagnostics for the current foreground window."""
        try:
            import ctypes

            user32 = ctypes.windll.user32
            hwnd = user32.GetForegroundWindow()
            title_buffer = ctypes.create_unicode_buffer(512)
            user32.GetWindowTextW(hwnd, title_buffer, len(title_buffer))

            class_buffer = ctypes.create_unicode_buffer(256)
            user32.GetClassNameW(hwnd, class_buffer, len(class_buffer))
            return {
                'hwnd': int(hwnd or 0),
                'title': title_buffer.value,
                'class_name': class_buffer.value,
            }
        except Exception as e:
            return {
                'hwnd': 0,
                'title': '',
                'class_name': '',
                'error': str(e),
            }

