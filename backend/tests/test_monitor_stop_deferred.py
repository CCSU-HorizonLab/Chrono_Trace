"""stop_monitoring 延迟收尾分支的会话守卫（第四轮备选）。

轮询线程 15s 未结束走延迟分支时，无条件 `is_monitoring = False` 会误杀
等待窗内已启动的新会话——同段 current_batch_id 清理已有「仅本会话」
守卫，标志位却漏了同款。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.realtime.monitor_service import RealtimeMonitorService


class _FakeAliveThread:
    def is_alive(self):
        return True

    def join(self, timeout=None):
        return


def _make_deferred_service():
    service = RealtimeMonitorService()
    service.is_monitoring = True
    service.current_batch_id = "batch-A"
    service.current_talker = "wxid_friend"
    service.current_display_name = "老朋友"
    service.current_account_wxid = "wxid_me"
    service.polling_thread = _FakeAliveThread()
    service._stop_event = None
    service._save_monitor_checkpoint = lambda *a, **k: None
    service._log_runtime_event = lambda *a, **k: None
    return service


def test_deferred_stop_keeps_new_session_monitoring_flag():
    """15s 等待窗内新会话已启动（batch 已换）：is_monitoring 不得被误杀。"""
    service = _make_deferred_service()

    calls = {"n": 0}

    def _fake_get_batch_count(batch_id, account_wxid):
        # 模拟等待窗内新会话启动：标志重新置 True、批次换新
        calls["n"] += 1
        service.is_monitoring = True
        service.current_batch_id = "batch-B"
        return 3

    service.message_buffer.get_batch_count = _fake_get_batch_count

    result = service.stop_monitoring()

    assert result["success"] is True
    assert "未被迁移" in result["message"]
    # 新会话的监听状态被保留：无新一轮 start 会误判「未在监听」
    assert service.is_monitoring is True
    assert service.current_batch_id == "batch-B"


def test_deferred_stop_without_new_session_clears_flags():
    """无新会话接手（批次未变）：延迟分支照常收尾清标志。"""
    service = _make_deferred_service()
    service.message_buffer.get_batch_count = lambda batch_id, account_wxid: 2

    result = service.stop_monitoring()

    assert result["success"] is True
    assert service.is_monitoring is False
    assert service.current_batch_id is None
    assert service.current_talker is None
    assert service.current_display_name is None
