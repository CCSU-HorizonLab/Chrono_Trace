from __future__ import annotations

from backend.app.services.wechat import key_provider as key_provider_module
from backend.app.services.wechat.key_provider import WeChatKeyProvider


class FakeExtension:
    def __init__(self, *, initialize_result=True, payloads=None):
        self.initialize_result = initialize_result
        self.payloads = list(payloads or [])
        self.initialized_pids = []
        self.cleanup_calls = 0

    def initialize_hook(self, pid):
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

