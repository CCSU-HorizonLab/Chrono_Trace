import os
os.environ["TORCH_COMPILE_DISABLE"] = "1"
from backend.app.runtime_overrides import activate_gpu_overlay_path

activate_gpu_overlay_path()

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
    window = webview.create_window(PROD_WINDOW_TITLE, url=dist_index, js_api=bridge, frameless=False)

    def on_started():
        """窗口启动后，将窗口引用注入 Bridge（供 Win32 悬浮窗服务使用）"""
        bridge.set_webview_window(window)

    webview.start(func=on_started)


if __name__ == '__main__':
    main()
