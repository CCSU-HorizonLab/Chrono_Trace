"""章节摘要金字塔测试：月摘要增量、脱敏红线、章节归并指纹、注入器口径。

桩注入：llm_call/chapters_provider/redactor_factory 全部构造注入，
不触网络；get_db 指向内存库。
"""
import json
import sqlite3
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from app.services.analysis import chapter_summaries as csmod
from app.services.analysis.chapter_summaries import (
    MONTH_MAX_MESSAGES,
    SUMMARY_VERSION,
    ChapterSummaryService,
    _summary_fp,
)
from app.services.realtime import profile_chapter_digest as digest_mod

BASE = 1700000000  # 固定秒级锚点（2023-11 中旬）
DAY = 86400


# ---------------------------------------------------------------------------
# 桩
# ---------------------------------------------------------------------------

class StubLLM:
    """按 user prompt 内容区分月/章任务；记录全部调用。"""

    def __init__(self, month_reply=None, chapter_reply=None):
        self.calls = []  # (system, user)
        self.month_reply = month_reply or (
            '{"topics": ["工作", "周末爬山"], "dynamics": "互动平稳，话题以日常为主",'
            ' "highlights": ["约了爬山"], "style": "语气轻松"}'
        )
        self.chapter_reply = chapter_reply or (
            '{"summary": "这段以日常分享为主，双方互动轻松，话题围绕工作与周末安排。",'
            ' "phase": "熟络升温期"}'
        )
        self.on_call = None  # 每次调用后的钩子（测试驱动取消）

    def __call__(self, system, user):
        self.calls.append((system, user))
        if self.on_call:
            self.on_call()
        if user.startswith("【月份】"):
            return self.month_reply
        if user.startswith("【章节】"):
            return self.chapter_reply
        raise AssertionError(f"unexpected user prompt: {user[:60]}")


class StubRedactor:
    """规则桩：替换手机号；可选对含关键词的文本抛异常。"""

    def __init__(self, fail_keyword=None):
        self.fail_keyword = fail_keyword
        self.seen = []

    def redact(self, text, **kwargs):
        self.seen.append(text)
        if self.fail_keyword and self.fail_keyword in text:
            raise RuntimeError("stub redaction failure")
        return SimpleNamespace(redacted_text=text.replace("13800138000", "[手机号]"))


def _stub_chapters_payload():
    """两章对齐播种月：章 1 覆盖 2023-11、章 2 覆盖 2023-12 起。"""
    def _stats(texts, weeks):
        return {
            "texts": texts, "me_texts": texts // 2, "other_texts": texts - texts // 2,
            "other_share": 0.5, "pos_ratio": 0.6, "latency_hours": 2.0, "weeks": weeks,
        }

    ch1_from, ch1_to = _month_anchor(2023, 11), _month_anchor(2023, 12)
    return {
        "ok": True,
        "version": 1,
        "chapters": [
            {"index": 0, "week_index": 0, "from_ts": ch1_from, "to_ts": ch1_to,
             "stats": _stats(60, 9), "changes": []},
            {"index": 1, "week_index": 9, "from_ts": ch1_to, "to_ts": _month_anchor(2024, 1),
             "stats": _stats(90, 9),
             "changes": [{"key": "volume", "label": "消息密度", "direction": "up", "delta": 1.2}]},
        ],
    }


# ---------------------------------------------------------------------------
# 夹具
# ---------------------------------------------------------------------------

@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row  # 对齐生产连接（db/connection.py）
    c.executescript(
        """
        CREATE TABLE conversations(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            account_wxid TEXT NOT NULL, username TEXT NOT NULL,
            display_name TEXT NOT NULL);
        CREATE TABLE messages(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            conversation_id INTEGER NOT NULL, is_sender INTEGER NOT NULL,
            message_type INTEGER NOT NULL, content TEXT,
            timestamp INTEGER NOT NULL, created_at INTEGER NOT NULL);
        """
    )
    yield c
    c.close()


def _month_anchor(year, month):
    """单月播种锚点：每月 5 号起铺 20 天（不跨自然月，本地时区）。"""
    from datetime import datetime

    return int(datetime(year, month, 5, 12, 0, 0).timestamp())


def _seed_month(conn, year, month, per_day=6, days=20):
    anchor = _month_anchor(year, month)
    for d in range(days):
        for k in range(per_day):
            ts = anchor + d * DAY + 3600 + k * 600
            conn.execute(
                "INSERT INTO messages(conversation_id, is_sender, message_type,"
                " content, timestamp, created_at) VALUES (1, ?, 1, ?, ?, ?)",
                (k % 2, f"消息{d}-{k} 手机号13800138000", ts, ts),
            )
    conn.commit()


def _make_service(conn, monkeypatch, llm=None, redactor_factory=None, chapters_payload=None):
    service = ChapterSummaryService(
        llm_call=llm or StubLLM(),
        redactor_factory=redactor_factory,
        chapters_provider=(lambda cid: chapters_payload or _stub_chapters_payload()),
    )
    monkeypatch.setattr(csmod, "get_db", lambda: conn)
    return service


_run_seq = [0]


def _run_sync(service, conversation_id=1):
    """不起线程直接跑（register → run），返回 task_id。"""
    _run_seq[0] += 1
    task_id = f"t_sync_{_run_seq[0]}"
    service.register_task(task_id, conversation_id)
    event = service._cancel_events[task_id]
    service.run(conversation_id, event, task_id)
    return task_id


# ---------------------------------------------------------------------------
# 月摘要
# ---------------------------------------------------------------------------

class TestMonthSummaries:

    def test_months_listed_and_summarized(self, conn, monkeypatch):
        llm = StubLLM()
        _seed_month(conn, 2023, 11)
        _seed_month(conn, 2023, 12)
        service = _make_service(conn, monkeypatch, llm=llm)

        task_id = _run_sync(service)
        # 2 月 + 2 章归并 = 4 次 LLM 调用
        assert len(llm.calls) == 4
        assert service.get_progress(task_id)["status"] == "completed"
        rows = conn.execute(
            "SELECT month_key FROM chapter_month_summaries WHERE version = ?",
            (SUMMARY_VERSION,),
        ).fetchall()
        assert len(rows) == 2
        progress = service.get_progress(task_id)
        assert progress["months_total"] == 2 and progress["months_done"] == 2

    def test_incremental_skips_ready_months(self, conn, monkeypatch):
        llm = StubLLM()
        _seed_month(conn, 2023, 11)
        service = _make_service(conn, monkeypatch, llm=llm)
        _run_sync(service)
        assert len(llm.calls) == 2  # 1 月 + 1 章

        _seed_month(conn, 2023, 12)  # 新月份
        _run_sync(service)
        # 新月摘要 1 次 + 章 2 首次可归并（上月无数据被跳过，本月就绪）1 次；
        # 核心：已就绪的 11 月不重算，已归并的章 1 指纹命中跳过
        month_calls = [u for _, u in llm.calls if u.startswith("【月份】")]
        assert len(month_calls) == 2
        assert len(llm.calls) == 4
        months = conn.execute(
            "SELECT COUNT(*) FROM chapter_month_summaries WHERE version = ?",
            (SUMMARY_VERSION,),
        ).fetchone()[0]
        assert months == 2

    def test_month_input_redacted_for_remote(self, conn, monkeypatch):
        llm = StubLLM()
        redactor = StubRedactor()
        _seed_month(conn, 2023, 11)
        service = _make_service(
            conn, monkeypatch, llm=llm,
            redactor_factory=lambda: redactor,
        )
        service._is_remote = True  # 强制远程语义（构造注入旁路模型探测）
        _run_sync(service)

        assert redactor.seen, "远程模型必须逐条过脱敏器"
        user_prompt = llm.calls[0][1]
        assert "13800138000" not in user_prompt
        assert "[手机号]" in user_prompt

    def test_redact_failure_drops_message_not_month(self, conn, monkeypatch):
        """单条脱敏异常：丢条继续（月报照常，prompt 记丢弃数）。"""
        llm = StubLLM()
        _seed_month(conn, 2023, 11)
        service = _make_service(
            conn, monkeypatch, llm=llm,
            redactor_factory=lambda: StubRedactor(fail_keyword="消息3-"),
        )
        service._is_remote = True
        _run_sync(service)
        assert "脱敏失败已丢弃" in llm.calls[0][1]
        assert conn.execute(
            "SELECT COUNT(*) FROM chapter_month_summaries"
        ).fetchone()[0] == 1

    def test_redactor_construction_failure_blocks(self, conn, monkeypatch):
        """远程模型脱敏器构造失败：整任务阻断，不发明文。"""
        llm = StubLLM()

        def _broken_factory():
            raise RuntimeError("redactor boom")

        service = _make_service(conn, monkeypatch, llm=llm, redactor_factory=_broken_factory)
        service._is_remote = True
        result = service.start_task(1)
        assert result["ok"] is False
        assert "阻断" in result["error"]
        assert not llm.calls

    def test_month_sampling_thins_by_count(self, conn, monkeypatch):
        """单月条数超上限：等距抽稀到 MONTH_MAX_MESSAGES 内。"""
        llm = StubLLM()
        anchor = _month_anchor(2023, 11)
        for k in range(4000):  # 全落 2023-11（4000 分钟 ≈ 2.8 天）
            ts = anchor + k * 60
            conn.execute(
                "INSERT INTO messages(conversation_id, is_sender, message_type,"
                " content, timestamp, created_at) VALUES (1, 0, 1, '短消息', ?, ?)",
                (ts, ts),
            )
        conn.commit()
        service = _make_service(conn, monkeypatch, llm=llm)
        _run_sync(service)
        user_prompt = llm.calls[0][1]
        sample_lines = [ln for ln in user_prompt.splitlines() if ln.startswith(("我：", "TA："))]
        assert len(sample_lines) <= MONTH_MAX_MESSAGES

    def test_invalid_llm_response_fails_task(self, conn, monkeypatch):
        llm = StubLLM(month_reply="这不是JSON")
        _seed_month(conn, 2023, 11)
        service = _make_service(conn, monkeypatch, llm=llm)
        task_id = "parse_fail"
        service.register_task(task_id, 1)
        with pytest.raises(ValueError):
            service.run(1, threading.Event(), task_id)
        # start_task 线程路径同语义：异常被 wrapper 捕获置 failed


# ---------------------------------------------------------------------------
# 章节归并
# ---------------------------------------------------------------------------

class TestChapterMerge:

    def test_chapter_summaries_written_with_phase(self, conn, monkeypatch):
        llm = StubLLM()
        _seed_month(conn, 2023, 11)
        _seed_month(conn, 2023, 12)
        service = _make_service(conn, monkeypatch, llm=llm)
        _run_sync(service)

        rows = conn.execute(
            "SELECT fingerprint, summary_json FROM chapter_summaries"
            " WHERE version = ? ORDER BY from_ts",
            (SUMMARY_VERSION,),
        ).fetchall()
        assert len(rows) == 2
        parsed = json.loads(rows[0]["summary_json"])
        assert parsed["summary"] and parsed["phase"]
        assert rows[0]["fingerprint"] == _summary_fp(_month_anchor(2023, 11), _month_anchor(2023, 12))

    def test_boundary_shift_invalidates_chapter_cache(self, conn, monkeypatch):
        """章节边界变化 → 指纹变化 → 章摘要重算（月摘要不重算）。"""
        llm = StubLLM()
        _seed_month(conn, 2023, 11)
        service = _make_service(conn, monkeypatch, llm=llm)
        _run_sync(service)
        first_calls = len(llm.calls)

        payload = _stub_chapters_payload()
        payload["chapters"][0]["to_ts"] = _month_anchor(2023, 12) - 5 * DAY  # 边界漂移
        payload["chapters"][1]["from_ts"] = _month_anchor(2023, 12) - 5 * DAY
        service._chapters_provider = lambda cid: payload
        _run_sync(service)

        # 月摘要 0 次重算；章 1 指纹变了重算 1 次，章 2 未变跳过
        assert len(llm.calls) == first_calls + 1
        fingerprints = {
            row[0] for row in conn.execute(
                "SELECT fingerprint FROM chapter_summaries"
            ).fetchall()
        }
        assert _summary_fp(
            _month_anchor(2023, 11), _month_anchor(2023, 12) - 5 * DAY,
        ) in fingerprints


# ---------------------------------------------------------------------------
# 任务三件套
# ---------------------------------------------------------------------------

class TestTaskPlumbing:

    def test_cancel_keeps_finished_months(self, conn, monkeypatch):
        llm = StubLLM()
        _seed_month(conn, 2023, 11)
        _seed_month(conn, 2023, 12)
        service = _make_service(conn, monkeypatch, llm=llm)

        task_id = "cancel_test"
        service.register_task(task_id, 1)
        event = service._cancel_events[task_id]
        call_count = [0]

        def _cancel_after_first():
            # 第 1 次 LLM 调用（11 月摘要）完成后置取消：12 月循环检查点生效
            call_count[0] += 1
            if call_count[0] >= 1:
                event.set()

        llm.on_call = _cancel_after_first
        service.run(1, event, task_id)
        assert service.get_progress(task_id)["status"] == "cancelled"
        # 第 1 个月已落库（取消保留已完成月）
        assert conn.execute(
            "SELECT COUNT(*) FROM chapter_month_summaries"
        ).fetchone()[0] == 1

    def test_find_running_and_reuse(self, conn, monkeypatch):
        service = _make_service(conn, monkeypatch)
        service.register_task("t1", 7)
        assert service.find_running_task(7) == "t1"
        assert service.has_running_task()
        service._update("t1", status="completed", finished_at=time.time())
        assert service.find_running_task(7) is None

    def test_cancel_task_without_running(self, conn, monkeypatch):
        service = _make_service(conn, monkeypatch)
        assert service.cancel_task("nope")["ok"] is False


# ---------------------------------------------------------------------------
# 画像注入器（profile_chapter_digest）
# ---------------------------------------------------------------------------

class TestDigestInjection:

    @staticmethod
    def _seed_summaries(conn):
        conn.execute(
            "CREATE TABLE chapter_summaries("
            " id INTEGER PRIMARY KEY AUTOINCREMENT, conversation_id INTEGER NOT NULL,"
            " fingerprint TEXT NOT NULL, from_ts INTEGER NOT NULL, to_ts INTEGER NOT NULL,"
            " summary_json TEXT NOT NULL, version INTEGER NOT NULL,"
            " model_id TEXT NOT NULL DEFAULT '', created_at INTEGER NOT NULL,"
            " UNIQUE(conversation_id, fingerprint, version))"
        )
        rows = [
            (1, "v1:0-100", 0, 100, '{"summary": "初识章", "phase": "初识期"}', SUMMARY_VERSION),
            (1, "v1:100-200", 100, 200, '{"summary": "熟络章", "phase": "熟络期"}', SUMMARY_VERSION),
            (1, "v1:old-99", 300, 400, '{"summary": "旧版失明", "phase": "旧"}', SUMMARY_VERSION - 1),
            (2, "v1:0-100", 0, 100, '{"summary": "别的会话", "phase": ""}', SUMMARY_VERSION),
        ]
        for cid, fp, f, t, js, ver in rows:
            conn.execute(
                "INSERT INTO chapter_summaries(conversation_id, fingerprint,"
                " from_ts, to_ts, summary_json, version, created_at)"
                " VALUES (?,?,?,?,?,?,?)",
                (cid, fp, f, t, js, ver, 1),
            )
        conn.commit()

    def test_rolling_takes_all_chapters(self, conn):
        self._seed_summaries(conn)
        digest = digest_mod.collect_chapter_digest(conn, 1)
        assert [d["summary"] for d in digest] == ["初识章", "熟络章"]
        assert digest[0]["phase"] == "初识期"

    def test_custom_window_overlaps_only(self, conn):
        self._seed_summaries(conn)
        digest = digest_mod.collect_chapter_digest(conn, 1, from_ts=150, to_ts=250)
        assert [d["summary"] for d in digest] == ["熟络章"]

    def test_missing_table_silent_empty(self, conn):
        assert digest_mod.collect_chapter_digest(conn, 99) == []

    def test_render_block(self, conn):
        self._seed_summaries(conn)
        digest = digest_mod.collect_chapter_digest(conn, 1)
        block = digest_mod.render_chapter_digest_block(digest)
        assert "【关系章节摘要】" in block
        assert "第1章" in block and "初识章" in block
        assert digest_mod.render_chapter_digest_block([]) == ""

    def test_dropped_on_redact_failure(self, conn, monkeypatch):
        self._seed_summaries(conn)

        class _Broken:
            def redact(self, text, **kw):
                if "熟络" in text:
                    raise RuntimeError("boom")
                return SimpleNamespace(redacted_text=text)

        monkeypatch.setattr(digest_mod, "PrivacyRedactor", lambda: _Broken())
        digest = digest_mod.collect_chapter_digest(conn, 1)
        assert [d["summary"] for d in digest] == ["初识章"]  # 脱敏失败章丢弃
