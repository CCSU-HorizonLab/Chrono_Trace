"""窗口关闭守卫：拦截标题栏 X 点击，交由前端确认（最小化/退出/取消）。

pywebview 的 closing 事件处理器返回 False 即取消本次关闭。首次 X 点击被
拦截后通知前端弹出确认对话框；用户选择经 bridge.perform_close_action 执行：
- minimize：window.minimize()（留在任务栏）
- exit：置放行标志后延迟 destroy（js_api 调用线程内直接销毁会与等待中的
  JS 调用互相等待死锁）
前端不可用（如页面加载失败）时不阻塞退出。双平台通用（Qt / EdgeChromium
均支持 closing 取消）。
"""
from __future__ import annotations

import logging
import threading

logger = logging.getLogger(__name__)

_CLOSE_REQUEST_JS = (
    "if (window.__chronoHandleCloseRequest) { window.__chronoHandleCloseRequest(); }"
)


def attach_close_guard(window, bridge) -> None:
    """在窗口与 Bridge 之间装配关闭确认链路（app.py / app_dev.py 各调用一次）。"""
    state = {"allow": False}

    def _on_closing():
        if state["allow"]:
            return True
        try:
            window.evaluate_js(_CLOSE_REQUEST_JS)
        except Exception as exc:
            logger.warning("[CloseGuard] 前端关闭确认不可用，放行关闭: %s", exc)
            return True
        return False

    try:
        window.events.closing += _on_closing
    except Exception as exc:
        logger.warning("[CloseGuard] closing 事件订阅失败（不拦截关闭）: %s", exc)
        return

    def _minimize() -> None:
        window.minimize()

    def _exit() -> None:
        state["allow"] = True
        threading.Timer(0.15, window.destroy).start()

    bridge.set_close_actions(minimize=_minimize, exit=_exit)
    logger.info("[CloseGuard] 关闭确认已启用")
