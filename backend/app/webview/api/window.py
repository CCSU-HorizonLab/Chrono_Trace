"""窗口与悬浮窗（关闭守卫/悬浮模式/拖拽）——从 bridge.py 拆出（步骤 3 mixin）。

Bridge 继承此 Mixin，方法名不变、前端 API 面与测试零破坏。
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class WindowApiMixin:
    """窗口与悬浮窗（关闭守卫/悬浮模式/拖拽）"""

    def set_close_actions(self, minimize=None, exit=None) -> None:
        """由 close_guard 装配关闭确认动作（见 webview/close_guard.py）。"""
        self._close_actions = {"minimize": minimize, "exit": exit}

    def perform_close_action(self, action: str) -> dict[str, Any]:
        """执行关闭按钮选择（前端关闭确认对话框调用）。

        action: "minimize"（最小化到任务栏）| "exit"（退出应用）
        """
        action = str(action or "").strip().lower()
        fn = self._close_actions.get(action)
        if fn is None:
            return {"ok": False, "error": f"未知关闭动作: {action or '(空)'}"}
        try:
            fn()
            return {"ok": True, "action": action}
        except Exception as e:
            logger.error(f"[Bridge] 关闭动作执行失败: {e}")
            return {"ok": False, "error": str(e)}

    def set_webview_window(self, window):
        """设置 PyWebView 窗口引用（由 app_dev.py 启动后注入）"""
        self._webview_window = window
        self._floating_service.set_webview_window(window)

    def prepare_exit(self) -> None:
        """进程退出前的优雅停机（close_guard 在销毁窗口前调用，尽力而为）。

        监听活跃时直接销毁窗口会让 Qt 在 C++ 层 terminate（实测 exit 134）；
        先走 stop_monitoring 完成 checkpoint 与缓冲迁移，再放行销毁。
        """
        try:
            from ...services.realtime.monitor_service import RealtimeMonitorService

            monitor = RealtimeMonitorService()
            if getattr(monitor, "is_monitoring", False):
                logger.info("[Bridge] 退出前停止实时监听（checkpoint+迁移）…")
                result = monitor.stop_monitoring()
                logger.info("[Bridge] 退出前监听已停止: %s", (result or {}).get("message", ""))
        except Exception as exc:
            logger.warning("[Bridge] 退出前停止监听失败（继续退出）: %s}", exc)

    def enter_floating_mode(self) -> dict[str, Any]:
        """
        进入悬浮窗模式：窗口变为紧凑悬浮面板，跟随微信窗口

        Returns:
            {"ok": True, "message": "...", "wechat_found": True/False}
        """
        try:
            return self._floating_service.enter_floating_mode()
        except Exception as e:
            logger.error(f"[Bridge] 进入悬浮模式失败: {e}")
            import traceback
            traceback.print_exc()
            return {'ok': False, 'error': str(e)}

    def exit_floating_mode(self) -> dict[str, Any]:
        """
        退出悬浮窗模式：恢复原始窗口尺寸和位置

        Returns:
            {"ok": True, "message": "..."}
        """
        try:
            return self._floating_service.exit_floating_mode()
        except Exception as e:
            logger.error(f"[Bridge] 退出悬浮模式失败: {e}")
            import traceback
            traceback.print_exc()
            return {'ok': False, 'error': str(e)}

    def get_floating_status(self) -> dict[str, Any]:
        """
        获取悬浮窗状态

        Returns:
            {"ok": True, "is_floating": bool, "wechat_found": bool}
        """
        try:
            return self._floating_service.get_status()
        except Exception as e:
            logger.error(f"[Bridge] 获取悬浮状态失败: {e}")
            return {'ok': False, 'error': str(e)}

    def set_floating_expanded(self, expanded: bool) -> dict[str, Any]:
        """
        动态切换悬浮窗展开态。

        expanded=True: 展开辅助栏所需宽度
        expanded=False: 恢复紧凑宽度
        """
        try:
            return self._floating_service.set_expanded(expanded)
        except Exception as e:
            logger.error(f"[Bridge] 切换悬浮窗展开态失败: {e}")
            import traceback
            traceback.print_exc()
            return {'ok': False, 'error': str(e)}

    def start_floating_drag(self) -> dict[str, Any]:
        """从悬浮面板页头启动原生窗口拖动。"""
        try:
            return self._floating_service.start_drag()
        except Exception as e:
            logger.error(f"[Bridge] 启动悬浮窗拖动失败: {e}")
            return {'ok': False, 'error': str(e)}

    def move_floating_window(self, dx: float, dy: float) -> dict[str, Any]:
        """按屏幕位移移动悬浮窗。"""
        try:
            return self._floating_service.move_by(float(dx), float(dy))
        except Exception as e:
            logger.error(f"[Bridge] 移动悬浮窗失败: {e}")
            return {'ok': False, 'error': str(e)}

