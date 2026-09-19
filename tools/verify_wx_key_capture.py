"""独立验证 py_wx_key 数据库密钥捕获链路。

这个脚本不依赖 Chrono Trace 的 Bridge、前端或数据库导入流程，只验证：

1. 找到指定的微信进程；
2. 安装数据库密钥 Hook；
3. 按 100ms 轮询状态和密钥；
4. 捕获到 64 位十六进制密钥后清理 Hook。

图片密钥接口刻意不调用。
"""

from __future__ import annotations

import argparse
import re
import sys
import time
from typing import Any


KEY_RE = re.compile(r"^[0-9a-fA-F]{64}$")
PROCESS_NAMES = {"wechat.exe", "weixin.exe"}


def configure_utf8_output() -> None:
    """让旧版 Windows 控制台也按 UTF-8 输出中文。"""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="replace")


def find_processes() -> list[tuple[int, str]]:
    """返回当前运行中的微信进程，按 PID 排序。"""
    try:
        import win32api
        import win32con
        import win32process
    except ImportError as exc:  # pragma: no cover - 环境依赖错误
        raise RuntimeError("缺少 pywin32，请先安装项目依赖") from exc

    result: list[tuple[int, str]] = []
    access = win32con.PROCESS_QUERY_INFORMATION | win32con.PROCESS_VM_READ
    for candidate_pid in win32process.EnumProcesses():
        handle = None
        try:
            handle = win32api.OpenProcess(access, False, int(candidate_pid))
            path = str(win32process.GetModuleFileNameEx(handle, 0) or "")
            name = path.rsplit("\\", 1)[-1]
            if name.lower() in PROCESS_NAMES:
                result.append((int(candidate_pid), name))
        except Exception:
            continue
        finally:
            if handle is not None:
                try:
                    win32api.CloseHandle(handle)
                except Exception:
                    pass
    return sorted(result)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="独立验证 wx_key 数据库密钥捕获")
    parser.add_argument("--pid", type=int, help="指定要 Hook 的微信 PID；不传则自动选择")
    parser.add_argument("--timeout", type=float, default=120.0, help="等待密钥的秒数，默认 120")
    return parser.parse_args()


def status_message(extension: Any) -> None:
    """尽可能取空状态队列；状态接口异常不影响主轮询。"""
    try:
        while True:
            message, level = extension.get_status_message()
            if not message:
                return
            level_name = {0: "信息", 1: "成功", 2: "错误"}.get(int(level), "状态")
            print(f"[{level_name}] {message}", flush=True)
    except Exception as exc:
        print(f"[警告] 读取 Hook 状态失败：{exc}", flush=True)


def main() -> int:
    configure_utf8_output()
    args = parse_args()
    if args.timeout <= 0:
        print("等待时间必须大于 0 秒", file=sys.stderr)
        return 2

    try:
        import wx_key
    except ImportError as exc:
        print(f"无法导入 wx_key：{exc}", file=sys.stderr)
        return 2

    processes = find_processes()
    if args.pid is not None:
        candidates = [(pid, name) for pid, name in processes if pid == args.pid]
        if not candidates:
            print(f"未找到指定 PID 的微信进程：{args.pid}", file=sys.stderr)
            return 2
        pid, process_name = candidates[0]
    elif len(processes) == 1:
        pid, process_name = processes[0]
    elif not processes:
        print("未找到 WeChat.exe 或 Weixin.exe，请先启动微信", file=sys.stderr)
        return 2
    else:
        print("检测到多个微信进程，请用 --pid 明确指定：")
        for candidate_pid, candidate_name in processes:
            print(f"  {candidate_pid}\t{candidate_name}")
        return 2

    print(f"目标进程：{process_name}（PID {pid}）")
    print("仅验证数据库密钥 Hook，不会调用图片密钥接口。")
    print("提示：Hook 成功后，请重新登录微信或执行会触发数据库读取的操作。")

    initialized = False
    try:
        initialized = bool(wx_key.initialize_hook(pid))
        status_message(wx_key)
        if not initialized:
            print(f"Hook 初始化失败：{wx_key.get_last_error_msg()}", file=sys.stderr)
            return 1

        print("Hook 初始化成功，开始每 100ms 轮询……", flush=True)
        deadline = time.monotonic() + float(args.timeout)
        while time.monotonic() < deadline:
            status_message(wx_key)
            payload = wx_key.poll_key_data()
            if isinstance(payload, dict):
                candidate = str(payload.get("key") or "").strip()
                if KEY_RE.fullmatch(candidate):
                    print(f"捕获成功：{candidate[:4]}……{candidate[-4:]}（已隐藏中间内容）")
                    return 0
                if candidate:
                    print(f"忽略格式异常的密钥数据（长度 {len(candidate)}）", file=sys.stderr)
            time.sleep(0.1)

        print("等待超时：没有捕获到新的数据库密钥。", file=sys.stderr)
        print("请确认微信已重新登录、目标 PID 未变化，并在下次登录前重新运行本脚本。", file=sys.stderr)
        return 1
    finally:
        if initialized:
            try:
                wx_key.cleanup_hook()
            finally:
                print("Hook 已清理。")


if __name__ == "__main__":
    raise SystemExit(main())
