from __future__ import annotations

import time

from backend.app.services.wechat import key_provider as key_provider_module
from backend.app.services.wechat.key_provider import WeChatKeyProvider


class FakeExtension:
    def __init__(self, *, initialize_result=True, initialize_failures=0, payloads=None):
        self.initialize_result = initialize_result
        self.initialize_failures = int(initialize_failures)
        self.payloads = list(payloads or [])
        self.initialized_pids = []
        self.initialize_attempts = 0
        self.cleanup_calls = 0

    def initialize_hook(self, pid):
        self.initialize_attempts += 1
        if self.initialize_attempts <= self.initialize_failures:
            return False
        self.initialized_pids.append(pid)
        return self.initialize_result

    def poll_key_data(self):
        if self.payloads:
            return self.payloads.pop(0)
        return None

    def cleanup_hook(self):
        self.cleanup_calls += 1
        return True

    def get_last_error_msg(self):
        return "fake hook error"


def test_capture_db_key_returns_missing_extension(monkeypatch):
    provider = WeChatKeyProvider()
    monkeypatch.setattr(provider, "_load_extension", staticmethod(lambda: None))

    result = provider.capture_db_key(account_wxid="wxid_test")

    assert result["ok"] is False
    assert result["code"] == "extension_missing"
    assert result["account_wxid"] == "wxid_test"


def test_capture_db_key_reports_hook_initialization_failure(monkeypatch):
    extension = FakeExtension(initialize_result=False)
    provider = WeChatKeyProvider()
    monkeypatch.setattr(provider, "_load_extension", staticmethod(lambda: extension))
    monkeypatch.setattr(provider, "_find_wechat_pid", staticmethod(lambda: (1234, "")))

    result = provider.capture_db_key()

    assert result["ok"] is False
    assert result["code"] == "hook_initialize_failed"
    assert result["pid"] == 1234
    assert extension.initialized_pids == [1234]
    assert extension.cleanup_calls == 0


def test_capture_db_key_validates_and_cleans_up_successfully(monkeypatch):
    extension = FakeExtension(
        payloads=[
            {"key": "too-short"},
            {"key": "A" * 64},
        ]
    )
    provider = WeChatKeyProvider()
    monkeypatch.setattr(provider, "_load_extension", staticmethod(lambda: extension))
    monkeypatch.setattr(provider, "_find_wechat_pid", staticmethod(lambda: (5678, "")))

    result = provider.capture_db_key(timeout_seconds=2, account_wxid="wxid_test")

    assert result == {
        "ok": True,
        "db_key": "a" * 64,
        "pid": 5678,
        "account_wxid": "wxid_test",
    }
    assert extension.initialized_pids == [5678]
    assert extension.cleanup_calls == 1


def test_capture_db_key_cleans_up_after_timeout(monkeypatch):
    extension = FakeExtension(payloads=[{"key": "bad"}])
    provider = WeChatKeyProvider()
    monkeypatch.setattr(provider, "_load_extension", staticmethod(lambda: extension))
    monkeypatch.setattr(provider, "_find_wechat_pid", staticmethod(lambda: (9999, "")))

    result = provider.capture_db_key(timeout_seconds=1)

    assert result["ok"] is False
    assert result["code"] == "capture_timeout"
    assert extension.cleanup_calls == 1


def test_capture_session_reports_hook_ready_before_login_result(monkeypatch):
    extension = FakeExtension(payloads=[None, {"key": "B" * 64}])
    provider = WeChatKeyProvider()
    monkeypatch.setattr(WeChatKeyProvider, "_load_extension", staticmethod(lambda: extension))
    monkeypatch.setattr(WeChatKeyProvider, "_find_wechat_pid", staticmethod(lambda: (2468, "")))

    session = provider.create_capture_session(timeout_seconds=2, account_wxid="wxid_session")
    initial = session.start()

    assert initial["status"] in {"hook_ready", "captured"}
    assert initial["account_wxid"] == "wxid_session"
    for _ in range(100):
        snapshot = session.snapshot()
        if snapshot["status"] == "captured":
            break
        time.sleep(0.05)
    assert snapshot["status"] == "captured"
    assert snapshot["db_key"] == "b" * 64
    assert extension.cleanup_calls == 1


def test_capture_session_waits_for_wechat_process_to_appear(monkeypatch):
    """重启流程刚拉起微信时进程可能还没出现，会话应持续等待而不是立刻失败。"""
    extension = FakeExtension(payloads=[{"key": "C" * 64}])
    provider = WeChatKeyProvider()
    monkeypatch.setattr(WeChatKeyProvider, "_load_extension", staticmethod(lambda: extension))

    pid_probes = {"count": 0}

    def delayed_pid():
        pid_probes["count"] += 1
        if pid_probes["count"] >= 3:
            return 1357, ""
        return None, "未检测到正在运行的微信进程"

    monkeypatch.setattr(WeChatKeyProvider, "_find_wechat_pid", staticmethod(delayed_pid))

    session = provider.create_capture_session(
        timeout_seconds=2,
        account_wxid="wxid_restart",
        wechat_start_wait_seconds=5,
        hook_install_retry_seconds=0,
    )
    initial = session.start()

    assert initial["status"] in {"hook_ready", "captured"}
    assert pid_probes["count"] == 3
    assert extension.initialized_pids == [1357]


def test_capture_session_retries_hook_install_while_wechat_starting(monkeypatch):
    """进程已出现但模块未加载完（版本读不到）时，应在宽限窗口内重试安装。"""
    extension = FakeExtension(initialize_failures=2, payloads=[{"key": "D" * 64}])
    provider = WeChatKeyProvider()
    monkeypatch.setattr(WeChatKeyProvider, "_load_extension", staticmethod(lambda: extension))
    monkeypatch.setattr(WeChatKeyProvider, "_find_wechat_pid", staticmethod(lambda: (2468, "")))

    session = provider.create_capture_session(
        timeout_seconds=2,
        account_wxid="wxid_restart",
        wechat_start_wait_seconds=0,
        hook_install_retry_seconds=5,
    )
    initial = session.start()

    assert initial["status"] in {"hook_ready", "captured"}
    assert extension.initialize_attempts == 3
    assert extension.initialized_pids == [2468]


def test_capture_session_fails_when_wechat_never_starts(monkeypatch):
    extension = FakeExtension()
    provider = WeChatKeyProvider()
    monkeypatch.setattr(WeChatKeyProvider, "_load_extension", staticmethod(lambda: extension))
    monkeypatch.setattr(
        WeChatKeyProvider,
        "_find_wechat_pid",
        staticmethod(lambda: (None, "未检测到正在运行的微信进程")),
    )

    session = provider.create_capture_session(
        timeout_seconds=1,
        wechat_start_wait_seconds=0,
        hook_install_retry_seconds=0,
    )
    initial = session.start()

    assert initial["status"] == "failed"
    assert initial["code"] == "wechat_not_running"
    assert extension.initialized_pids == []


def test_capture_session_reports_init_failure_after_retry_window(monkeypatch):
    extension = FakeExtension(initialize_result=False)
    provider = WeChatKeyProvider()
    monkeypatch.setattr(WeChatKeyProvider, "_load_extension", staticmethod(lambda: extension))
    monkeypatch.setattr(WeChatKeyProvider, "_find_wechat_pid", staticmethod(lambda: (2468, "")))

    session = provider.create_capture_session(
        timeout_seconds=1,
        wechat_start_wait_seconds=0,
        hook_install_retry_seconds=0,
    )
    initial = session.start()

    assert initial["status"] == "failed"
    assert initial["code"] == "hook_initialize_failed"
    assert extension.initialize_attempts == 1
    assert extension.cleanup_calls == 0
