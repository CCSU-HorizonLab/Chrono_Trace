"""问问微信（历史问答）测试：混合检索/RRF 融合/脱敏阻断/引用回填。"""

import json
import os
import pickle
import sqlite3
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import app.services.analysis.history_qa_service as hqmod
from app.services.analysis.history_qa_service import (
    HistoryQAError,
    HistoryQAService,
)


class _FakeHTTP:
    def __init__(self, content="根据记录 [1]，TA 喜欢爬山。"):
        self.content = content
        self.calls = []

    def __call__(self, *, url, payload, timeout, log, log_prefix, headers=None, **kw):
        self.calls.append({"url": url, "payload": payload})
        return {"choices": [{"message": {"content": self.content}}]}


class _FakeRedactor:
    def __init__(self, fail=False):
        self.fail = fail
        self.texts = []

    def redact(self, text, **kw):
        if self.fail:
            raise RuntimeError("redactor broken")
        self.texts.append(text)
        return SimpleNamespace(redacted_text=text.replace("13800001111", "[手机号]"))


@pytest.fixture
def db(monkeypatch):
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE conversations (id INTEGER PRIMARY KEY, account_wxid TEXT,"
        " username TEXT, display_name TEXT)"
    )
    conn.execute(
        "CREATE TABLE messages (id INTEGER PRIMARY KEY, conversation_id INT,"
        " message_type INT, is_sender INT, content TEXT, timestamp INT)"
    )
    conn.execute(
        "CREATE TABLE sentiment_cache (message_id INTEGER PRIMARY KEY,"
        " polarity INT, intensity REAL, embedding_vector BLOB, created_at INT)"
    )
    conn.execute("INSERT INTO conversations VALUES (1, 'wxid_me', 'wxid_a', '阿明')")
    monkeypatch.setattr(hqmod, "get_db", lambda: conn)
    yield conn
    conn.close()


def seed(db, mid, text, ts, is_sender=0, mtype=1):
    db.execute(
        "INSERT INTO messages (id, conversation_id, message_type, is_sender, content, timestamp)"
        " VALUES (?,?,?, ?, ?, ?)",
        (mid, 1, mtype, is_sender, text, ts),
    )


def use_local_model(monkeypatch):
    """本地模型：get_active_model_config 返回 ollama，免脱敏。"""
    import app.services.realtime.rag.config as ragcfg
    import app.services.realtime.rag.fact_llm as factllm

    monkeypatch.setattr(
        factllm,
        "get_active_model_config",
        lambda: {"api_base_url": "http://127.0.0.1:11434/v1", "model_id": "qwen", "api_key": ""},
    )


def ask(monkeypatch, db, question, http=None):
    http = http or _FakeHTTP()
    monkeypatch.setattr(hqmod, "post_json_with_retries", http)
    monkeypatch.setattr(hqmod, "_load_question_vector", lambda q: None)  # 纯关键词通道
    use_local_model(monkeypatch)
    return HistoryQAService().ask(1, question), http


# ===== 检索与回答 =====


def test_keyword_retrieval_and_citation_round_trip(monkeypatch, db):
    seed(db, 1, "周末去爬山吧，带上防晒", 1700000100)
    seed(db, 2, "好呀，我也想爬山很久了", 1700000200, is_sender=1)
    seed(db, 3, "今晚吃什么", 1700000300)  # 无关消息，不应入选

    result, http = ask(monkeypatch, db, "我们聊过爬山吗")

    assert "爬山" in result["answer"]
    # 默认桩回答只引用 [1]：citations 过滤为实际引用子集（消息 2 命中但未被引用）
    ids = [c["message_id"] for c in result["citations"]]
    assert ids == [1] and 3 not in ids
    # 引用带时间与发送方原文（本地展示用原文）
    by_id = {c["message_id"]: c for c in result["citations"]}
    assert by_id[1]["is_sender"] == 0 and "防晒" in by_id[1]["text"]
    # prompt 中包含脱敏前定位文本与编号
    sent = json.dumps(http.calls[0]["payload"], ensure_ascii=False)
    assert "[1]" in sent and "爬山" in sent


def test_citations_follow_answer_markers(monkeypatch, db):
    seed(db, 1, "第一条爬山消息", 1700000100)
    seed(db, 2, "第二条爬山消息", 1700000200)

    # 回答引用 [2]：citations 只含第二条（时间升序编号，2 = 消息 2）
    result, _ = ask(monkeypatch, db, "爬山", http=_FakeHTTP(content="答案见 [2]"))
    assert [c["message_id"] for c in result["citations"]] == [2]

    # 回答未带有效编号：退回全集（保留上下文浏览价值）
    result, _ = ask(monkeypatch, db, "爬山", http=_FakeHTTP(content="没有编号的回答"))
    assert len(result["citations"]) == 2


def test_no_matching_records_raises(monkeypatch, db):
    seed(db, 1, "今晚吃什么", 1700000100)
    with pytest.raises(HistoryQAError) as exc:
        # 问题分词（跳伞/话题/聊过）与消息无交集才判「没有找到」
        ask(monkeypatch, db, "跳伞这个话题我们聊过吗")
    assert "没有找到" in str(exc.value)


def test_empty_question_rejected():
    with pytest.raises(HistoryQAError):
        HistoryQAService().ask(1, "   ")


def test_vector_channel_ranks_by_cosine_and_skips_dim_mismatch(monkeypatch, db):
    seed(db, 1, "我喜欢吃火锅", 1700000100)
    seed(db, 2, "看电影去不去", 1700000200)
    db.execute(
        "INSERT INTO sentiment_cache VALUES (1, 1, 0.5, ?, 1)",
        (pickle.dumps([1.0, 0.0, 0.0]),),
    )
    db.execute(
        "INSERT INTO sentiment_cache VALUES (2, 0, 0.0, ?, 1)",
        (pickle.dumps([0.0, 1.0]),),  # 旧模型宽度，应跳过
    )
    monkeypatch.setattr(hqmod, "_load_question_vector", lambda q: [0.9, 0.1, 0.0])

    http = _FakeHTTP()
    monkeypatch.setattr(hqmod, "post_json_with_retries", http)
    use_local_model(monkeypatch)

    result = HistoryQAService().ask(1, "吃的偏好")

    ids = [c["message_id"] for c in result["citations"]]
    assert ids == [1]  # 只有维度匹配且相关的消息入选


def test_context_sorted_by_time_and_char_budget(monkeypatch, db):
    # 两条命中，时间倒序入库；上下文应按时间升序呈现
    seed(db, 10, "后来的消息", 1700000900)
    seed(db, 11, "更早的消息", 1700000100)
    result, _ = ask(monkeypatch, db, "消息")
    ts = [c["timestamp"] for c in result["citations"]]
    assert ts == sorted(ts)


# ===== 模型门槛与脱敏 =====


def test_no_llm_config_raises(monkeypatch, db):
    import app.services.realtime.rag.fact_llm as factllm

    monkeypatch.setattr(factllm, "get_active_model_config", lambda: None)
    monkeypatch.setattr(hqmod, "_load_question_vector", lambda q: None)
    seed(db, 1, "样本消息", 1700000100)
    with pytest.raises(HistoryQAError) as exc:
        HistoryQAService().ask(1, "样本")
    assert "LLM" in str(exc.value)


def test_remote_model_redacts_before_send(monkeypatch, db):
    import app.services.realtime.rag.config as ragcfg
    import app.services.realtime.rag.fact_llm as factllm
    import app.services.realtime.privacy_redactor as prmod

    monkeypatch.setattr(
        factllm,
        "get_active_model_config",
        lambda: {"api_base_url": "https://api.deepseek.com/v1", "model_id": "d", "api_key": "k"},
    )
    redactor = _FakeRedactor()
    monkeypatch.setattr(prmod, "PrivacyRedactor", lambda conn: redactor)
    seed(db, 1, "我电话 13800001111 有空联系", 1700000100)

    http = _FakeHTTP()
    monkeypatch.setattr(hqmod, "post_json_with_retries", http)
    monkeypatch.setattr(hqmod, "_load_question_vector", lambda q: None)

    result = HistoryQAService().ask(1, "电话")

    sent = json.dumps(http.calls[0]["payload"], ensure_ascii=False)
    assert "13800001111" not in sent and "[手机号]" in sent
    # 引用回填仍是本地原文（展示不外发）
    assert "13800001111" in result["citations"][0]["text"]


def test_remote_model_redacts_question_text(monkeypatch, db):
    """问题原文含手机号：payload 中的问题同样必须脱敏（P1 红线）。"""
    import app.services.realtime.rag.config as ragcfg
    import app.services.realtime.rag.fact_llm as factllm
    import app.services.realtime.privacy_redactor as prmod

    monkeypatch.setattr(
        factllm,
        "get_active_model_config",
        lambda: {"api_base_url": "https://api.deepseek.com/v1", "model_id": "d", "api_key": "k"},
    )
    redactor = _FakeRedactor()
    monkeypatch.setattr(prmod, "PrivacyRedactor", lambda conn: redactor)
    seed(db, 1, "打给我 13800001111 随时", 1700000100)

    http = _FakeHTTP(content="这是 TA 的号码 [1]")
    monkeypatch.setattr(hqmod, "post_json_with_retries", http)
    monkeypatch.setattr(hqmod, "_load_question_vector", lambda q: None)

    result = HistoryQAService().ask(1, "13800001111 是谁的号码")

    sent = json.dumps(http.calls[0]["payload"], ensure_ascii=False)
    # 问题与记录都不得出现原文号码
    assert "13800001111" not in sent
    assert sent.count("[手机号]") >= 2  # 问题 + 记录各一处
    # 返回给前端的问题保持本地原文（仅展示，不外发）
    assert "13800001111" in result["question"]


def test_remote_model_redaction_failure_blocks(monkeypatch, db):
    import app.services.realtime.rag.config as ragcfg
    import app.services.realtime.rag.fact_llm as factllm
    import app.services.realtime.privacy_redactor as prmod

    monkeypatch.setattr(
        factllm,
        "get_active_model_config",
        lambda: {"api_base_url": "https://api.deepseek.com/v1", "model_id": "d", "api_key": ""},
    )
    monkeypatch.setattr(prmod, "PrivacyRedactor", lambda conn: _FakeRedactor(fail=True))
    seed(db, 1, "样本", 1700000100)
    monkeypatch.setattr(hqmod, "_load_question_vector", lambda q: None)

    with pytest.raises(HistoryQAError) as exc:
        HistoryQAService().ask(1, "样本")
    assert "阻断" in str(exc.value)
