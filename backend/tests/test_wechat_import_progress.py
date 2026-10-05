"""异步微信导入任务的注册表/进度查询/防重入/TTL 清理测试。

bridge.import_wechat_data 为异步任务模式（daemon 线程 + task dict +
get_import_progress 轮询），本文件用 FakeService 驱动 worker 线程的
全生命周期，不落盘真实微信数据。
"""

import os
import sys
import threading
import time


sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.webview.bridge import Bridge


def make_bridge(service) -> Bridge:
    """partial Bridge：只装配导入域与 _prune_task_dicts 触碰的注册表。"""
    bridge = Bridge.__new__(Bridge)
    bridge._wechat_import_tasks = {}
    bridge._wechat_import_lock = threading.Lock()
    bridge._suggestion_streams = {}
    bridge._suggestion_stream_lock = threading.Lock()
    bridge._wechat_key_capture_sessions = {}
    bridge._wechat_key_capture_lock = threading.Lock()
    bridge._model_download_status = {}
    bridge._model_download_lock = threading.Lock()
    bridge._resolve_account_wxid = lambda wxid="": "wxid_test"
    bridge._get_wechat_custom_paths = lambda wxid="": {}
    bridge._resolve_wechat_account = lambda wxid="": {}
    bridge._save_wechat_import_baseline = lambda *a, **k: None
    bridge.wechat_service = service
    return bridge


class FakeImportService:
    """按脚本驱动 progress_callback 的假导入服务。"""

    def __init__(self, script=None, result=None, error=None, gate=None):
        # script: [(args, kwargs)] 逐项调用 progress_callback
        self.script = script or []
        self.result = result if result is not None else {
            "ok": True, "stats": {"inserted_contacts": 3, "inserted_messages": 42},
        }
        self.error = error  # 非 None 时 worker 内抛该异常
        self.gate = gate  # threading.Event：阻塞在导入中（防重入测试用）
        self.captured_callbacks = []
        self.snapshot_calls = 0

    def import_wechat_data(self, db_key, options, custom_paths,
                           progress_callback=None, raw_keys=None):
        self.captured_callbacks.append(progress_callback)
        if self.gate is not None:
            self.gate.wait(timeout=10)
        if self.error is not None:
            raise self.error
        for args, kwargs in self.script:
            progress_callback(*args, **kwargs)
        return self.result

    def build_file_size_snapshot(self, custom_paths):
        self.snapshot_calls += 1
        return {}


def join_task(bridge, task_id, timeout=5.0):
    thread = bridge._wechat_import_tasks[task_id].get("thread")
    if thread is not None:
        thread.join(timeout=timeout)
    return not thread.is_alive()


def test_get_import_progress_not_found():
    bridge = make_bridge(FakeImportService())
    prog = bridge.get_import_progress("no-such-task")
    assert prog["ok"] is False
    assert prog["status"] == "not_found"


def test_import_task_lifecycle_with_details():
    service = FakeImportService(script=[
        (("查找数据库路径...", 0, 100), {"detail": {"phase": "resolving_paths"}}),
        (("导入联系人...", 10, 100), {"detail": {"phase": "contacts"}}),
        (("扫描消息表...", 30, 100), {"detail": {"phase": "scanning"}}),
        (("共 3 个对话待导入...", 30, 100),
         {"detail": {"phase": "scanning", "conversation_total": 3}}),
        (("导入对话 1/3...", 40, 100),
         {"detail": {"phase": "conversations", "conversation_idx": 1,
                     "conversation_total": 3, "inserted_messages": 10}}),
        (("导入对话 3/3...", 88, 100),
         {"detail": {"phase": "conversations", "conversation_idx": 3,
                     "conversation_total": 3, "inserted_messages": 42}}),
    ])
    bridge = make_bridge(service)

    started = bridge.import_wechat_data("k", {}, "wxid_test")
    assert started["ok"] is True and started["reused"] is False and started["task_id"]

    assert join_task(bridge, started["task_id"]), "worker 线程未在时限内结束"

    prog = bridge.get_import_progress(started["task_id"])
    assert prog["ok"] is True
    assert prog["status"] == "completed"
    assert prog["phase"] == "done"
    assert prog["percent"] == 100.0
    assert prog["conversation_total"] == 3
    assert prog["conversation_idx"] == 3
    assert prog["inserted_messages"] == 42
    assert prog["inserted_contacts"] == 3
    assert prog["elapsed_ms"] >= 0
    assert prog["result"]["ok"] is True
    assert prog["result"]["stats"]["inserted_messages"] == 42
    # 成功路径保存基线快照（搬入 worker 线程后仍应执行）
    assert service.snapshot_calls == 1


def test_progress_callback_without_detail_backward_compat():
    # 旧三参签名（不带 detail）不抛异常：phase 保持上次值、phase_label 更新
    service = FakeImportService(script=[
        (("旧式进度文案", 55, 100), {}),
    ])
    bridge = make_bridge(service)
    started = bridge.import_wechat_data("k", {}, "wxid_test")
    assert join_task(bridge, started["task_id"])
    prog = bridge.get_import_progress(started["task_id"])
    assert prog["ok"] is True
    # 终态写入会覆盖 phase=done；此用例关注兼容性——终态正常到达即未炸
    assert prog["status"] == "completed"
    assert prog["phase_label"] == "导入完成"


def test_import_reentry_reuses_running_task():
    gate = threading.Event()
    service = FakeImportService(gate=gate)
    bridge = make_bridge(service)

    first = bridge.import_wechat_data("k", {}, "wxid_test")
    assert first["ok"] is True and first["reused"] is False

    second = bridge.import_wechat_data("k", {}, "wxid_test")
    assert second["ok"] is True
    assert second["reused"] is True
    assert second["task_id"] == first["task_id"]
    assert len(bridge._wechat_import_tasks) == 1

    gate.set()
    assert join_task(bridge, first["task_id"])
    assert bridge.get_import_progress(first["task_id"])["status"] == "completed"


def test_import_failure_marks_failed():
    # worker 内抛异常 → failed 终态
    bridge = make_bridge(FakeImportService(error=RuntimeError("boom")))
    started = bridge.import_wechat_data("k", {}, "wxid_test")
    assert join_task(bridge, started["task_id"])
    prog = bridge.get_import_progress(started["task_id"])
    assert prog["status"] == "failed"
    assert "boom" in (prog["error"] or "")

    # 服务层返回 ok=False → 同样 failed
    bridge2 = make_bridge(FakeImportService(result={"ok": False, "error": "密钥错误"}))
    started2 = bridge2.import_wechat_data("k", {}, "wxid_test")
    assert join_task(bridge2, started2["task_id"])
    prog2 = bridge2.get_import_progress(started2["task_id"])
    assert prog2["status"] == "failed"
    assert prog2["error"] == "密钥错误"


def test_prune_removes_terminal_and_stale_import_tasks():
    bridge = make_bridge(FakeImportService())
    now_ms = int(time.time() * 1000)
    bridge._wechat_import_tasks.update({
        "fresh_running": {"status": "running", "updated_at": now_ms},
        "stale_running": {"status": "running", "updated_at": now_ms - 25 * 3600 * 1000},
        "old_terminal": {"status": "completed", "updated_at": now_ms - 2 * 3600 * 1000},
        "recent_terminal": {"status": "failed", "updated_at": now_ms - 60 * 1000},
    })

    bridge._prune_task_dicts()

    remaining = set(bridge._wechat_import_tasks)
    assert remaining == {"fresh_running", "recent_terminal"}
