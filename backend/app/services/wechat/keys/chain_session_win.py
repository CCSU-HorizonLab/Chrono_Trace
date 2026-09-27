"""Windows 密钥捕获链会话：只读扫描优先 → wx_key hook 登录捕获回退。

状态机与 WeChatKeyCaptureSession / LinuxKeyCaptureSession 同形（见 base.py）：
- 扫描阶段在 start() 返回前完成（秒级）：命中即 captured（免重启）；
- 未命中则挂起 wx_key 内层会话并置 hook_ready（提示重启登录），此后的
  snapshot() 动态代理内层状态，前端既有轮询流程零改动。
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Any, Optional

logger = logging.getLogger(__name__)


class WindowsChainSession:
    def __init__(self, *, wechat_dir: str = "", timeout_seconds: int = 120,
                 account_wxid: str = "", wxkey_provider=None):
        self.wechat_dir = str(wechat_dir or "").strip()
        self.timeout_seconds = max(30, int(timeout_seconds or 120))
        self.account_wxid = str(account_wxid or "")
        self._wxkey_provider = wxkey_provider
        self._lock = threading.Lock()
        self._ready = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._inner = None          # wx_key 回退会话（激活后 snapshot 代理）
        self._inner_terminal = False
        self._status = "preparing"
        self._message = "正在准备密钥捕获。"
        self._result: Optional[dict[str, Any]] = None

    # ---------- 对外（与其余会话同形） ----------

    def start(self, ready_timeout_seconds: Optional[int] = None) -> dict[str, Any]:
        with self._lock:
            if self._thread is None:
                self._thread = threading.Thread(
                    target=self._run, name="win-key-chain-capture", daemon=True
                )
                self._thread.start()
        if ready_timeout_seconds is None:
            ready_timeout_seconds = 60
        if not self._ready.wait(timeout=max(1, int(ready_timeout_seconds))):
            return {
                "ok": False, "status": "failed",
                "code": "hook_prepare_timeout", "error": "密钥捕获准备超时。",
            }
        return self.snapshot()

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            inner = self._inner
        if inner is not None and not self._inner_terminal:
            snap = inner.snapshot()
            if snap.get("status") in {"captured", "failed", "timed_out"}:
                self._inner_terminal = True
            return snap
        with self._lock:
            payload = {
                "ok": self._status not in {"failed", "timed_out"},
                "status": self._status,
                "message": self._message,
                "account_wxid": self.account_wxid,
            }
            if self._result:
                payload.update(self._result)
            return payload

    # ---------- 内部 ----------

    def _set_result(self, status: str, message: str,
                    result: Optional[dict[str, Any]] = None) -> None:
        with self._lock:
            self._status = status
            self._message = message
            self._result = dict(result or {})

    def _run(self) -> None:
        # 阶段一：只读扫描（免重启；wechat_dir 缺失时跳过）
        if self.wechat_dir:
            self._set_result("preparing", "正在只读扫描微信进程内存（免重启）…")
            try:
                from .scan_win import scan_wechat_raw_keys
                scan = scan_wechat_raw_keys(
                    self.wechat_dir, timeout_seconds=min(60, self.timeout_seconds)
                )
                if scan.get("ok"):
                    self._set_result(
                        "captured", "只读扫描捕获成功。",
                        {
                            "db_key": scan.get("db_key"),
                            "key_type": scan.get("key_type", "raw"),
                            "raw_keys": scan.get("raw_keys") or {},
                            "pid": scan.get("pid"),
                        },
                    )
                    self._ready.set()
                    return
                logger.info("[KeyChain] 扫描未命中: %s", scan.get("error"))
            except Exception as exc:  # 扫描异常不阻断回退
                logger.info("[KeyChain] 扫描异常（转登录捕获）: %s", exc)

        # 阶段二：wx_key hook 登录捕获（现役方案）
        self._set_result("preparing", "扫描未命中，转登录捕获（需重启微信并重新登录）…")
        try:
            inner = self._wxkey_provider.create_capture_session(
                timeout_seconds=self.timeout_seconds, account_wxid=self.account_wxid
            )
        except Exception as exc:
            self._set_result("failed", f"登录捕获会话创建失败: {exc}",
                             {"code": "capture_start_failed", "error": str(exc)})
            self._ready.set()
            return

        initial = inner.start(ready_timeout_seconds=45)
        with self._lock:
            self._inner = inner
            self._inner_terminal = initial.get("status") in {
                "captured", "failed", "timed_out",
            }
        self._ready.set()

        # 代理等待内层终态
        deadline = time.monotonic() + self.timeout_seconds + 60
        while time.monotonic() < deadline:
            snap = inner.snapshot()
            if snap.get("status") in {"captured", "failed", "timed_out"}:
                with self._lock:
                    self._inner_terminal = True
                return
            time.sleep(0.3)
