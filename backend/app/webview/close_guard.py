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

# 返回布尔：true=已派发给前端（取消本次关闭）；false/None=前端未就绪（放行）
_CLOSE_REQUEST_JS = (
    "(() => { if (window.__chronoHandleCloseRequest) "
    "{ window.__chronoHandleCloseRequest(); return true; } return false; })()"
)


def attach_close_guard(window, bridge) -> None:
    """在窗口与 Bridge 之间装配关闭确认链路（app.py / app_dev.py 各调用一次）。"""
    state = {"allow": False}

    def _safe_destroy() -> None:
        try:
            window.destroy()
        except Exception as exc:
            logger.error("[CloseGuard] 窗口销毁失败: %s", exc)

    def _dispatch_close_request() -> None:
        dispatched = False
        try:
            dispatched = bool(window.evaluate_js(_CLOSE_REQUEST_JS))
        except Exception as exc:
            logger.warning("[CloseGuard] 前端关闭确认不可用，放行关闭: %s", exc)
        if not dispatched:
            # 前端未就绪/不可用：放行真实关闭
            state["allow"] = True
            threading.Timer(0.1, _safe_destroy).start()

    def _on_closing():
        if state["allow"]:
            return True
        # GUI 线程内同步 evaluate_js 会与 pending 的 JS↔Python 桥接调用互等
        # 死锁（实测：桥接忙时点 X 整窗卡死）——改为后台线程派发
        threading.Timer(0.05, _dispatch_close_request).start()
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
        # 0.5s：js_api 返回序列化慢时仍可能在调用进行中销毁（互等）
        threading.Timer(0.5, _safe_destroy).start()

    bridge.set_close_actions(minimize=_minimize, exit=_exit)
    logger.info("[CloseGuard] 关闭确认已启用")
