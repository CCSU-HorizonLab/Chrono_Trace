"""回复陪练测试（重设计 §4.4 陪练模式）：JSON 提取/三档归一/上下文
组装/脱敏阻断/串行门闩共用。"""

import json
import os
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
    """按 rehearse 调用形态记录 payload，返回固定 content。"""

    def __init__(self, content):
        self.content = content
        self.calls = []

    def __call__(self, *, url, payload, timeout, log, log_prefix, headers=None, **kw):
        self.calls.append({"url": url, "payload": payload})
        return {"choices": [{"message": {"content": self.content}}]}


_VALID_JSON = json.dumps(
    {
        "options": [
            {"tone": "cooler", "label": "缓一缓", "direction": "少说", "draft": "嗯嗯，先忙", "consequence": "话题冷下来"},
            {"tone": "steady", "label": "稳一稳", "direction": "接住", "draft": "收到，那周末再说", "consequence": "平稳"},
            {"tone": "closer", "label": "进一步", "direction": "主动", "draft": "要不周六我订个位？", "consequence": "升温"},
        ]
    },
    ensure_ascii=False,
)


@pytest.fixture(autouse=True)
def _clear_module_state():
    import app.services.realtime.llm_http as llmhttp

    hqmod._VECTOR_CACHE.clear()
    hqmod._QA_CONV_LOCKS.clear()
    hqmod._QA_LAST_ASK_START.clear()
    llmhttp._CANCELLED.clear()
    yield
    hqmod._VECTOR_CACHE.clear()
    hqmod._QA_CONV_LOCKS.clear()
    hqmod._QA_LAST_ASK_START.clear()
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
    import app.services.realtime.rag.fact_llm as factllm

    monkeypatch.setattr(
        factllm,
        "get_active_model_config",
        lambda: {"api_base_url": "http://127.0.0.1:11434/v1", "model_id": "qwen", "api_key": ""},
    )


def rehearse(monkeypatch, db, received, content=_VALID_JSON):
    http = _FakeHTTP(content)
    monkeypatch.setattr(hqmod, "post_json_with_retries", http)
    monkeypatch.setattr(hqmod, "_load_question_vector", lambda q: None)
    use_local_model(monkeypatch)
    return HistoryQAService().rehearse(1, received), http


# ===== JSON 提取 =====


class TestExtractJsonObject:
    def test_plain_json(self):
        assert hqmod._extract_json_object('{"a": 1}') == {"a": 1}

    def test_code_fence(self):
        assert hqmod._extract_json_object('```json\n{"a": [1,2]}\n```') == {"a": [1, 2]}

    def test_surrounding_prose(self):
        # 思考模型常在 JSON 前后夹叙述文字：取首个 { 到末个 } 的跨度
        assert hqmod._extract_json_object('好的，以下是：{"a":1} 希望有帮助') == {"a": 1}

    def test_invalid_returns_none(self):
        assert hqmod._extract_json_object("不是 JSON") is None
        assert hqmod._extract_json_object("{broken") is None
        assert hqmod._extract_json_object("[1,2]") is None  # 数组不是对象


# ===== 三档归一 =====


class TestNormalizeOptions:
    def test_fixed_tone_order(self):
        # 模型输出顺序不可信（cooler 在前）：按 steady→closer→cooler 重排
        obj = json.loads(_VALID_JSON)
        result = HistoryQAService._normalize_rehearsal_options(obj)
        assert [o["tone"] for o in result] == ["steady", "closer", "cooler"]

    def test_invalid_tone_dropped_and_fields_clipped(self):
        obj = {
            "options": [
                {"tone": "hot", "label": "x", "draft": "y"},  # 非法 tone
                {"tone": "steady", "label": "稳" * 20, "draft": "好" * 200, "direction": "d", "consequence": "c"},
                {"tone": "steady", "draft": "第二个稳档"},  # 重复档取首个
                {"tone": "closer", "direction": "没草稿"},  # 空 draft 无意义
            ]
        }
        result = HistoryQAService._normalize_rehearsal_options(obj)
        assert len(result) == 1
        assert result[0]["tone"] == "steady"
        assert len(result[0]["label"]) == 8
        assert len(result[0]["draft"]) == 120

    def test_missing_label_gets_default(self):
        obj = {"options": [{"tone": "steady", "draft": "嗯嗯"}]}
        result = HistoryQAService._normalize_rehearsal_options(obj)
        assert result[0]["label"] == "稳一稳"

    def test_not_a_dict_or_no_options(self):
        assert HistoryQAService._normalize_rehearsal_options(None) == []
        assert HistoryQAService._normalize_rehearsal_options({"options": "no"}) == []


# ===== rehearse 主流程 =====


class TestRehearse:
    def test_round_trip_and_context_injection(self, monkeypatch, db):
        seed(db, 1, "最近聊到周末爬山", 1700000100, is_sender=1)
        seed(db, 2, "周末要加班", 1700000200)
        result, http = rehearse(monkeypatch, db, "周末有空吗")
        assert result["ok"] is True
        assert result["contact_name"] == "阿明"
        assert [o["tone"] for o in result["options"]] == ["steady", "closer", "cooler"]
        # 近期窗口进 prompt（时间正序），消息本身进【TA 的消息】
        user_prompt = http.calls[0]["payload"]["messages"][1]["content"]
        assert "【TA 的消息】周末有空吗" in user_prompt
        assert "【近期对话】" in user_prompt
        assert user_prompt.index("最近聊到周末爬山") < user_prompt.index("周末要加班")

    def test_empty_received_rejected(self, monkeypatch, db):
        with pytest.raises(HistoryQAError, match="请先粘贴"):
            HistoryQAService().rehearse(1, "  ")

    def test_unparsable_model_output_raises(self, monkeypatch, db):
        seed(db, 1, "随便", 1700000100)
        with pytest.raises(HistoryQAError, match="无法解析"):
            rehearse(monkeypatch, db, "在吗", content="模型坏掉了不是 JSON")

    def test_no_context_still_works(self, monkeypatch, db):
        # 空会话：prompt 显式声明无背景，照常出三档
        result, http = rehearse(monkeypatch, db, "在吗")
        assert result["ok"] is True
        assert "没有可用的背景资料" in http.calls[0]["payload"]["messages"][1]["content"]

    def test_remote_model_redacts_all_inputs(self, monkeypatch, db):
        seed(db, 1, "老地方见 13800001111", 1700000100)
        monkeypatch.setattr(hqmod, "_load_question_vector", lambda q: None)

        import app.services.realtime.rag.config as ragcfg
        import app.services.realtime.rag.fact_llm as factllm

        remote_cfg = {"api_base_url": "http://192.0.2.1/v1", "model_id": "m", "api_key": "k"}
        monkeypatch.setattr(factllm, "get_active_model_config", lambda: remote_cfg)
        monkeypatch.setattr(ragcfg, "is_remote_llm_model", lambda cfg: True)

        texts = []

        class _Redactor:
            def redact(self, text, **kw):
                texts.append(text)
                return SimpleNamespace(redacted_text=text.replace("13800001111", "[手机号]"))

        import app.services.realtime.privacy_redactor as pr

        monkeypatch.setattr(pr, "PrivacyRedactor", lambda con: _Redactor())
        http = _FakeHTTP(_VALID_JSON)
        monkeypatch.setattr(hqmod, "post_json_with_retries", http)

        result = HistoryQAService().rehearse(1, "13800001111 在吗")
        assert result["ok"] is True
        # 贴入消息与检索记录都过了脱敏；prompt 里只见脱敏副本
        assert "13800001111 在吗" in texts
        user_prompt = http.calls[0]["payload"]["messages"][1]["content"]
        assert "13800001111" not in user_prompt
        assert "[手机号]" in user_prompt

    def test_redaction_failure_blocks(self, monkeypatch, db):
        seed(db, 1, "随便", 1700000100)
        monkeypatch.setattr(hqmod, "_load_question_vector", lambda q: None)

        import app.services.realtime.rag.config as ragcfg
        import app.services.realtime.rag.fact_llm as factllm

        monkeypatch.setattr(
            factllm,
            "get_active_model_config",
            lambda: {"api_base_url": "http://192.0.2.1/v1", "model_id": "m", "api_key": "k"},
        )
        monkeypatch.setattr(ragcfg, "is_remote_llm_model", lambda cfg: True)

        class _Broken:
            def redact(self, text, **kw):
                raise RuntimeError("redactor broken")

        import app.services.realtime.privacy_redactor as pr

        monkeypatch.setattr(pr, "PrivacyRedactor", lambda con: _Broken())
        monkeypatch.setattr(
            hqmod, "post_json_with_retries",
            lambda **kw: pytest.fail("脱敏失败必须阻断，不得发远程"),
        )
        with pytest.raises(HistoryQAError, match="阻断"):
            HistoryQAService().rehearse(1, "在吗")
