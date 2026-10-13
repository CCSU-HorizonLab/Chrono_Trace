"""群聊统计与日报测试：成员聚合/我的排名/时段范围/日报降级与 LLM 链路。"""

import json
import os
import sqlite3
import sys
import time
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import app.services.analysis.group_summary_service as gsmod
from app.services.analysis.group_summary_service import (
    GroupSummaryError,
    GroupSummaryService,
)

NOW = int(time.time())  # 以真实时钟为基准：日报窗口按 time.time() 计算


class _FakeHTTP:
    def __init__(self, content="1. 主要话题：周末爬山\n2. 群氛围：活跃"):
        self.content = content
        self.calls = []

    def __call__(self, *, url, payload, timeout, log, log_prefix, headers=None, **kw):
        self.calls.append({"url": url, "payload": payload})
        return {"choices": [{"message": {"content": self.content}}]}


@pytest.fixture
def db(monkeypatch):
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE conversations (id INTEGER PRIMARY KEY, conversation_type TEXT,"
        " display_name TEXT, account_wxid TEXT)"
    )
    conn.execute(
        "CREATE TABLE messages (id INTEGER PRIMARY KEY AUTOINCREMENT, conversation_id INT,"
        " message_type INT, is_sender INT, sender TEXT, content TEXT, timestamp INT)"
    )
    conn.execute(
        "INSERT INTO conversations VALUES (1, 'group', '爬山群', 'wxid_me'),"
        " (2, 'private', '阿明', 'wxid_me')"
    )
    monkeypatch.setattr(gsmod, "get_db", lambda: conn)
    yield conn
    conn.close()


def seed(db, sender, text, ts, is_sender=0, conv=1):
    db.execute(
        "INSERT INTO messages (conversation_id, message_type, is_sender, sender, content, timestamp)"
        " VALUES (?, 1, ?, ?, ?, ?)",
        (conv, is_sender, "" if is_sender else sender, text, ts),
    )


# ===== 发言统计 =====


def test_group_stats_aggregates_members_and_my_rank(db):
    seed(db, "阿强", "周末去爬山", NOW)
    seed(db, "阿强", "带好装备", NOW + 60)
    seed(db, "小美", "我也去", NOW + 120)
    seed(db, "", "我报名", NOW + 180, is_sender=1)

    stats = GroupSummaryService().get_group_stats(1)

    assert stats["total_messages"] == 4
    names = [m["name"] for m in stats["members"]]
    assert names[0] == "阿强"  # 2 条居首
    assert "我" in names and "小美" in names
    qiang = next(m for m in stats["members"] if m["name"] == "阿强")
    assert qiang["message_count"] == 2 and qiang["share"] == 0.5
    assert qiang["char_count"] == len("周末去爬山") + len("带好装备")
    # 我 1 条；同计数按首次出现序排（阿强2 → 小美1 → 我1），我的排名为第 3
    assert stats["my_rank"] == 3
    # 文本消息计入时段分布
    assert sum(stats["active_hours"].values()) == 4


def test_group_stats_rejects_private_conversation(db):
    with pytest.raises(GroupSummaryError):
        GroupSummaryService().get_group_stats(2)


def test_group_stats_range_filter(db):
    seed(db, "阿强", "旧消息", NOW - 30 * 86400)
    seed(db, "阿强", "新消息", NOW)
    stats = GroupSummaryService().get_group_stats(1, start=NOW - 86400)
    assert stats["total_messages"] == 1


def test_group_stats_top_words_filters_stopwords(db):
    seed(db, "阿强", "爬山 爬山 爬山 那个 哈哈", NOW)
    stats = GroupSummaryService().get_group_stats(1)
    words = {w["word"]: w["count"] for w in stats["top_words"]}
    assert words.get("爬山") == 3
    assert "那个" not in words and "哈哈" not in words


# ===== 日报 =====


def test_summary_degrades_without_model(monkeypatch, db):
    import app.services.realtime.rag.fact_llm as factllm

    monkeypatch.setattr(factllm, "get_active_model_config", lambda: None)
    seed(db, "阿强", "样本", NOW)

    result = GroupSummaryService().generate_group_summary(1, days=7)

    assert result["ok"] is True and result["degraded"] is True
    assert "LLM" in result["degraded_reason"]
    assert result["stats"]["total_messages"] >= 1


def test_summary_calls_llm_with_day_segments(monkeypatch, db):
    import app.services.realtime.rag.fact_llm as factllm

    monkeypatch.setattr(
        factllm,
        "get_active_model_config",
        lambda: {"api_base_url": "http://127.0.0.1:11434/v1", "model_id": "qwen", "api_key": ""},
    )
    # 两个不同日期的消息 → prompt 应有日期分段头与发送者
    seed(db, "阿强", "上周的计划", NOW - 3 * 86400)
    seed(db, "小美", "最新的安排", NOW)

    http = _FakeHTTP()
    monkeypatch.setattr(gsmod, "post_json_with_retries", http)

    result = GroupSummaryService().generate_group_summary(1, days=7)

    assert result["degraded"] is False and "主要话题" in result["summary"]
    sent = json.dumps(http.calls[0]["payload"], ensure_ascii=False)
    assert "—— " in sent and "阿强" in sent and "小美" in sent
    assert "近 7 天" in sent


def test_summary_no_messages_degrades(monkeypatch, db):
    import app.services.realtime.rag.fact_llm as factllm

    monkeypatch.setattr(
        factllm,
        "get_active_model_config",
        lambda: {"api_base_url": "http://127.0.0.1:11434/v1", "model_id": "qwen", "api_key": ""},
    )
    result = GroupSummaryService().generate_group_summary(1, days=1)
    assert result["degraded"] is True
    assert "没有可用的文本消息" in result["degraded_reason"]


def test_summary_remote_model_redacts(monkeypatch, db):
    import app.services.realtime.rag.config as ragcfg
    import app.services.realtime.rag.fact_llm as factllm
    import app.services.realtime.privacy_redactor as prmod

    monkeypatch.setattr(
        factllm,
        "get_active_model_config",
        lambda: {"api_base_url": "https://api.deepseek.com/v1", "model_id": "d", "api_key": ""},
    )
    monkeypatch.setattr(ragcfg, "is_remote_llm_model", lambda cfg: True)

    captured = {}

    class _CapturingRedactor:
        def redact(self, text, **kw):
            captured.update(kw)
            return SimpleNamespace(redacted_text=text.replace("13800001111", "[手机号]"))

    monkeypatch.setattr(prmod, "PrivacyRedactor", lambda conn: _CapturingRedactor())
    seed(db, "阿强", "我电话 13800001111", NOW)

    http = _FakeHTTP()
    monkeypatch.setattr(gsmod, "post_json_with_retries", http)

    result = GroupSummaryService().generate_group_summary(1, days=7)

    assert result["degraded"] is False
    sent = json.dumps(http.calls[0]["payload"], ensure_ascii=False)
    assert "13800001111" not in sent and "[手机号]" in sent
    # 占位符键需要账号维度：account_wxid 必须随脱敏调用传递
    assert captured.get("account_wxid") == "wxid_me"
    assert captured.get("conversation_id") == 1


def test_render_single_day_overflow_trims_within_day():
    """单日超预算：日内从最早消息裁起，保底 1 行，总长收回预算内。"""
    ts = NOW
    segments = {
        time.strftime("%Y-%m-%d", time.localtime(ts)): [
            ("阿强", "满" * gsmod.PER_MESSAGE_CHARS, ts + i) for i in range(gsmod.PER_DAY_MESSAGES)
        ]
    }
    lines = GroupSummaryService._render_segments(segments)
    assert len(lines) >= 2  # 日期头 + 至少 1 条消息
    assert len("\n".join(lines)) <= gsmod.MAX_SUMMARY_CHARS
    # 裁的是最早的行：保底保留的是最后一条
    assert lines[-1].endswith("满" * gsmod.PER_MESSAGE_CHARS)


def test_summary_cancel_aborts_pending_llm(monkeypatch, db):
    """在途日报可取消：bridge 线程立即抛「已取消」。"""
    import app.services.realtime.llm_http as llmhttp
    import app.services.realtime.rag.fact_llm as factllm

    monkeypatch.setattr(
        factllm,
        "get_active_model_config",
        lambda: {"api_base_url": "http://127.0.0.1:11434/v1", "model_id": "qwen", "api_key": ""},
    )
    seed(db, "阿强", "样本消息", NOW)

    def slow_post(*, should_abort=None, **kw):
        llmhttp.request_llm_cancel(gsmod.GS_CANCEL_SCOPE, 1)
        deadline = time.time() + 5
        while not (should_abort and should_abort()) and time.time() < deadline:
            time.sleep(0.02)
        return {"choices": [{"message": {"content": "迟到"}}]}

    monkeypatch.setattr(gsmod, "post_json_with_retries", slow_post)

    with pytest.raises(GroupSummaryError) as exc:
        GroupSummaryService().generate_group_summary(1, days=1)
    assert "取消" in str(exc.value)


def test_summary_range_follows_days_param(monkeypatch, db):
    import app.services.realtime.rag.fact_llm as factllm

    monkeypatch.setattr(
        factllm,
        "get_active_model_config",
        lambda: {"api_base_url": "http://127.0.0.1:11434/v1", "model_id": "qwen", "api_key": ""},
    )
    # 20 天前的消息不在「近 7 天」窗口内：无记录走降级，不触达 LLM
    seed(db, "阿强", "很早的消息", NOW - 20 * 86400)

    http = _FakeHTTP()
    monkeypatch.setattr(gsmod, "post_json_with_retries", http)

    result = GroupSummaryService().generate_group_summary(1, days=7)
    assert result["degraded"] is True
    assert http.calls == []
