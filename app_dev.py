import os

import time
import atexit
import signal
import subprocess
import logging
import webview
import requests
from backend.app.webview.bridge import Bridge
from backend.app.config import FRONTEND_DIR, DEV_WINDOW_TITLE
from backend.app.logging_config import setup_logging, get_logger

# 配置全局日志（开发模式也写入文件）
setup_logging(level=logging.DEBUG)

logger = get_logger(__name__)


def cleanup_proc_tree(proc: subprocess.Popen):
    if not proc or proc.poll() is not None:
        return
    try:
        if os.name == 'nt':
            try:
                proc.send_signal(signal.CTRL_BREAK_EVENT)
                proc.wait(timeout=3)
            except Exception:
                pass
            try:
                subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], check=False)
            except Exception:
                pass
        else:
            # 整组信号（start_frontend_dev 已 start_new_session 成组）：只杀
            # npm 这个 pid 会留 vite 孤儿占 5173，下次启动检测到端口直接
            # 挂载旧实例——watch 失效时会一直服务旧源码且 HMR 静默不工作
            pgid = None
            try:
                pgid = os.getpgid(proc.pid)
                os.killpg(pgid, signal.SIGINT)
                proc.wait(timeout=3)
            except Exception:
                pass
            if pgid is not None:
                try:
                    os.killpg(pgid, signal.SIGKILL)  # 组已全退时 ESRCH，吞掉
                except Exception:
                    pass
    except Exception:
        pass


def wait_for_dev_server(url: str, timeout_sec: int = 60, interval_sec: float = 0.5):
    start = time.time()
    last_err = None
    while time.time() - start < timeout_sec:
        try:
            resp = requests.get(url, timeout=2)
            if resp.status_code == 200:
                return True
        except Exception as e:
            last_err = e
        time.sleep(interval_sec)
    raise RuntimeError(f"前端 dev server 未在 {timeout_sec}s 内就绪，最后错误: {last_err}")


def start_frontend_dev(cwd_path: str):
    if os.name == 'nt':
        cmd = ["cmd", "/c", "npm", "run", "dev"]
        popen_kwargs = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
    else:
        cmd = ["npm", "run", "dev"]
        # 独立进程组：cleanup_proc_tree 走 killpg 整组清理（见其注释），
        # 否则 npm 退出后 vite 成孤儿占 5173
        popen_kwargs = {"start_new_session": True}

    return subprocess.Popen(
        cmd,
        cwd=cwd_path,
        stdout=None,
        stderr=None,
        shell=False,
        **popen_kwargs,
    )



def main():
    frontend_dir = FRONTEND_DIR
    if not os.path.isdir(frontend_dir):
        raise FileNotFoundError(f"前端目录不存在: {frontend_dir}")

    dev_url = os.getenv('DEV_URL', 'http://localhost:5173')
    bridge = Bridge()

    # 如已存在可达的 dev server，就直接挂载（避免重复启动）
    already_running = False
    try:
        if wait_for_dev_server(dev_url, timeout_sec=2):
            already_running = True
            logger.info(f"检测到已有 dev server：{dev_url}，跳过启动 npm。")
    except Exception:
        pass

    npm_proc = None
    if not already_running:
        logger.info("正在启动前端 dev server (npm run dev)...")
        npm_proc = start_frontend_dev(frontend_dir)
        atexit.register(lambda: cleanup_proc_tree(npm_proc))
        wait_for_dev_server(dev_url, timeout_sec=90)
        logger.info(f"dev server 已就绪：{dev_url}")

    # easy_drag 关闭：与边缘缩放/自绘标题栏拖动（原生 HTCAPTION）抢事件
    window = webview.create_window(DEV_WINDOW_TITLE, url=dev_url, js_api=bridge, frameless=True, width=950, height=800, easy_drag=False)

    # 启动/关闭守卫/退出清理统一走 gui_backend（Linux 强制 Qt 后端）
    from backend.app.webview.gui_backend import run_main_window, hard_exit_after_webview

    run_main_window(window, bridge, debug=True)

    # 关闭窗口后也清理一次（双保险）；随后硬退出兜底（QtWebEngine 收尾段错误）
    cleanup_proc_tree(npm_proc)
    hard_exit_after_webview()


if __name__ == '__main__':
    main()
