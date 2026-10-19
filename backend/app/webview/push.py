"""后端→前端实时推送通道（evaluate_js）。

monitor 轮询线程只入队（绝不阻塞采集循环）；常驻 sender 线程 drain 聚合后
单次派发。线程模型同 close_guard 实测结论：evaluate_js 只能在后台线程调
（GUI 线程同步调会与桥接调用互等死锁），JS 侧立即返回不 await。

前端入口 window.__chronoRealtimePush（App.vue 挂载，转投 chrono:realtime-push
CustomEvent），FloatingPanel 按批次匹配合并上屏；派发失败/窗口未就绪时
静默降级，由前端既有 3s 轮询兜底对账。
"""
from __future__ import annotations

import json
import logging
import queue
import threading

logger = logging.getLogger(__name__)

# payload 是 JSON 数组：[{batch_id, account_wxid, messages:[{id, sender_attr,
# content, message_type, timestamp}]}]，消息形状与 bridge.get_realtime_recent_messages
# 返回项一致，前端零转换合并
_JS_DISPATCH = "window.__chronoRealtimePush && window.__chronoRealtimePush({payload})"


class RealtimePushService:
    """实时消息推送：入队即返回，sender 线程聚合派发。"""

    def __init__(self) -> None:
        self._window = None
        self._queue: "queue.Queue[dict]" = queue.Queue()
        self._sender: threading.Thread | None = None
        self._sender_lock = threading.Lock()

    def set_window(self, window) -> None:
        self._window = window

    def push_realtime_messages(self, batch_id: str, account_wxid: str,
                               messages: list[dict]) -> None:
        """monitor 轮询线程调用：仅入队，绝不阻塞采集。"""
        if not messages:
            return
        self._queue.put({
            "batch_id": batch_id,
            "account_wxid": account_wxid,
            "messages": messages,
        })
        self._ensure_sender()

    def _ensure_sender(self) -> None:
        with self._sender_lock:
            if self._sender is not None and self._sender.is_alive():
                return
            self._sender = threading.Thread(
                target=self._send_loop, daemon=True, name="realtime-push"
            )
            self._sender.start()

    def _send_loop(self) -> None:
        # 常驻：空闲时阻塞在 get() 零开销；高频消息时 drain 聚合为单次派发
        while True:
            batch = [self._queue.get()]
            while True:
                try:
                    batch.append(self._queue.get_nowait())
                except queue.Empty:
                    break
            self._dispatch(batch)

    def _dispatch(self, batch: list[dict]) -> None:
        window = self._window
        if window is None:
            return
        try:
            payload = json.dumps(batch, ensure_ascii=False, separators=(",", ":"))
            window.evaluate_js(_JS_DISPATCH.format(payload=payload))
        except Exception as exc:
            logger.debug("[push] 实时消息派发失败（前端轮询兜底）: %s", exc)
