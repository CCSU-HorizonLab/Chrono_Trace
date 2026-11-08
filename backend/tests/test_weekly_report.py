"""关系周报服务测试（docs/product-redesign-2026-11.md §6.4）。"""

import os
import sqlite3
import sys
import time
from typing import Any

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import app.services.analysis.weekly_report_service as wrs


def _make_db() -> sqlite3.Connection:
    # 后台升级线程会跨线程用库：测试连接放开同线程限制（生产 get_db 线程本地，无此问题）
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute(
        "CREATE TABLE messages (id INTEGER PRIMARY KEY, conversation_id INTEGER,"
        " is_sender INTEGER, timestamp INTEGER)"
    )
    conn.execute(
        "CREATE TABLE message_preprocessed (message_id INTEGER PRIMARY KEY,"
        " conversation_id INTEGER, char_count INTEGER, is_valid INTEGER)"
    )
    conn.execute(
        "CREATE TABLE response_times (id INTEGER PRIMARY KEY AUTOINCREMENT,"
        " conversation_id INTEGER, sent_message_id INTEGER, reply_message_id INTEGER,"
        " response_time_seconds REAL, is_abnormal INTEGER,"
        " UNIQUE(sent_message_id, reply_message_id))"
    )
    conn.execute(
        "CREATE TABLE initiative_stats (conversation_id INTEGER PRIMARY KEY,"
        " total_sessions INTEGER, user_initiated_sessions INTEGER,"
        " other_initiated_sessions INTEGER)"
    )
    conn.execute(
        "CREATE TABLE affinity_scores (id INTEGER PRIMARY KEY AUTOINCREMENT,"
        " conversation_id INTEGER, analysis_version INTEGER, overall_score REAL,"
        " sub_scores_json TEXT, created_at INTEGER)"
    )
    conn.execute(
        "CREATE TABLE weekly_reports (id INTEGER PRIMARY KEY AUTOINCREMENT,"
        " conversation_id INTEGER, week_start TEXT, verdict TEXT, source TEXT,"
        " snapshot_json TEXT, created_at INTEGER, updated_at INTEGER,"
        " UNIQUE(conversation_id, week_start))"
    )
    return conn


@pytest.fixture
def db(monkeypatch):
    conn = _make_db()
    monkeypatch.setattr("app.db.connection.get_db", lambda: conn)
    yield conn
    conn.close()


def _insert_analysis(conn, overall: float, subs: dict | None, ts: int, caliber: int = 6):
    import json

    conn.execute(
        "INSERT INTO affinity_scores(conversation_id, analysis_version, overall_score,"
        " sub_scores_json, created_at) VALUES (1, ?, ?, ?, ?)",
        (caliber, overall, json.dumps(subs or {}), ts),
    )


_NOW = int(time.time())


class TestCollectSnapshot:
    def test_no_baseline_returns_none(self, db):
        assert wrs.collect_snapshot(1) is None

    def test_snapshot_fields(self, db):
        _insert_analysis(db, 78.9, {"interaction_investment": {"score": 87.0}}, _NOW - 86400)
        _insert_analysis(db, 75.0, {"interaction_investment": {"score": 85.0}}, _NOW - 30 * 86400)
        snap = wrs.collect_snapshot(1)
        assert snap is not None
        assert set(snap) == {
            "week_start", "deltas", "initiative", "response_recent",
            "response_prev", "week_now", "week_prev",
        }
        assert snap["deltas"]["overall"] == 78.9
        assert snap["deltas"]["overall_delta"] == 3.9
        assert snap["deltas"]["dim_deltas"]["interaction_investment"] == 2.0


class TestTemplateReport:
    def test_sentences(self, db):
        _insert_analysis(db, 78.9, {}, _NOW - 86400)
        _insert_analysis(db, 75.0, {}, _NOW - 30 * 86400)
        db.execute(
            "INSERT INTO initiative_stats VALUES (1, 20, 8, 12)"
        )
        snap = wrs.collect_snapshot(1)
        text = wrs.template_report(snap)
        assert "关系温度 79" in text
        assert "上升 3.9" in text
        assert "本周" in text

    def test_empty_week(self, db):
        _insert_analysis(db, 50.0, {}, _NOW - 86400)
        snap = wrs.collect_snapshot(1)
        assert "停歇" in wrs.template_report(snap)


class TestUpsertFlow:
    def test_ensure_template_creates_and_idempotent(self, db):
        _insert_analysis(db, 66.0, {}, _NOW - 86400)
        first = wrs.ensure_template(1)
        assert first is not None and first["source"] == "template"
        assert first["verdict"]
        second = wrs.ensure_template(1)
        assert second["week_start"] == first["week_start"]
        rows = db.execute("SELECT COUNT(*) FROM weekly_reports").fetchone()[0]
        assert rows == 1  # 幂等：不重复落行

    def test_ensure_template_without_baseline(self, db):
        assert wrs.ensure_template(1) is None

    def test_llm_upsert_overwrites_same_week(self, db):
        _insert_analysis(db, 66.0, {}, _NOW - 86400)
        wrs.ensure_template(1)
        snap = wrs.collect_snapshot(1)
        wrs._upsert(1, snap["week_start"], "AI 判读正文。", "llm", snap)
        cur = wrs.get_current(1)
        assert cur["source"] == "llm" and cur["verdict"] == "AI 判读正文。"
        rows = db.execute("SELECT COUNT(*) FROM weekly_reports").fetchone()[0]
        assert rows == 1  # 同周覆盖不新增行


class TestRequestLlmUpgrade:
    def test_dispatch_and_dedupe(self, db, monkeypatch):
        import threading

        _insert_analysis(db, 66.0, {}, _NOW - 86400)
        release = threading.Event()

        def fake_llm(snapshot):
            release.wait(5)  # 卡住后台线程，保证 r2 落在 in-flight 窗口内
            return "LLM 正文。"

        monkeypatch.setattr(wrs, "llm_report", fake_llm)
        r1 = wrs.request_llm_upgrade(1)
        assert r1["started"] is True
        r2 = wrs.request_llm_upgrade(1)  # in-flight 去重
        assert r2["started"] is False and r2["reason"] == "already_running"
        release.set()
        # 等后台线程完成
        for _ in range(100):
            if db.execute("SELECT source FROM weekly_reports").fetchone():
                break
            time.sleep(0.05)
        row = db.execute("SELECT verdict, source FROM weekly_reports").fetchone()
        assert row["source"] == "llm" and row["verdict"] == "LLM 正文。"

    def test_llm_failure_keeps_template(self, db, monkeypatch):
        _insert_analysis(db, 66.0, {}, _NOW - 86400)
        wrs.ensure_template(1)
        monkeypatch.setattr(wrs, "llm_report", lambda s: None)  # 失败 → None
        assert wrs.request_llm_upgrade(1)["started"] is True
        for _ in range(100):
            time.sleep(0.05)
            row = db.execute("SELECT source FROM weekly_reports").fetchone()
            if row and row["source"] == "template":
                break
        assert wrs.get_current(1)["source"] == "template"  # 模板版保留


class TestLlmConfigured:
    def test_no_config_false(self, db, monkeypatch):
        monkeypatch.setattr(
            "app.services.realtime.rag.fact_llm.get_active_model_config", lambda: None
        )
        assert wrs.llm_configured() is False


# ----------------------------------------------------------------------
# LLM 生成：思考模型定档 / extra_body 优先 / <think> 剥离
# ----------------------------------------------------------------------

class TestLlmReport:
    def _run(self, monkeypatch, model_cfg, content):
        captured = {}

        def _fake_post(**kwargs):
            captured.update(kwargs.get("payload") or {})
            return {"choices": [{"message": {"role": "assistant", "content": content}}]}

        monkeypatch.setattr(
            "app.services.realtime.rag.fact_llm.get_active_model_config",
            lambda: model_cfg,
        )
        monkeypatch.setattr(
            "app.services.realtime.llm_http.post_json_with_retries", _fake_post
        )
        out = wrs.llm_report({"deltas": {}, "week_now": {"messages": 3}})
        return out, captured

    def test_thinking_model_gets_medium_effort_and_budget(self, monkeypatch):
        _, payload = self._run(
            monkeypatch,
            {"model_id": "Qwen3.5-9B", "api_base_url": "http://x/v1", "api_key": "k"},
            "本周关系平稳。",
        )
        assert payload["reasoning_effort"] == "medium"
        assert payload["max_tokens"] == 800  # 500 会被思维链吃尽

    def test_extra_body_merged_with_priority(self, monkeypatch):
        _, payload = self._run(
            monkeypatch,
            {
                "model_id": "Qwen3.5-9B",
                "api_base_url": "http://x/v1",
                "api_key": "",
                "extra_body": '{"enable_thinking": false, "reasoning_effort": "high"}',
            },
            "ok",
        )
        assert payload["enable_thinking"] is False
        assert payload["reasoning_effort"] == "high"  # 用户显式档不被覆盖

    def test_think_inline_tags_stripped(self, monkeypatch):
        out, _ = self._run(
            monkeypatch,
            {"model_id": "gpt-x", "api_base_url": "http://x/v1", "api_key": ""},
            "<think>先分析数字再下结论</think>本周温度 35，较上周回落。",
        )
        assert out == "本周温度 35，较上周回落。"
        assert "think" not in out
