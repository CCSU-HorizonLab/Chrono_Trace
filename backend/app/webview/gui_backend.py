"""pywebview 启动后端选择与主窗口生命周期（Linux 强制 Qt）。

pywebview 6.x 在非 KDE 会话按 [GTK, Qt] 顺序自动探测，venv 装有 PyGObject
时会选中 WebKitGTK——其 window.localStorage/sessionStorage 为 null，懒加载
路由组件在 setup 阶段即崩（切页白屏）。本项目 Linux 标准后端一直是 Qt
（requirements-linux.txt：纯 pip 可装、支持悬浮窗 move/resize/on_top；打包
链路已显式排除 GTK 栈），dev 入口在此显式对齐，避免「打包强制 Qt 正常、
dev 被 GTK 抢占白屏」的分裂。
"""
from __future__ import annotations

import logging
import sys

logger = logging.getLogger(__name__)


def start_webview(**kwargs) -> None:
    """按平台启动 webview 事件循环：Linux 显式 qt（导入/启动失败均回退自动探测），其余平台走默认。"""
    import webview

    if sys.platform.startswith("linux"):
        try:
            import webview.platforms.qt  # noqa: F401  # 探测 Qt 后端可导入
        except Exception as exc:
            logger.warning(
                "Qt 后端不可用（%s），回退自动探测——WebKitGTK 下 storage 为 null，页面切换将异常", exc
            )
        else:
            logger.info("Linux 强制 pywebview Qt 后端（规避 WebKitGTK 下 storage 为 null）")
            try:
                webview.start(gui="qt", **kwargs)
                return
            except Exception as exc:
                # Qt 模块可导入但跑不起来（如缺 libGL/libxcb 平台插件）：
                # 回退自动探测保底可用，而不是启动即死
                logger.warning("Qt 后端启动失败（%s），回退自动探测", exc)
    webview.start(**kwargs)


def run_main_window(window, bridge, **start_kwargs) -> None:
    """主窗口生命周期统一入口：注入 Bridge → 挂关闭守卫 → 起事件循环 → Qt 退出清理。

    dev（app_dev.py）与生产（app.py）共用此路径，防止两端启动/清理参数悄然分叉。
    """
    from .close_guard import attach_close_guard
    from .qt_teardown import shutdown_qt_webengine_cleanly

    def on_started():
        """窗口启动后，将窗口引用注入 Bridge（供悬浮窗服务使用）"""
        bridge.set_webview_window(window)

    attach_close_guard(window, bridge)
    start_webview(func=on_started, **start_kwargs)
    shutdown_qt_webengine_cleanly()


def hard_exit_after_webview(exit_code: int = 0) -> None:
    """Qt 后端退出兜底：窗口已关、数据已守卫保存、页面已先行析构后硬退出。

    QtWebEngine 在解释器收尾阶段的 profile/子进程原生析构仍偶发段错误
    （退出码 139）。事件循环退出后不再有任何需要"优雅"完成的清理——
    冲刷日志与标准流后直接 os._exit，让退出码干净。仅 Linux 生效；
    Windows(WebView2) 原样返回走正常解释器收尾。调用方须先完成各自的
    子进程清理（dev 的 npm dev server），os._exit 不跑 atexit。
    """
    import os

    if not sys.platform.startswith("linux"):
        return
    try:
        sys.stdout.flush()
        sys.stderr.flush()
        logging.shutdown()
    except Exception:
        pass
    os._exit(exit_code)
