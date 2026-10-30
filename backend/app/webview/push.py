"""后端→前端实时推送通道（evaluate_js）。

monitor 轮询线程只入队（绝不阻塞采集循环）；常驻 sender 线程 drain 聚合后
单次派发。线程模型同 close_guard 实测结论：evaluate_js 只能在后台线程调
（GUI 线程同步调会与桥接调用互等死锁），JS 侧立即返回不 await。

双通道共用同一队列与 sender 线程：
- realtime：monitor 消息回显。前端入口 window.__chronoRealtimePush
  （App.vue 挂载，转投 chrono:realtime-push CustomEvent），FloatingPanel
  按批次匹配合并上屏；派发失败/窗口未就绪时静默降级，由前端既有 3s
  轮询兜底对账。
- qa：问问微信流式增量。前端入口 window.__chronoQaPush（转投
  chrono:qa-push CustomEvent），Analytics 问答页签按 req_id 匹配打字机
  上屏；推送丢失只丢打字机效果，bridge await 返回值仍是终态对账兜底。

进程单例（get_push_service）：gui_backend 启动时注入 window，bridge 侧
（问答流式回调）直接取用，不经 bridge 实例传递状态。
"""
from __future__ import annotations

import json
import logging
import queue
import threading
import time

logger = logging.getLogger(__name__)

# realtime payload 是 JSON 数组：[{batch_id, account_wxid, messages:[{id,
# sender_attr, content, message_type, timestamp}]}]，消息形状与
# bridge.get_realtime_recent_messages 返回项一致，前端零转换合并。
# qa payload 是 JSON 数组：[{type:"delta", req_id, conversation_id, text}]
_JS_DISPATCHES = {
    "realtime": "window.__chronoRealtimePush && window.__chronoRealtimePush({payload})",
    "qa": "window.__chronoQaPush && window.__chronoQaPush({payload})",
}


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
            "channel": "realtime",
            "payload": {
                "batch_id": batch_id,
                "account_wxid": account_wxid,
                "messages": messages,
            },
        })
        self._ensure_sender()

    def push_qa_event(self, event: dict) -> None:
        """问答流式增量（bridge 工作线程调用）：仅入队，不打断问答主流程。"""
        if not event:
            return
        self._queue.put({"channel": "qa", "payload": event})
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
        # 常驻：空闲时阻塞在 get() 零开销；有事件时经 45ms 合并窗聚合后
        # 单次派发——QA 流式 token 级增量（行间隔可低于 evaluate_js 的
        # 1-5ms 往返）若无窗会退化为每 token 一次 IPC，窗到期即发不再等
        # （realtime 消息回显同窗无感，本就有 3s 轮询兜底）
        while True:
            batch = [self._queue.get()]
            deadline = time.monotonic() + 0.045
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                try:
                    batch.append(self._queue.get(timeout=remaining))
                except queue.Empty:
                    break
            self._dispatch(batch)

    def _dispatch(self, batch: list[dict]) -> None:
        window = self._window
        if window is None:
            return
        by_channel: dict[str, list[dict]] = {}
        for item in batch:
            by_channel.setdefault(item.get("channel") or "", []).append(item.get("payload"))
        for channel, payloads in by_channel.items():
            template = _JS_DISPATCHES.get(channel)
            if not template:
                continue
            try:
                text = json.dumps(payloads, ensure_ascii=False, separators=(",", ":"))
                window.evaluate_js(template.format(payload=text))
            except Exception as exc:
                logger.debug("[push] %s 通道派发失败（前端自有兜底）: %s", channel, exc)


_PUSH_SERVICE: "RealtimePushService | None" = None
_PUSH_LOCK = threading.Lock()


def get_push_service() -> RealtimePushService:
    """进程级单例：gui_backend 启动注入 window，bridge 侧直接取用。"""
    global _PUSH_SERVICE
    with _PUSH_LOCK:
        if _PUSH_SERVICE is None:
            _PUSH_SERVICE = RealtimePushService()
        return _PUSH_SERVICE
