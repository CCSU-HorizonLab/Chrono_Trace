"""Qt WebEngine 退出期清理（Linux Qt 后端专用）。

退出时 QtWebEngine 析构 profile 而页面对象仍存活会打
「Release of profile requested but WebEnginePage still not deleted.
Expect troubles !」告警（偶发伴随退出崩溃/挂起）。规范修法是让
QWebEnginePage/QWebEngineView 先于 profile 析构——webview.start()
返回后（事件循环已退出）手动 deleteLater 并强制派发延迟删除事件。
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def shutdown_qt_webengine_cleanly() -> None:
    """显式先删页面/视图再放 profile 析构；非 Qt 后端静默跳过。"""
    try:
        from qtpy.QtCore import QCoreApplication, QEvent
        from qtpy.QtWidgets import QApplication
        from qtpy.QtWebEngineWidgets import QWebEngineView
    except Exception:
        return  # Windows(WebView2) 或无 Qt 环境：不适用

    try:
        app = QApplication.instance()
        if app is None:
            return
        pages = []
        for widget in app.topLevelWidgets():
            if isinstance(widget, QWebEngineView):
                page = widget.page()
                if page is not None:
                    pages.append(page)
                    page.deleteLater()
                widget.deleteLater()
        if not pages:
            return
        # 事件循环已退出，deleteLater 不会自然派发——手动冲刷延迟删除队列，
        # 再跑一轮事件确保视图/page 析构先于 profile
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        app.processEvents()
        logger.debug("[Qt清理] 已先行析构 %d 个 WebEnginePage", len(pages))
    except Exception as exc:
        logger.debug("[Qt清理] 跳过（%s）", exc)
