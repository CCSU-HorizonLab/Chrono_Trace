"""post_json_stream 原语测试：SSE 解析 / abort 中断 / 部分返回 / 回退信号 /
代理口径 / 200 假流式兜底。"""

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import app.services.realtime.llm_http as llmhttp


class _FakeResp:
    """http.client 响应替身：status + 按行迭代 + 可读 body。"""

    def __init__(self, lines, status=200, body=b""):
        self._lines = [f"{l}\n".encode("utf-8") for l in lines]
        self.status = status
        self._body = body

    def __iter__(self):
        return iter(self._lines)

    def read(self):
        return self._body


class _BrokenResp:
    """发一个 delta 后断流（网络中断在增量途中）。"""

    status = 200

    def __init__(self, part):
        self._part = part

    def __iter__(self):
        yield f"data: {json.dumps({'choices': [{'delta': {'content': self._part}}]})}\n".encode("utf-8")
        raise ConnectionResetError("peer gone")

    def read(self):
        return b""


class _DeadResp:
    """连接即断（零 delta 失败：应原样上抛交调用方回退非流式）。"""

    status = 200

    def __iter__(self):
        raise ConnectionResetError("dead")
        yield b""  # pragma: no cover

    def read(self):
        return b""


class _FakeConn:
    def close(self):
        pass


def _chunk(delta_content="", reasoning=""):
    payload = {}
    if delta_content:
        payload["content"] = delta_content
    if reasoning:
        payload["reasoning_content"] = reasoning
    return f"data: {json.dumps({'choices': [{'delta': payload}]})}"


def _stream(monkeypatch, resp, deltas, should_abort=None):
    monkeypatch.setattr(
        llmhttp, "_open_stream_connection",
        lambda url, data, headers, timeout: (_FakeConn(), resp),
    )
    return llmhttp.post_json_stream(
        url="http://x/v1/chat/completions",
        payload={"model": "m", "stream": True},
        timeout=5,
        log=lambda *_: None,
        log_prefix="[t]",
        on_delta=deltas.append,
        should_abort=should_abort,
    )


def test_sse_content_deltas_parsed_and_done_terminates(monkeypatch):
    deltas: list[str] = []
    content, truncated = _stream(
        monkeypatch,
        _FakeResp([_chunk(reasoning="思考"), _chunk("你好"), _chunk("世界"), "data: [DONE]", _chunk("不应到达")]),
        deltas,
    )
    assert content == "你好世界"
    assert truncated is False
    assert deltas == ["你好", "世界"]  # reasoning 增量不回调（思维链不给用户）


def test_abort_midway_returns_partial_truncated(monkeypatch):
    deltas: list[str] = []
    state = {"armed": False}

    def _should_abort():
        return state["armed"]

    real_append = deltas.append

    def _track(text):
        real_append(text)
        if len(deltas) >= 2:
            state["armed"] = True

    monkeypatch.setattr(
        llmhttp, "_open_stream_connection",
        lambda url, data, headers, timeout: (_FakeConn(), _FakeResp([_chunk("一"), _chunk("二"), _chunk("三")])),
    )
    content, truncated = llmhttp.post_json_stream(
        url="http://x", payload={}, timeout=5,
        log=lambda *_: None, log_prefix="[t]",
        on_delta=_track, should_abort=_should_abort,
    )
    assert content == "一二"
    assert truncated is True
    assert deltas == ["一", "二"]


def test_network_error_after_deltas_returns_partial_truncated(monkeypatch):
    deltas: list[str] = []
    content, truncated = _stream(monkeypatch, _BrokenResp("部分"), deltas)
    assert content == "部分"
    assert truncated is True
    assert deltas == ["部分"]


def test_zero_delta_network_error_propagates(monkeypatch):
    deltas: list[str] = []
    with pytest.raises(Exception):
        _stream(monkeypatch, _DeadResp(), deltas)
    assert deltas == []


def test_stream_unsupported_raised_for_plain_4xx(monkeypatch):
    monkeypatch.setattr(
        llmhttp, "_open_stream_connection",
        lambda url, data, headers, timeout: (_FakeConn(), _FakeResp([], status=400, body=b"stream unsupported")),
    )
    with pytest.raises(llmhttp.LLMStreamUnsupported):
        llmhttp.post_json_stream(
            url="http://x", payload={}, timeout=5,
            log=lambda *_: None, log_prefix="[t]", on_delta=lambda t: None,
        )


def test_reasoning_effort_400_is_not_stream_unsupported(monkeypatch):
    """严格网关拒思考量参数的 400 不误诊为流式不支持——走普通失败由
    调用方整段回退（那边有摘参重试）。"""
    monkeypatch.setattr(
        llmhttp, "_open_stream_connection",
        lambda url, data, headers, timeout: (
            _FakeConn(), _FakeResp([], status=400, body=b"reasoning_effort not supported"),
        ),
    )
    with pytest.raises(RuntimeError) as exc_info:
        llmhttp.post_json_stream(
            url="http://x", payload={}, timeout=5,
            log=lambda *_: None, log_prefix="[t]", on_delta=lambda t: None,
        )
    assert not isinstance(exc_info.value, llmhttp.LLMStreamUnsupported)


def test_http_5xx_raises_plain_error(monkeypatch):
    monkeypatch.setattr(
        llmhttp, "_open_stream_connection",
        lambda url, data, headers, timeout: (_FakeConn(), _FakeResp([], status=502, body=b"bad gw")),
    )
    with pytest.raises(RuntimeError):
        llmhttp.post_json_stream(
            url="http://x", payload={}, timeout=5,
            log=lambda *_: None, log_prefix="[t]", on_delta=lambda t: None,
        )


def test_fake_stream_json_body_fully_parsed(monkeypatch):
    """200 却回普通 JSON（网关忽略 stream 参数）：整体解析兜底，答案不丢。"""
    body = json.dumps({"choices": [{"message": {"content": "完整答案"}}]})
    deltas: list[str] = []
    content, truncated = _stream(monkeypatch, _FakeResp([body]), deltas)
    assert content == "完整答案"
    assert truncated is False
    assert deltas == []


def test_on_delta_failure_not_disguised_as_truncation(monkeypatch):
    """推送回调链抛错不冒充网络截断：流读取继续，全文返回。"""
    deltas: list[str] = []

    def _bad_callback(text):
        deltas.append(text)
        raise RuntimeError("push broken")

    monkeypatch.setattr(
        llmhttp, "_open_stream_connection",
        lambda url, data, headers, timeout: (_FakeConn(), _FakeResp([_chunk("一"), _chunk("二")])),
    )
    content, truncated = llmhttp.post_json_stream(
        url="http://x", payload={}, timeout=5,
        log=lambda *_: None, log_prefix="[t]", on_delta=_bad_callback,
    )
    assert content == "一二"
    assert truncated is False


def test_stream_uses_bare_http_client_not_urllib(monkeypatch):
    """网络路径与非流式一致：裸 http.client 直连（不走 urllib opener 的
    系统代理），不碰 urllib.request.urlopen。"""
    def _unexpected_urlopen(*a, **kw):
        raise AssertionError("流式不得走 urllib.request.urlopen（代理分叉）")

    monkeypatch.setattr(llmhttp.urllib.request, "urlopen", _unexpected_urlopen)
    monkeypatch.setattr(
        llmhttp, "_open_stream_connection",
        lambda url, data, headers, timeout: (_FakeConn(), _FakeResp([_chunk("好")], )),
    )
    content, _ = llmhttp.post_json_stream(
        url="http://x", payload={}, timeout=5,
        log=lambda *_: None, log_prefix="[t]", on_delta=lambda t: None,
    )
    assert content == "好"
