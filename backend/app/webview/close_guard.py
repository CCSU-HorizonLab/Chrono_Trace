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

    def _on_closing():
        if state["allow"]:
            return True
        try:
            dispatched = window.evaluate_js(_CLOSE_REQUEST_JS)
        except Exception as exc:
            logger.warning("[CloseGuard] 前端关闭确认不可用，放行关闭: %s", exc)
            return True
        # 页面加载中/刷新中：前端回调未注册（求值无异常但返回 false）——放行，
        # 否则点 X 无任何反应且无法退出（此前返回 False 无条件吞掉关闭事件）
        return not bool(dispatched)

    try:
        window.events.closing += _on_closing
    except Exception as exc:
        logger.warning("[CloseGuard] closing 事件订阅失败（不拦截关闭）: %s", exc)
        return

    def _minimize() -> None:
        window.minimize()

    def _exit() -> None:
        state["allow"] = True

        def _destroy() -> None:
            try:
                window.destroy()
            except Exception as exc:  # Timer 线程内异常不能无声吞掉——否则窗口卡在“已退出未退出”
                logger.error("[CloseGuard] 窗口销毁失败: %s", exc)

        # 0.5s：js_api 返回序列化慢于 0.15s 时仍可能在调用进行中销毁（互等）
        threading.Timer(0.5, _destroy).start()

    bridge.set_close_actions(minimize=_minimize, exit=_exit)
    logger.info("[CloseGuard] 关闭确认已启用")
