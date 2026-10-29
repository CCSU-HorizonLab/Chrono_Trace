"""画像双 profiler 出网脱敏（第五轮抽查 #1）。

ContactProfiler/SelfProfiler 的 prompt 携带聊天原文与联系人姓名，
此前直发远程 LLM 无脱敏——全仓其余 9 个 LLM 消费方均有红线，唯画像
双 profiler 漏网。修复口径与 feedback_rule_extractor 一致：
is_remote → PrivacyRedactor 全量脱敏 → 失败即 raise 阻断，本地豁免。
"""
import json
import sqlite3
import sys
import time

sys.path.insert(0, __file__.rsplit("/backend/tests/", 1)[0] + "/backend")

from app.services.realtime.contact_profiler import ContactProfiler
from app.services.realtime.self_profiler import SelfProfiler


def _build_model_db(base_url="https://api.deepseek.com/v1") -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE llm_models (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL, provider TEXT NOT NULL,
            model_id TEXT NOT NULL, api_base_url TEXT NOT NULL,
            api_key TEXT, is_active INTEGER DEFAULT 0,
            max_tokens INTEGER DEFAULT 512, temperature REAL DEFAULT 0.7,
            created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL
        )
        """
    )
    now = int(time.time())
    conn.execute(
        "INSERT INTO llm_models (name, provider, model_id, api_base_url, api_key,"
        " is_active, max_tokens, temperature, created_at, updated_at)"
        " VALUES ('m', 'deepseek', 'deepseek-chat', ?, 'token', 1, 1024, 0.3, ?, ?)",
        (base_url, now, now),
    )
    conn.commit()
    return conn


class _DummyResponse:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return json.dumps(
            {
                "choices": [{"message": {"content": json.dumps({
                    "personality_tags": ["安静"],
                    "chat_style": "短句",
                    "relationship_note": "稳",
                    "typing_style": "short",
                    "frequent_catchphrases": ["ok"],
                    "sentence_patterns": ["[x] ok"],
                    "shared_memories": ["self"],
                    "attitude_and_role": "calm",
                    "do_and_donts": "keep it short",
                })}}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            }
        ).encode("utf-8")


def _capture_post(monkeypatch, captured):
    def fake_pooled_request(method, url, *, data, headers, timeout):
        captured.setdefault("payloads", []).append(json.loads(data.decode("utf-8")))
        return _DummyResponse().read(), 200, {}

    monkeypatch.setattr("app.services.realtime.llm_http._pooled_request", fake_pooled_request)


def test_contact_profiler_redacts_prompt_for_remote_model(monkeypatch):
    conn = _build_model_db()
    profiler = ContactProfiler(timeout=5)
    captured: dict = {}
    _capture_post(monkeypatch, captured)
    monkeypatch.setattr("app.db.connection.get_db", lambda: conn)

    prompt = "对方：我手机号13812345678，到了联系我"
    profiler._call_llm(prompt, account_wxid="wxid_test")

    sent = captured["payloads"][0]["messages"][1]["content"]
    assert "13812345678" not in sent
    assert "[PHONE_" in sent


def test_self_profiler_redacts_prompt_for_remote_model(monkeypatch):
    conn = _build_model_db()
    profiler = SelfProfiler(timeout=5)
    captured: dict = {}
    _capture_post(monkeypatch, captured)
    monkeypatch.setattr("app.db.connection.get_db", lambda: conn)

    prompt = "对方：我手机号13812345678，到了联系我"
    profiler._call_llm(prompt, account_wxid="wxid_test")

    sent = captured["payloads"][0]["messages"][1]["content"]
    assert "13812345678" not in sent
    assert "[PHONE_" in sent


def test_profiler_blocks_when_redaction_fails(monkeypatch):
    """脱敏失败必须阻断出网，不得降级发原文。"""
    conn = _build_model_db()
    captured: dict = {}
    _capture_post(monkeypatch, captured)
    monkeypatch.setattr("app.db.connection.get_db", lambda: conn)

    def broken_redact(self, *args, **kwargs):
        raise RuntimeError("redactor exploded")

    monkeypatch.setattr(
        "app.services.realtime.privacy_redactor.PrivacyRedactor.redact", broken_redact)

    for profiler in (ContactProfiler(timeout=5), SelfProfiler(timeout=5)):
        try:
            profiler._call_llm("对方：我手机号13812345678", account_wxid="wxid_test")
        except RuntimeError as exc:
            assert "红线阻断" in str(exc)
        else:
            raise AssertionError("Expected RuntimeError（脱敏失败必须阻断）")

    assert captured.get("payloads", []) == [], "脱敏失败后不得有任何出网请求"


def test_profiler_local_model_bypasses_redaction(monkeypatch):
    conn = _build_model_db(base_url="http://127.0.0.1:11434/v1")
    profiler = SelfProfiler(timeout=5)
    captured: dict = {}
    _capture_post(monkeypatch, captured)
    monkeypatch.setattr("app.db.connection.get_db", lambda: conn)

    prompt = "对方：我手机号13812345678"
    profiler._call_llm(prompt, account_wxid="wxid_test")

    sent = captured["payloads"][0]["messages"][1]["content"]
    assert "13812345678" in sent, "本地模型豁免脱敏，原样发送"
