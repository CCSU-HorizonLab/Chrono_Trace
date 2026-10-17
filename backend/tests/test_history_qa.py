"""问问微信（历史问答）测试：混合检索/RRF 融合/脱敏阻断/引用回填/向量缓存/取消。"""

import json
import os
import pickle
import sqlite3
import sys
import threading
import time
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


@pytest.fixture(autouse=True)
def _clear_module_state():
    """模块级向量缓存与共享取消注册表按测试隔离。"""
    import app.services.realtime.llm_http as llmhttp

    hqmod._VECTOR_CACHE.clear()
    llmhttp._CANCELLED.clear()
    yield
    hqmod._VECTOR_CACHE.clear()
    llmhttp._CANCELLED.clear()


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
    assert result["citations"][0]["index"] == 1
    # 引用带时间与发送方原文（本地展示用原文）
    by_id = {c["message_id"]: c for c in result["citations"]}
    assert by_id[1]["is_sender"] == 0 and "防晒" in by_id[1]["text"]
    # prompt 中包含脱敏前定位文本与编号
    sent = json.dumps(http.calls[0]["payload"], ensure_ascii=False)
    assert "[1]" in sent and "爬山" in sent


def test_citations_follow_answer_markers(monkeypatch, db):
    seed(db, 1, "第一条爬山消息", 1700000100)
    seed(db, 2, "第二条爬山消息", 1700000200)

    # 回答引用 [2]：citations 只含第二条；回答去 [n] 编号后引用重排为连续序号
    result, _ = ask(monkeypatch, db, "爬山", http=_FakeHTTP(content="答案见 [2]"))
    assert [c["message_id"] for c in result["citations"]] == [2]
    assert result["citations"][0]["index"] == 1
    assert "[" not in result["answer"] and "答案见" in result["answer"]

    # 回答未带有效编号：不把全量上下文冒充引用溯源
    result, _ = ask(monkeypatch, db, "爬山", http=_FakeHTTP(content="没有编号的回答"))
    assert result["citations"] == []


def test_answer_citation_marks_stripped_cleanly(monkeypatch, db):
    seed(db, 1, "周末去爬山吧", 1700000100)
    result, _ = ask(
        monkeypatch, db, "爬山", http=_FakeHTTP(content="结论是这样 [1][2] ，细节如下 [9]。")
    )
    # 编号剔除后标点前的空格收掉，不残留连续空格
    assert result["answer"] == "结论是这样，细节如下。"


def test_reasoning_content_not_leaked_as_answer(monkeypatch, db):
    """思考模型正文为空：不把思维链当回答，明确报错并留现场。"""
    seed(db, 1, "样本消息", 1700000100)

    class _ThinkingHTTP(_FakeHTTP):
        def __call__(self, **kw):
            super().__call__(**kw)
            return {
                "choices": [
                    {
                        "message": {"content": "", "reasoning_content": "思维链……"},
                        "finish_reason": "length",
                    }
                ]
            }

    monkeypatch.setattr(hqmod, "post_json_with_retries", _ThinkingHTTP())
    monkeypatch.setattr(hqmod, "_load_question_vector", lambda q: None)
    use_local_model(monkeypatch)
    with pytest.raises(HistoryQAError) as exc:
        HistoryQAService().ask(1, "样本")
    assert "空回答" in str(exc.value)


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


def test_vector_cache_reuses_deserialization_and_rebuilds_on_change(monkeypatch, db):
    seed(db, 1, "我喜欢吃火锅", 1700000100)
    db.execute(
        "INSERT INTO sentiment_cache VALUES (1, 1, 0.5, ?, 1)",
        (pickle.dumps([1.0, 0.0]),),
    )
    svc = HistoryQAService()
    entry1 = svc._load_vector_cache(1)
    assert entry1["by_dim"][2]["metas"][0]["message_id"] == 1

    calls = {"n": 0}
    real_loads = pickle.loads

    def counting(buf):
        calls["n"] += 1
        return real_loads(buf)

    monkeypatch.setattr(hqmod.pickle, "loads", counting)

    # 指纹未变：直接复用缓存，不再反序列化任何向量
    entry2 = svc._load_vector_cache(1)
    assert calls["n"] == 0
    assert entry2["by_dim"][2]["vectors"] == entry1["by_dim"][2]["vectors"]

    # 新增向量行 → 指纹变化 → 重建
    seed(db, 2, "看电影去不去", 1700000200)
    db.execute(
        "INSERT INTO sentiment_cache VALUES (2, 0, 0.0, ?, 1)",
        (pickle.dumps([0.0, 1.0]),),
    )
    entry3 = svc._load_vector_cache(1)
    assert calls["n"] >= 1
    assert len(entry3["by_dim"][2]["metas"]) == 2


def test_vector_cache_not_poisoned_by_transient_fetch_failure(monkeypatch, db):
    """行抓取瞬时失败：本次降级为无向量，且不把空结果写进缓存。"""
    seed(db, 1, "我喜欢吃火锅", 1700000100)
    db.execute(
        "INSERT INTO sentiment_cache VALUES (1, 1, 0.5, ?, 1)",
        (pickle.dumps([1.0, 0.0]),),
    )
    svc = HistoryQAService()
    real_get_db = hqmod.get_db

    class FlakyConn:
        """指纹查询（COUNT）放行，向量行抓取抛错。"""

        def __init__(self, inner):
            self._inner = inner

        def execute(self, sql, *args):
            if "COUNT" not in sql and "embedding_vector IS NOT NULL" in sql:
                raise sqlite3.OperationalError("database is locked")
            return self._inner.execute(sql, *args)

    with monkeypatch.context() as m:
        m.setattr(hqmod, "get_db", lambda: FlakyConn(real_get_db()))
        entry = svc._load_vector_cache(1)
        assert entry["by_dim"] == {}
        assert 1 not in hqmod._VECTOR_CACHE  # 空结果未落缓存

    # 异常恢复后同一指纹正常重建，向量通道不受毒化影响
    entry2 = svc._load_vector_cache(1)
    assert entry2["by_dim"][2]["metas"][0]["message_id"] == 1


def test_keyword_channel_escapes_like_wildcards(monkeypatch, db):
    """问句分词含 % / _：按字面匹配，不当通配符放大召回。"""
    monkeypatch.setattr(hqmod, "_extract_keywords", lambda q: ["100_x", "50%"])
    seed(db, 1, "看下 100_x 的进度", 1700000100)
    seed(db, 2, "看下 100Ax 的进度", 1700000200)  # _ 当通配符会误中
    seed(db, 3, "打了 50 折 优惠", 1700000300)     # % 前缀 50 会误中

    rows = HistoryQAService()._keyword_channel(1, "ignored")

    assert [r["message_id"] for r in rows] == [1]


def test_keyword_channel_covers_cold_terms_beyond_flood(monkeypatch, db):
    """逐关键词取数：高频词刷不满候选池，冷门词的更早消息也能进池。"""
    monkeypatch.setattr(hqmod, "_extract_keywords", lambda q: ["我们", "跳伞"])
    # 15 条最新的高频词消息（超过单关键词上限）
    for i in range(15):
        seed(db, 100 + i, f"我们随便聊聊 {i}", 1700000000 + i)
    seed(db, 50, "去年说好去跳伞的", 1600000000)  # 冷门词、时间最早

    rows = HistoryQAService()._keyword_channel(1, "ignored")

    ids = [r["message_id"] for r in rows]
    assert 50 in ids  # 冷门词的早期命中不被高频词挤出
    assert len(ids) <= 2 * hqmod.KEYWORD_PER_TERM_LIMIT


def test_context_sorted_by_time_and_char_budget(monkeypatch, db):
    # 两条命中，时间倒序入库；上下文应按时间升序呈现
    seed(db, 10, "后来的消息", 1700000900)
    seed(db, 11, "更早的消息", 1700000100)
    result, _ = ask(monkeypatch, db, "消息")
    ts = [c["timestamp"] for c in result["citations"]]
    assert ts == sorted(ts)


# ===== 多轮问答 =====


def test_history_block_and_merged_retrieval(monkeypatch, db):
    """上一问的实词并入检索：「那次花了多少钱」靠上文的「火锅」命中记录。"""
    seed(db, 1, "周末吃火锅，两个人 350 块", 1700000100)

    # 无历史时当前问句无命中关键词
    with pytest.raises(HistoryQAError):
        ask(monkeypatch, db, "那次花了多少钱")

    http = _FakeHTTP()
    monkeypatch.setattr(hqmod, "post_json_with_retries", http)
    monkeypatch.setattr(hqmod, "_load_question_vector", lambda q: None)
    use_local_model(monkeypatch)

    result = HistoryQAService().ask(
        1,
        "那次花了多少钱",
        history=[{"question": "我们去哪吃的火锅", "answer": "你们去吃了火锅"}],
    )

    sent = json.dumps(http.calls[0]["payload"], ensure_ascii=False)
    assert "【历史问答】" in sent and "我们去哪吃的火锅" in sent
    # 检索靠上一问的「火锅」命中，引用回填成功
    assert [c["message_id"] for c in result["citations"]] == [1]


def test_history_redacted_for_remote(monkeypatch, db):
    """远程模型：历史问答同样过脱敏（前端回传按不可信输入处理）。"""
    import app.services.realtime.rag.config as ragcfg
    import app.services.realtime.rag.fact_llm as factllm
    import app.services.realtime.privacy_redactor as prmod

    seed(db, 1, "电话在名片上", 1700000100)
    monkeypatch.setattr(
        factllm,
        "get_active_model_config",
        lambda: {"api_base_url": "https://api.deepseek.com/v1", "model_id": "d", "api_key": ""},
    )
    monkeypatch.setattr(ragcfg, "is_remote_llm_model", lambda cfg: True)
    monkeypatch.setattr(prmod, "PrivacyRedactor", lambda conn: _FakeRedactor())

    http = _FakeHTTP()
    monkeypatch.setattr(hqmod, "post_json_with_retries", http)
    monkeypatch.setattr(hqmod, "_load_question_vector", lambda q: None)

    HistoryQAService().ask(
        1,
        "接着说",
        history=[{"question": "电话 13800001111 是谁的", "answer": "是 TA 的 [手机号]"}],
    )

    sent = json.dumps(http.calls[0]["payload"], ensure_ascii=False)
    assert "13800001111" not in sent
    assert "13800001111 是谁的" not in sent


def test_history_normalized_and_capped(monkeypatch, db):
    """历史清洗：只留成对轮次、截最近几轮、异常输入按无历史。"""
    turns = HistoryQAService()._normalize_history(
        [
            {"question": "q1", "answer": "a1"},
            {"question": "只有问题", "answer": ""},
            "垃圾项",
            {"question": "q4", "answer": "a4"},
            {"question": "q5", "answer": "a5"},
        ]
    )
    assert turns == [
        {"question": "q4", "answer": "a4"},
        {"question": "q5", "answer": "a5"},
    ]
    assert HistoryQAService()._normalize_history(None) == []
    assert HistoryQAService()._normalize_history("不是列表") == []
    long_q = "问" * 999
    assert HistoryQAService()._normalize_history(
        [{"question": long_q, "answer": "a"}]
    )[0]["question"] == long_q[: hqmod.HISTORY_TURN_CHARS]


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


# ===== 取消 =====


def test_cancel_aborts_pending_ask(monkeypatch, db):
    """在途请求可取消：bridge 线程立即抛「已取消」，工作线程经 should_abort 退出。"""
    seed(db, 1, "样本消息", 1700000100)

    def slow_post(*, should_abort=None, **kw):
        hqmod.request_cancel(1)  # 模拟用户在请求在途时点「取消」
        deadline = time.time() + 5
        while not (should_abort and should_abort()) and time.time() < deadline:
            time.sleep(0.02)
        return {"choices": [{"message": {"content": "迟到的回答 [1]"}}]}

    monkeypatch.setattr(hqmod, "post_json_with_retries", slow_post)
    monkeypatch.setattr(hqmod, "_load_question_vector", lambda q: None)
    use_local_model(monkeypatch)

    with pytest.raises(HistoryQAError) as exc:
        HistoryQAService().ask(1, "样本")
    assert "取消" in str(exc.value)


# ===== RAG 长期记忆槽 =====


def _fake_rag(monkeypatch, items):
    """替换 RAG 检索器：返回给定记忆条目；返回 calls 供断言。"""
    import app.services.realtime.rag.config as ragcfg
    import app.services.realtime.rag.retriever as retriever_mod

    monkeypatch.setattr(ragcfg, "load_rag_settings", lambda: {"rag_enabled": True})
    calls = {}

    class _Retriever:
        def __init__(self):
            pass

        def retrieve(self, **kw):
            calls.update(kw)
            return {"items": [{"content": c} for c in items], "strategy": "facts"}

    monkeypatch.setattr(retriever_mod, "RagRetriever", _Retriever)
    return calls


def test_rag_memories_injected_into_prompt(monkeypatch, db):
    seed(db, 1, "周末去爬山吧，带上防晒", 1700000100)
    calls = _fake_rag(monkeypatch, ["对方每周三固定打羽毛球", "对方对猫过敏"])

    result, http = ask(monkeypatch, db, "我们聊过爬山吗")

    sent = json.dumps(http.calls[0]["payload"], ensure_ascii=False)
    assert "【长期记忆】" in sent
    assert "- 对方每周三固定打羽毛球" in sent and "对猫过敏" in sent
    # 检索键：当前会话 + 原始问题
    assert calls["conversation_id"] == 1 and calls["account_wxid"] == "wxid_me"
    assert calls["query"] == "我们聊过爬山吗"
    # 消息引用编号不受记忆条目影响
    assert result["citations"] and result["citations"][0]["index"] == 1


def test_rag_memories_absent_when_retrieval_empty(monkeypatch, db):
    seed(db, 1, "周末去爬山吧", 1700000100)
    _fake_rag(monkeypatch, [])

    result, http = ask(monkeypatch, db, "我们聊过爬山吗")

    sent = json.dumps(http.calls[0]["payload"], ensure_ascii=False)
    assert "【长期记忆】（从历史聊天提炼" not in sent  # 系统提示词规则行除外


def test_rag_memories_skipped_when_disabled(monkeypatch, db):
    seed(db, 1, "周末去爬山吧", 1700000100)
    import app.services.realtime.rag.config as ragcfg
    import app.services.realtime.rag.retriever as retriever_mod

    monkeypatch.setattr(ragcfg, "load_rag_settings", lambda: {"rag_enabled": False})

    class _Boom:
        def __init__(self):
            raise AssertionError("RAG 关闭时不应构造检索器")

    monkeypatch.setattr(retriever_mod, "RagRetriever", _Boom)

    result, http = ask(monkeypatch, db, "我们聊过爬山吗")
    assert "【长期记忆】（从历史聊天提炼" not in json.dumps(http.calls[0]["payload"], ensure_ascii=False)


def test_rag_memories_redacted_for_remote(monkeypatch, db):
    """远程模型：记忆条目同样过脱敏（失败即阻断红线）。"""
    import app.services.realtime.privacy_redactor as prmod
    import app.services.realtime.rag.config as ragcfg
    import app.services.realtime.rag.fact_llm as factllm

    seed(db, 1, "周末去爬山吧，我电话 13800001111", 1700000100)
    _fake_rag(monkeypatch, ["对方手机号 13800001111"])
    monkeypatch.setattr(
        factllm,
        "get_active_model_config",
        lambda: {"api_base_url": "https://api.deepseek.com/v1", "model_id": "d", "api_key": ""},
    )
    monkeypatch.setattr(ragcfg, "is_remote_llm_model", lambda cfg: True)
    monkeypatch.setattr(prmod, "PrivacyRedactor", lambda conn: _FakeRedactor())

    http = _FakeHTTP()
    monkeypatch.setattr(hqmod, "post_json_with_retries", http)
    monkeypatch.setattr(hqmod, "_load_question_vector", lambda q: None)

    HistoryQAService().ask(1, "我们聊过爬山吗")

    sent = json.dumps(http.calls[0]["payload"], ensure_ascii=False)
    assert "【长期记忆】" in sent
    assert "13800001111" not in sent and "[手机号]" in sent
