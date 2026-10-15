"""pywebview 启动后端选择（Linux 强制 Qt）。

pywebview 6.x 在非 KDE 会话按 [GTK, Qt] 顺序自动探测，venv 装有 PyGObject
时会选中 WebKitGTK——其 window.localStorage 为 null，懒加载路由组件在
setup 阶段即崩（切页白屏：localStorage.getItem / parentNode 系列报错）。
本项目 Linux 标准后端一直是 Qt（requirements-linux.txt：纯 pip 可装、
支持悬浮窗 move/resize/on_top；打包链路已显式排除 GTK 栈），dev 入口
在此显式对齐，避免「打包强制 Qt 正常、dev 被 GTK 抢占白屏」的分裂。
"""
from __future__ import annotations

import logging
import sys

logger = logging.getLogger(__name__)


def start_webview(**kwargs) -> None:
    """按平台启动 webview 事件循环：Linux 显式 qt（Qt 缺失时回退自动探测），其余平台走默认。"""
    import webview

    if sys.platform.startswith("linux"):
        try:
            import webview.platforms.qt  # noqa: F401  # 探测 Qt 后端可导入
        except Exception as exc:
            logger.warning(
                "Qt 后端不可用（%s），回退自动探测——WebKitGTK 下 localStorage 为 null，页面切换将异常", exc
            )
        else:
            logger.info("Linux 强制 pywebview Qt 后端（规避 WebKitGTK localStorage 为 null）")
            webview.start(gui="qt", **kwargs)
            return
    webview.start(**kwargs)
