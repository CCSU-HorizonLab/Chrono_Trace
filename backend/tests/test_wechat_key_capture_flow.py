from __future__ import annotations

from app.services.wechat.keys import flow_win as key_capture_flow


def test_inspect_reports_not_running(monkeypatch):
    monkeypatch.setattr(key_capture_flow, "_list_wechat_processes", lambda: [])

    result = key_capture_flow.inspect_wechat_login_state()

    assert result["ok"] is True
    assert result["running"] is False
    assert result["login_state"] == "not_running"


def test_inspect_identifies_logged_in_window(monkeypatch):
    monkeypatch.setattr(
        key_capture_flow,
        "_list_wechat_processes",
        lambda: [{"pid": 101, "name": "Weixin.exe", "exe_path": "C:/Weixin.exe"}],
    )
    monkeypatch.setattr(key_capture_flow, "_window_texts", lambda _pids: ["微信", "聊天", "通讯录"])

    result = key_capture_flow.inspect_wechat_login_state()

    assert result["running"] is True
    assert result["login_state"] == "logged_in"


def test_inspect_identifies_login_window(monkeypatch):
    monkeypatch.setattr(
        key_capture_flow,
        "_list_wechat_processes",
        lambda: [{"pid": 202, "name": "Weixin.exe", "exe_path": "C:/Weixin.exe"}],
    )
    monkeypatch.setattr(key_capture_flow, "_window_texts", lambda _pids: ["微信", "扫码登录"])

    result = key_capture_flow.inspect_wechat_login_state()

    assert result["running"] is True
    assert result["login_state"] == "login_required"


def test_inspect_unknown_state_does_not_assume_logged_in(monkeypatch):
    monkeypatch.setattr(
        key_capture_flow,
        "_list_wechat_processes",
        lambda: [{"pid": 303, "name": "Weixin.exe", "exe_path": "C:/Weixin.exe"}],
    )
    monkeypatch.setattr(key_capture_flow, "_window_texts", lambda _pids: ["微信"])

    result = key_capture_flow.inspect_wechat_login_state()

    assert result["running"] is True
    assert result["login_state"] == "unknown"
