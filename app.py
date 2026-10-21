import os

import webview
import logging
from backend.app.webview.bridge import Bridge
from backend.app.config import get_dist_index_path, PROD_WINDOW_TITLE
from backend.app.logging_config import setup_logging, get_logger

# 配置全局日志
setup_logging(level=logging.INFO)

logger = get_logger(__name__)


def main():
    logger.info("启动 Chrono Trace 应用程序")
    bridge = Bridge()
    dist_index = get_dist_index_path()
    if not dist_index:
        raise RuntimeError('未找到前端构建产物，请先执行 npm run build 生成 frontend/webdist/index.html')
    # 默认尺寸/最小尺寸显式给出：WinForms/Qt 的裸默认窗偏小（~800x600），
    # 无框窗口此前又无法缩放，画像等弹窗直接超出视口；min_size 防误拖过小。
    # easy_drag 关闭：页面任意处按住即移窗，会与边缘缩放/自绘标题栏拖动
    # （start_drag 的原生 HTCAPTION 循环）抢事件
    window = webview.create_window(
        PROD_WINDOW_TITLE, url=dist_index, js_api=bridge, frameless=True,
        width=1200, height=720, min_size=(880, 640), easy_drag=False,
    )

    # 启动/关闭守卫/退出清理统一走 gui_backend（Linux 强制 Qt 后端）
    from backend.app.webview.gui_backend import run_main_window, hard_exit_after_webview

    run_main_window(window, bridge)
    hard_exit_after_webview()


if __name__ == '__main__':
    main()
