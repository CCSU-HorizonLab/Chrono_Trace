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
    window = webview.create_window(PROD_WINDOW_TITLE, url=dist_index, js_api=bridge, frameless=True)

    # 启动/关闭守卫/退出清理统一走 gui_backend（Linux 强制 Qt 后端）
    from backend.app.webview.gui_backend import run_main_window, hard_exit_after_webview

    run_main_window(window, bridge)
    hard_exit_after_webview()


if __name__ == '__main__':
    main()
