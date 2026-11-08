"""AI 分身测试：语气采样/画像降级/提示词组装/历史清洗/脱敏红线/流式回调。"""

import json
import os
import sqlite3
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import app.services.analysis.avatar_chat_service as avmod
import app.services.analysis.history_qa_service as hqmod
from app.services.analysis.avatar_chat_service import (
    AVATAR_MIN_SAMPLES,
    VOICE_QUOTE_MAX_CHARS,
    AvatarChatService,
)
from app.services.analysis.history_qa_service import HistoryQABlocked, HistoryQAError

PROFILE_SCHEMA = 5


class _LlmStub:
    """记录收到的 messages，返回固定回复（(正文, truncated) 形状）。"""

    def __init__(self, reply="嗯嗯，好呀"):
        self.reply = reply
        self.calls = []

    def __call__(self, conversation_id, messages, *, temperature, max_tokens,
                 on_delta=None, log_prefix=""):
        self.calls.append({
            "messages": messages, "temperature": temperature,
            "max_tokens": max_tokens, "on_delta": on_delta,
        })
        if on_delta is not None:
            on_delta(self.reply[:1])  # 模拟流式首字（push 链验证用）
        return self.reply, False


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
    """会话门闩与共享取消注册表按测试隔离（与问答测试同源）。"""
    import app.services.realtime.llm_http as llmhttp

    hqmod._QA_CONV_LOCKS.clear()
    llmhttp._CANCELLED.clear()
    yield
    hqmod._QA_CONV_LOCKS.clear()
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
        "CREATE TABLE contact_profiles (id INTEGER PRIMARY KEY AUTOINCREMENT,"
        " conversation_id INT, schema_version INT, window_to INT, created_at INT,"
        " profile_json TEXT)"
    )
    conn.execute("INSERT INTO conversations VALUES (1, 'wxid_me', 'wxid_a', '阿明')")
    # 两处 get_db 都指到内存库：avatar 模块自身与借用的问答服务
    monkeypatch.setattr(avmod, "get_db", lambda: conn)
    monkeypatch.setattr(hqmod, "get_db", lambda: conn)
    yield conn
    conn.close()


def seed(db, mid, text, ts, is_sender=0, mtype=1):
    db.execute(
        "INSERT INTO messages (id, conversation_id, message_type, is_sender, content, timestamp)"
        " VALUES (?, 1, ?, ?, ?, ?)",
        (mid, mtype, is_sender, text, ts),
    )


def use_local_model(monkeypatch):
    import app.services.realtime.rag.config as ragcfg
    import app.services.realtime.rag.fact_llm as factllm

    monkeypatch.setattr(
        factllm,
        "get_active_model_config",
        lambda: {"api_base_url": "http://127.0.0.1:11434/v1", "model_id": "qwen", "api_key": ""},
    )


def use_remote_model(monkeypatch):
    import app.services.realtime.rag.fact_llm as factllm

    monkeypatch.setattr(
        factllm,
        "get_active_model_config",
        lambda: {"api_base_url": "http://192.168.1.5:8004/v1", "model_id": "qwen", "api_key": "k"},
    )


def make_service(monkeypatch, db, llm=None, memories=None):
    """组装被测服务：LLM 与 RAG 记忆槽全部落桩，其余走真代码。"""
    svc = AvatarChatService()
    llm = llm or _LlmStub()
    monkeypatch.setattr(svc._qa, "_post_llm_chat", llm)
    if memories is None:
        memories = []
    monkeypatch.setattr(
        svc._qa, "_retrieve_rag_memories",
        lambda *a, **kw: ([{"content": m} for m in memories], False),
    )
    return svc, llm


def seed_voice(db, count=40, base_ts=1700000000):
    """种 count 条 TA 文本（等长可预测）+ 少量我方消息（不应入采样）。"""
    for i in range(count):
        seed(db, 1000 + i, "爬山去吗周末" if i % 2 else "嗯嗯好呀[呲牙]", base_ts + i)
    for i in range(5):
        seed(db, 2000 + i, "我方消息不进采样", base_ts + i, is_sender=1)


# ===== 语气采样 =====


def test_voice_sample_ta_side_only_and_stats(db):
    seed_voice(db, count=40)
    voice = AvatarChatService()._sample_voice(1)
    assert voice["sample_count"] == 40  # 我方 5 条不入采样
    # 两种文本长度 6/8（「嗯嗯好呀[呲牙]」的 [呲牙] 计 4 字符）各 20 条，
    # 上中位落在长组；短句占比 1.0（全部 ≤10 字）
    assert voice["median_len"] == 8
    assert voice["short_ratio"] == 1.0
    assert "[呲牙]" in voice["top_emojis"]
    assert voice["quotes"] and all(
        len(q["text"]) <= VOICE_QUOTE_MAX_CHARS for q in voice["quotes"]
    )
    # 原话样本来自 TA 消息原文
    joined = "".join(q["text"] for q in voice["quotes"])
    assert "我方消息" not in joined
    assert "嗯嗯好呀" in joined or "爬山去吗" in joined


def test_voice_sample_filters_pure_emoji_and_tiny(db):
    for i in range(40):
        seed(db, 3000 + i, "[呲牙]" if i % 2 else "好", 1700000000 + i)
    voice = AvatarChatService()._sample_voice(1)
    # 纯表情码与 <4 字短句都被过滤：样本槽为空但统计照常
    assert voice["quotes"] == []
    assert voice["sample_count"] == 40


def test_voice_sample_empty_conversation(db):
    voice = AvatarChatService()._sample_voice(1)
    assert voice["sample_count"] == 0 and voice["quotes"] == []


def test_voice_top_words_drop_function_words(db):
    """高频词按词性黑名单滤功能词：代词/时间词堆不成口吻档案——
    「我们」「今天」不得进 Top，内容词照常保留。"""
    for i in range(40):
        seed(db, 5000 + i, "我们今天去爬山", 1700000000 + i)
    voice = AvatarChatService()._sample_voice(1)
    assert "我们" not in voice["top_words"]
    assert "今天" not in voice["top_words"]
    assert "爬山" in voice["top_words"]


# ===== 主链路 =====


def test_chat_below_min_samples_rejected(monkeypatch, db):
    for i in range(AVATAR_MIN_SAMPLES - 1):
        seed(db, 4000 + i, "样本不足", 1700000000 + i)
    svc, llm = make_service(monkeypatch, db)
    use_local_model(monkeypatch)
    with pytest.raises(HistoryQAError) as exc:
        svc.chat(1, "在吗")
    assert str(AVATAR_MIN_SAMPLES - 1) in str(exc.value)
    assert not llm.calls


def test_chat_empty_message_rejected(monkeypatch, db):
    svc, _ = make_service(monkeypatch, db)
    with pytest.raises(HistoryQAError):
        svc.chat(1, "   ")


def test_chat_prompt_assembly_with_profile_and_memory(monkeypatch, db):
    seed_voice(db)
    db.execute(
        "INSERT INTO contact_profiles (conversation_id, schema_version, window_to,"
        " created_at, profile_json) VALUES (1, ?, 100, 1, ?)",
        (PROFILE_SCHEMA, json.dumps({
            "personality_tags": ["细致严谨", "爱开玩笑"],
            "chat_style": "消息偏短，爱用呲牙表情",
            "interests": ["爬山", "早茶"],
            "relationship_note": "老同学，认识十年",
        })),
    )
    svc, llm = make_service(
        monkeypatch, db, memories=["TA 每周三固定去爬山"]
    )
    use_local_model(monkeypatch)
    result = svc.chat(1, "周末干嘛去", history=[
        {"role": "user", "content": "最近好吗"},
        {"role": "assistant", "content": "还行还行"},
    ])

    assert result["profile_used"] is True
    assert result["reply"] == "嗯嗯，好呀"
    assert result["voice"]["sample_count"] == 40
    messages = llm.calls[0]["messages"]
    assert [m["role"] for m in messages] == ["system", "user", "assistant", "user"]
    system = messages[0]["content"]
    for fragment in (
        "阿明", "AI 模拟", "细致严谨", "老同学", "【TA 的语气档案】",
        "【TA 的原话样本】", "【相关记忆】", "每周三固定去爬山", "不编造",
    ):
        assert fragment in system, fragment
    # 口吻温度高于问答（0.3 求准）
    assert llm.calls[0]["temperature"] == 0.7
    # 历史轮次与当前消息随 user/assistant 原生角色进入对话
    assert messages[1]["content"] == "最近好吗"
    assert messages[-1]["content"] == "周末干嘛去"


def test_chat_without_profile_degrades(monkeypatch, db):
    seed_voice(db)
    svc, llm = make_service(monkeypatch, db)
    use_local_model(monkeypatch)
    result = svc.chat(1, "在忙吗")
    assert result["profile_used"] is False
    system = llm.calls[0]["messages"][0]["content"]
    assert "【TA 的画像】" not in system
    assert "【TA 的语气档案】" in system  # 降级仍有口吻锚点


def test_chat_memory_no_hit_adds_antihallucination(monkeypatch, db):
    """检索有结果但全被门控拒（no_hit）时，系统提示词显式告知无可靠
    记录——温度 0.7 的口吻生成最需要反幻觉锚点（同问答口径）。"""
    seed_voice(db)
    svc, llm = make_service(monkeypatch, db)
    use_local_model(monkeypatch)
    monkeypatch.setattr(
        svc._qa, "_retrieve_rag_memories", lambda *a, **kw: ([], True)
    )
    svc.chat(1, "还记得上次吗")
    system = llm.calls[0]["messages"][0]["content"]
    assert "没有与此话题直接相关的可靠记录" in system
    assert "不要从" in system


def test_stale_profile_schema_ignored(monkeypatch, db):
    seed_voice(db)
    db.execute(
        "INSERT INTO contact_profiles (conversation_id, schema_version, window_to,"
        " created_at, profile_json) VALUES (1, ?, 100, 1, ?)",
        (PROFILE_SCHEMA - 1, json.dumps({"chat_style": "旧代画像"})),
    )
    svc, llm = make_service(monkeypatch, db)
    use_local_model(monkeypatch)
    result = svc.chat(1, "在吗")
    assert result["profile_used"] is False
    assert "旧代画像" not in llm.calls[0]["messages"][0]["content"]


def test_chat_survives_stale_cancel_token(monkeypatch, db):
    """上一轮退出后注册的取消（前端离开页面 onUnmounted 的无条件
    cancel）不得毒化下一轮分身对话——串行门闩入口清死残留，新提问
    正常走到 LLM 而不是被「本次提问已取消」误杀。"""
    import app.services.realtime.llm_http as llmhttp

    seed_voice(db, count=40)
    svc, llm = make_service(monkeypatch, db)
    use_local_model(monkeypatch)
    svc.chat(1, "在吗")
    # 无在途请求时的 cancel：死残留
    llmhttp.request_llm_cancel(hqmod.QA_CANCEL_SCOPE, 1)
    result = svc.chat(1, "还在吗")
    assert result["reply"] == llm.reply
    assert llmhttp.take_llm_cancel(hqmod.QA_CANCEL_SCOPE, 1) is False  # 已被入口清掉


def test_history_normalization_drops_invalid_and_truncates():
    turns = AvatarChatService._normalize_history([
        {"role": "system", "content": "不该出现"},       # 非法角色
        {"role": "user", "content": ""},                 # 空内容
        "garbage",                                        # 非字典
        {"role": "user", "content": "x" * 999},          # 超长截断
    ] + [{"role": "user", "content": f"轮{i}"} for i in range(20)])
    assert all(t["role"] == "user" for t in turns)
    # 合法 user 共 21 条（超长 1 + 轮0..19），留最近 8 条 = 轮12..轮19
    assert len(turns) == 8
    assert turns[0]["content"] == "轮12" and turns[-1]["content"] == "轮19"
    long = AvatarChatService._normalize_history([{"role": "user", "content": "x" * 999}])
    assert len(long[0]["content"]) == 400


# ===== 脱敏红线 =====


def test_remote_redacts_all_materials(monkeypatch, db):
    seed_voice(db)
    db.execute(
        "INSERT INTO contact_profiles (conversation_id, schema_version, window_to,"
        " created_at, profile_json) VALUES (1, ?, 100, 1, ?)",
        (PROFILE_SCHEMA, json.dumps({"chat_style": "爱提13800001111"})),
    )
    svc, _ = make_service(monkeypatch, db, memories=["记忆 13800001111"])
    use_remote_model(monkeypatch)
    redactor = _FakeRedactor()
    import app.services.realtime.privacy_redactor as prmod

    monkeypatch.setattr(prmod, "PrivacyRedactor", lambda db: redactor)

    svc.chat(1, "手机号 13800001111 是多少", history=[
        {"role": "user", "content": "历史里也有 13800001111"},
    ])

    seen = "".join(redactor.texts)
    # 用户消息/历史/姓名/画像/语气高频词与表情/原话样本/RAG 记忆全部过检
    for fragment in ("手机号 13800001111", "历史里也有", "爱提13800001111", "记忆 13800001111"):
        assert fragment in seen, fragment
    assert "阿明" in seen  # display_name 不再明文进 prompt
    assert any("嗯嗯好呀" in t or "爬山去吗" in t for t in redactor.texts)


def test_remote_redactor_failure_blocks(monkeypatch, db):
    seed_voice(db)
    svc, _ = make_service(monkeypatch, db)
    use_remote_model(monkeypatch)
    import app.services.realtime.privacy_redactor as prmod

    monkeypatch.setattr(prmod, "PrivacyRedactor", lambda db: _FakeRedactor(fail=True))
    with pytest.raises(HistoryQABlocked):
        svc.chat(1, "在吗")


def test_local_model_skips_redaction(monkeypatch, db):
    seed_voice(db)
    svc, llm = make_service(monkeypatch, db)
    use_local_model(monkeypatch)
    import app.services.realtime.privacy_redactor as prmod

    calls = []
    monkeypatch.setattr(prmod, "PrivacyRedactor", lambda db: calls.append(1))
    svc.chat(1, "在吗")
    assert not calls  # 本地模型不触发脱敏
    assert llm.calls[0]["messages"][-1]["content"] == "在吗"


# ===== bridge 端点 =====


def test_bridge_ask_avatar_chat_ok_and_push(monkeypatch, db):
    from app.webview.api.history_qa import HistoryQaApiMixin

    seed_voice(db)
    pushed = []
    svc, _ = make_service(monkeypatch, db)
    use_local_model(monkeypatch)

    import app.webview.push as pushmod

    monkeypatch.setattr(
        avmod, "AvatarChatService", lambda: svc,
    )
    monkeypatch.setattr(
        "app.webview.push.get_push_service",
        lambda: SimpleNamespace(push_avatar_event=pushed.append),
    )
    result = HistoryQaApiMixin().ask_avatar_chat(
        1, "在吗", [{"role": "user", "content": "上一轮"}], "req-1"
    )
    assert result["ok"] is True and result["reply"] == "嗯嗯，好呀"
    assert result["voice"]["sample_count"] == 40
    # 流式首字经 push_avatar_event 入队（打字机通道）
    assert pushed and pushed[0]["req_id"] == "req-1" and pushed[0]["text"] == "嗯"


def test_bridge_ask_avatar_chat_error_path(monkeypatch, db):
    from app.webview.api.history_qa import HistoryQaApiMixin

    result = HistoryQaApiMixin().ask_avatar_chat(1, "  ")
    assert result["ok"] is False and "说点什么" in result["error"]
