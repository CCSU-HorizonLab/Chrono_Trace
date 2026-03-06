import os
import time
import atexit
import signal
import subprocess
import webview
import requests
from backend.app.webview.bridge import Bridge
from backend.app.config import FRONTEND_DIR, DEV_URL_DEFAULT, DEV_WINDOW_TITLE


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
            try:
                proc.send_signal(signal.SIGINT)
                proc.wait(timeout=3)
            except Exception:
                pass
            try:
                proc.kill()
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
    else:
        cmd = ["npm", "run", "dev"]

    return subprocess.Popen(
        cmd,
        cwd=cwd_path,
        stdout=None,
        stderr=None,
        shell=False,
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == 'nt' else 0,
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
            print(f"检测到已有 dev server：{dev_url}，跳过启动 npm。")
    except Exception:
        pass

    npm_proc = None
    if not already_running:
        print("正在启动前端 dev server (npm run dev)...")
        npm_proc = start_frontend_dev(frontend_dir)
        atexit.register(lambda: cleanup_proc_tree(npm_proc))
        wait_for_dev_server(dev_url, timeout_sec=90)
        print(f"dev server 已就绪：{dev_url}")

    window = webview.create_window(DEV_WINDOW_TITLE, url=dev_url, js_api=bridge, frameless=False)

    def on_started():
        """窗口启动后，将窗口引用注入 Bridge（供悬浮窗服务使用）"""
        bridge.set_webview_window(window)

    webview.start(func=on_started, debug=True)

    # 关闭窗口后也清理一次（双保险）
    cleanup_proc_tree(npm_proc)


if __name__ == '__main__':
    main()
