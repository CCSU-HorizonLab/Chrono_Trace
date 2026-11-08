"""画像生成取消测试：桥接层立即返回已取消 + should_abort 贯穿 HTTP 层。"""

import os
import sqlite3
import sys
import threading
import time

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def test_bridge_cancel_returns_immediately():
    """生成中取消：run_cancelable 轮询命中即返回「已取消」，不等工作线程跑完。"""
    from app.webview.api.profile import PROFILE_CANCEL_SCOPE, ProfileApiMixin
    import app.services.realtime.llm_http as llmhttp

    def slow_generate(should_abort):
        deadline = time.time() + 5
        while time.time() < deadline and not (should_abort and should_abort()):
            time.sleep(0.02)
        return {"ok": True, "profile": {}}

    # 模拟弹窗关闭：0.1s 后请求取消
    timer = threading.Timer(0.1, lambda: llmhttp.request_llm_cancel(PROFILE_CANCEL_SCOPE, 42))
    timer.start()
    t0 = time.time()
    res = ProfileApiMixin()._run_profile_cancelable(slow_generate, 42, log_prefix="[test]")
    timer.join()

    assert res["cancelled"] is True
    assert time.time() - t0 < 2  # 立即返回，不陪跑 5s
    assert llmhttp.take_llm_cancel(PROFILE_CANCEL_SCOPE, 42) is False  # 标记已被消费


def test_bridge_without_cancel_key_runs_to_completion():
    """未传取消键（旧调用方）：不受取消机制影响，正常等结果。"""
    from app.webview.api.profile import ProfileApiMixin

    res = ProfileApiMixin()._run_profile_cancelable(
        lambda abort: {"ok": True}, 0, log_prefix="[test]"
    )
    assert res == {"ok": True}


def test_profiler_passes_should_abort_into_http(monkeypatch):
    """should_abort 传入 HTTP 层：取消时在尝试边界抛 LLMRequestAborted。"""
    import app.db.connection as dbmod
    import app.services.realtime.contact_profiler as cp
    from app.services.realtime.llm_http import LLMRequestAborted

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        "CREATE TABLE llm_models (id INTEGER PRIMARY KEY, name TEXT, provider TEXT,"
        " model_id TEXT, api_base_url TEXT, api_key TEXT, is_active INT,"
        " max_tokens INT, temperature REAL, created_at INT, updated_at INT)"
    )
    conn.execute(
        "INSERT INTO llm_models VALUES (1, 't', 'custom', 'qwen3.5-9b',"
        " 'http://127.0.0.1:11434/v1', '', 1, 512, 0.5, 0, 0)"
    )
    monkeypatch.setattr(dbmod, "get_db", lambda: conn)

    captured = {}

    def fake_post(**kw):
        captured.update(kw)
        if kw.get("should_abort") and kw["should_abort"]():
            raise LLMRequestAborted("cancelled in test")
        return {"choices": [{"message": {"content": "{}"}}]}

    monkeypatch.setattr(cp, "post_json_with_retries", fake_post)

    with pytest.raises(LLMRequestAborted):
        cp.ContactProfiler()._call_llm("测试 prompt", should_abort=lambda: True)

    assert captured["should_abort"]() is True
    conn.close()


def test_bridge_serializes_generation_per_key():
    """同 key 串行门闩：A 在途时 B 不得起步，A 退出后 B 才进入。

    无门闩并发下（12d2f71 回归形态），后轮入口的清残留会与前轮在途
    的停止意图竞速——单槽标记无属主，这是概率性互杀，链路级无法确定
    性复现；串行性是它的确定性替身：B 排队等 A 真正退出，入口清残留
    就永远只碰死标记（语义直测见 test_group_summary 的 gate 用例）。
    """
    from app.webview.api.profile import ProfileApiMixin

    a_inside = threading.Event()
    b_inside = threading.Event()
    release_a = threading.Event()
    out = {}

    def gen_a(_abort):
        a_inside.set()
        release_a.wait(5)  # A 在途（持门闩）
        return {"ok": True, "which": "A"}

    def gen_b(_abort):
        b_inside.set()
        return {"ok": True, "which": "B"}

    def run(gen, tag):
        out[tag] = ProfileApiMixin()._run_profile_cancelable(gen, 42, log_prefix=f"[{tag}]")

    ta = threading.Thread(target=run, args=(gen_a, "a"))
    ta.start()
    assert a_inside.wait(2), "A 未起步"
    tb = threading.Thread(target=run, args=(gen_b, "b"))
    tb.start()
    assert not b_inside.wait(0.3), "A 在途时 B 不得起步（同 key 串行门闩）"
    release_a.set()
    assert b_inside.wait(2), "A 退出后 B 应起步"
    ta.join(5)
    tb.join(5)

    assert out["a"] == {"ok": True, "which": "A"}
    assert out["b"] == {"ok": True, "which": "B"}
