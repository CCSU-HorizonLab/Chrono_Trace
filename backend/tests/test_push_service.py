"""推送通道测试：双通道（realtime/qa）派发路由与进程单例。

evaluate_js 派发是同步直调（窗口替身记录 JS 表达式），不走 sender 线程
轮询——单测只验 _dispatch 的路由与打包，线程模型属 close_guard 实录范畴。
"""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.webview.push import RealtimePushService, get_push_service


class _FakeWindow:
    def __init__(self):
        self.js_calls: list[str] = []

    def evaluate_js(self, code: str):
        self.js_calls.append(code)


def test_qa_events_dispatch_to_qa_channel():
    svc = RealtimePushService()
    window = _FakeWindow()
    svc.set_window(window)
    # 直接构造队列项测 _dispatch 路由（不经 push_qa_event 入队——那会启动
    # sender 线程抢先消费，与本测试的手动消费构成竞态）
    svc._dispatch([{"channel": "qa", "payload": {"type": "delta", "req_id": "r1", "conversation_id": 1, "text": "你"}}])
    assert len(window.js_calls) == 1
    assert window.js_calls[0].startswith("window.__chronoQaPush")
    payload = json.loads(window.js_calls[0][len("window.__chronoQaPush && window.__chronoQaPush(") : -1])
    assert payload == [{"type": "delta", "req_id": "r1", "conversation_id": 1, "text": "你"}]


def test_mixed_batch_dispatched_per_channel():
    """同批聚合按通道分组：realtime 走原入口数组、qa 走新入口数组。"""
    svc = RealtimePushService()
    window = _FakeWindow()
    svc.set_window(window)
    batch = [
        {"channel": "realtime", "payload": {"batch_id": "b1", "messages": []}},
        {"channel": "qa", "payload": {"type": "delta", "req_id": "r1", "conversation_id": 1, "text": "好"}},
        {"channel": "qa", "payload": {"type": "delta", "req_id": "r1", "conversation_id": 1, "text": "的"}},
    ]
    svc._dispatch(batch)
    assert len(window.js_calls) == 2
    calls = {c.split(" && ")[0] for c in window.js_calls}
    assert calls == {"window.__chronoRealtimePush", "window.__chronoQaPush"}
    qa_call = next(c for c in window.js_calls if "__chronoQaPush" in c)
    # 同通道多事件聚合成一次派发（数组）
    payload = json.loads(qa_call[qa_call.index("(") + 1 : -1])
    assert [p["text"] for p in payload] == ["好", "的"]


def test_dispatch_without_window_is_silent():
    svc = RealtimePushService()
    svc._dispatch([{"channel": "qa", "payload": {"type": "delta", "req_id": "r", "conversation_id": 1, "text": "x"}}])  # 不应抛（窗口未就绪静默降级）


def test_get_push_service_is_process_singleton():
    assert get_push_service() is get_push_service()
