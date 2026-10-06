"""LLM 关系评估服务测试（构造器注入 Fake，不 patch 模块）。"""

import json
import os
import sqlite3
import sys
from datetime import datetime

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import app.services.analysis.relationship_llm_service as rlmod
from app.services.analysis.relationship_llm_service import (
    RelationshipLLMAbsent,
    RelationshipLLMService,
)


class _FakeHTTP:
    """返回预置响应体的假 HTTP 通道。"""

    def __init__(self, content: str):
        self.content = content
        self.calls: list[dict] = []

    def __call__(self, *, url, payload, timeout, log, log_prefix, headers=None, max_retries=3, **kw):
        self.calls.append({"url": url, "payload": payload, "headers": headers})
        return {"choices": [{"message": {"content": self.content}}]}


class _FakeRedactor:
    def __init__(self, fail=False):
        self.fail = fail
        self.calls: list[dict] = []

    def redact(self, text, *, account_wxid, conversation_id, source_table, source_id):
        if self.fail:
            raise RuntimeError("redactor broken")
        self.calls.append({
            "text": text,
            "account_wxid": account_wxid,
            "conversation_id": conversation_id,
            "source_table": source_table,
        })
        from types import SimpleNamespace

        return SimpleNamespace(redacted_text=text.replace("13800001111", "[手机号]"))


def _model(remote_url="http://192.168.1.9:11434/v1"):
    return {"api_base_url": remote_url, "api_key": "", "model_id": "qwen", "name": "测试模型"}


def _ok_content(score=72):
    return json.dumps({
        "score": score,
        "sub_scores": {"communication_quality": 80, "relationship_warmth": 70, "risk_signals": 20},
        "evidence": [{"quote": "老王今晚吃饭不", "month": "2026-09"}],
        "insight": "双方互动频繁且积极。",
    }, ensure_ascii=False)


@pytest.fixture
def db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    # 真实结构：speech_units 只存 message_ids/sender/时间戳，内容回查 messages
    conn.execute("CREATE TABLE speech_units (id INTEGER PRIMARY KEY, conversation_id INT, message_ids TEXT, sender TEXT, first_message_timestamp INT, last_message_timestamp INT, message_count INT)")
    conn.execute("CREATE TABLE interaction_pairs (id INTEGER PRIMARY KEY, conversation_id INT, from_speech_unit_id INT, to_speech_unit_id INT, time_gap INT, from_polarity INT, to_polarity INT)")
    conn.execute("CREATE TABLE messages (id INTEGER PRIMARY KEY, conversation_id INT, is_sender INT, content TEXT, timestamp INT)")
    conn.execute("CREATE TABLE message_preprocessed (message_id INTEGER PRIMARY KEY, cleaned_content TEXT)")
    yield conn
    conn.close()


def seed_pairs(db, n=20, base_ts=None):
    base = base_ts or int(datetime(2026, 9, 1, 10, 0).timestamp())
    for i in range(n):
        # 每个单元两条消息，验证 message_ids 回查与拼接
        f_ids, t_ids = [], []
        for j, text in enumerate((f"对方消息{i}甲", f"对方消息{i}乙：最近怎么样")):
            mid = 4 * i + j + 1
            db.execute(
                "INSERT INTO messages (id, conversation_id, is_sender, content, timestamp) VALUES (?, 1, 0, ?, ?)",
                (mid, text, base + 3600 * i + j * 5),
            )
            db.execute(
                "INSERT INTO message_preprocessed (message_id, cleaned_content) VALUES (?, ?)",
                (mid, text),
            )
            f_ids.append(mid)
        for j, text in enumerate((f"我方回复{i}甲", "挺好的")):
            mid = 4 * i + 2 + j + 1
            db.execute(
                "INSERT INTO messages (id, conversation_id, is_sender, content, timestamp) VALUES (?, 1, 1, ?, ?)",
                (mid, text, base + 3600 * i + 60 + j * 5),
            )
            db.execute(
                "INSERT INTO message_preprocessed (message_id, cleaned_content) VALUES (?, ?)",
                (mid, text),
            )
            t_ids.append(mid)
        db.execute(
            "INSERT INTO speech_units (id, conversation_id, message_ids, sender, first_message_timestamp, last_message_timestamp, message_count) VALUES (?, 1, ?, 'other', ?, ?, 2)",
            (2 * i + 1, ",".join(map(str, f_ids)), base + 3600 * i, base + 3600 * i + 5),
        )
        db.execute(
            "INSERT INTO speech_units (id, conversation_id, message_ids, sender, first_message_timestamp, last_message_timestamp, message_count) VALUES (?, 1, ?, 'user', ?, ?, 2)",
            (2 * i + 2, ",".join(map(str, t_ids)), base + 3600 * i + 60, base + 3600 * i + 65),
        )
        db.execute(
            "INSERT INTO interaction_pairs (id, conversation_id, from_speech_unit_id, to_speech_unit_id, time_gap, from_polarity, to_polarity) VALUES (?, 1, ?, ?, 60, 1, 1)",
            (i + 1, 2 * i + 1, 2 * i + 2),
        )
    db.commit()


@pytest.fixture(autouse=True)
def patch_db(db, monkeypatch):
    monkeypatch.setattr(rlmod, "get_db", lambda: db)


def test_evaluate_parses_score_and_subscores(db):
    seed_pairs(db)
    http = _FakeHTTP(_ok_content())
    svc = RelationshipLLMService(_model(), http=http, is_remote=lambda m: False)
    result = svc.evaluate(1)
    assert result["score"] == 72
    assert result["sub_scores"]["communication_quality"] == 80
    assert result["evidence"][0]["quote"] == "老王今晚吃饭不"
    assert result["meta"]["sampled_pairs"] >= 10


def test_thinking_model_content_parses(db):
    seed_pairs(db)
    content = "<think>推理过程省略 {\"score\": 10}</think>" + _ok_content(65)
    svc = RelationshipLLMService(_model(), http=_FakeHTTP(content), is_remote=lambda m: False)
    result = svc.evaluate(1)
    assert result["score"] == 65


def test_invalid_json_raises_absent(db):
    seed_pairs(db)
    svc = RelationshipLLMService(_model(), http=_FakeHTTP("抱歉我无法输出"), is_remote=lambda m: False)
    with pytest.raises(RelationshipLLMAbsent):
        svc.evaluate(1)


def test_remote_without_redactor_raises_absent(db):
    seed_pairs(db)
    svc = RelationshipLLMService(_model(), http=_FakeHTTP(_ok_content()), is_remote=lambda m: True, redactor_factory=None)
    with pytest.raises(RelationshipLLMAbsent):
        svc.evaluate(1)


def test_remote_redacts_each_message_with_scope_ids(db):
    seed_pairs(db, n=15)
    redactor = _FakeRedactor()
    svc = RelationshipLLMService(
        _model(),
        http=_FakeHTTP(_ok_content()),
        is_remote=lambda m: True,
        redactor_factory=lambda: redactor,
    )
    result = svc.evaluate(1, account_wxid="wxid_a")
    assert result["score"] == 72
    assert len(redactor.calls) >= 20  # 每对两条均脱敏
    assert all(c["source_table"] == "affinity_relationship_llm" for c in redactor.calls)
    assert all(c["account_wxid"] == "wxid_a" for c in redactor.calls)


def test_local_model_skips_redaction(db):
    seed_pairs(db)
    redactor = _FakeRedactor()
    svc = RelationshipLLMService(
        _model(remote_url="http://127.0.0.1:11434/v1"),
        http=_FakeHTTP(_ok_content()),
        is_remote=lambda m: False,
        redactor_factory=lambda: redactor,
    )
    svc.evaluate(1)
    assert redactor.calls == []


def test_sampling_stratifies_by_polarity_and_prefers_recent(db):
    # 40 对 + 12 对近期，验证分层与近期优先
    base_old = int(datetime(2026, 1, 1).timestamp())
    seed_pairs(db, n=40, base_ts=base_old)
    for i in range(12):
        ts = base_old + 86400 * 400 + 3600 * i
        fid, tid = 1000 + 2 * i, 1001 + 2 * i
        mid_f, mid_t = 5000 + 2 * i, 5001 + 2 * i
        db.execute(
            "INSERT INTO messages (id, conversation_id, is_sender, content, timestamp) VALUES (?, 1, 0, ?, ?)",
            (mid_f, f"近期样本{i}", ts),
        )
        db.execute(
            "INSERT INTO messages (id, conversation_id, is_sender, content, timestamp) VALUES (?, 1, 1, ?, ?)",
            (mid_t, f"近期回复{i}", ts + 30),
        )
        db.execute(
            "INSERT INTO speech_units (id, conversation_id, message_ids, sender, first_message_timestamp, last_message_timestamp, message_count) VALUES (?, 1, ?, 'other', ?, ?, 1)",
            (fid, str(mid_f), ts, ts),
        )
        db.execute(
            "INSERT INTO speech_units (id, conversation_id, message_ids, sender, first_message_timestamp, last_message_timestamp, message_count) VALUES (?, 1, ?, 'user', ?, ?, 1)",
            (tid, str(mid_t), ts + 30, ts + 30),
        )
        db.execute(
            "INSERT INTO interaction_pairs (id, conversation_id, from_speech_unit_id, to_speech_unit_id, time_gap, from_polarity, to_polarity) VALUES (?, 1, ?, ?, 30, 1, 1)",
            (500 + i, fid, tid),
        )
    db.commit()
    svc = RelationshipLLMService(_model(), http=_FakeHTTP(_ok_content()), is_remote=lambda m: False)
    pairs = svc._sample_interaction_pairs(1)
    assert len(pairs) <= 40
    months = {p["month"] for p in pairs}
    # 分层：旧桶（2026 年初）保有样本，新桶（近期）也在
    assert any(m.startswith("2026-0") for m in months)
    assert "2027-02" in months


def test_prompt_includes_relationship_context_labels(db):
    seed_pairs(db)
    http = _FakeHTTP(_ok_content())
    svc = RelationshipLLMService(_model(), http=http, is_remote=lambda m: False)
    svc.evaluate(1, context={"relationship_type": "朋友", "interaction_duration": "1-3年", "communication_style": "轻松"})
    user_content = http.calls[0]["payload"]["messages"][1]["content"]
    assert "关系类型：朋友" in user_content
    assert "认识时长：1-3年" in user_content
    assert "沟通风格：轻松" in user_content


def test_score_clamped_and_evidence_capped(db):
    seed_pairs(db)
    content = json.dumps({
        "score": 250,
        "sub_scores": {"communication_quality": -5, "relationship_warmth": 999, "risk_signals": 40},
        "evidence": [{"quote": f"证据{i}", "month": "2026-09"} for i in range(9)],
        "insight": "x",
    }, ensure_ascii=False)
    svc = RelationshipLLMService(_model(), http=_FakeHTTP(content), is_remote=lambda m: False)
    result = svc.evaluate(1)
    assert result["score"] == 100
    assert result["sub_scores"]["communication_quality"] == 0
    assert result["sub_scores"]["relationship_warmth"] == 100
    assert len(result["evidence"]) == 5


def test_insufficient_pairs_raises_absent(db):
    seed_pairs(db, n=5)
    svc = RelationshipLLMService(_model(), http=_FakeHTTP(_ok_content()), is_remote=lambda m: False)
    with pytest.raises(RelationshipLLMAbsent):
        svc.evaluate(1)


def test_input_char_budget_drops_oldest_pairs(db):
    # 单元文本超长，触发预算裁剪：保留的是较新的对
    base = int(datetime(2026, 9, 30).timestamp())
    for i in range(60):
        ts = base + 3600 * i
        mid_f, mid_t = 4 * i + 1, 4 * i + 2
        db.execute(
            "INSERT INTO messages (id, conversation_id, is_sender, content, timestamp) VALUES (?, 1, 0, ?, ?)",
            (mid_f, f"很长的消息内容{'x' * 200}编号{i}", ts),
        )
        db.execute(
            "INSERT INTO messages (id, conversation_id, is_sender, content, timestamp) VALUES (?, 1, 1, ?, ?)",
            (mid_t, f"很长的回复{'y' * 200}编号{i}", ts + 30),
        )
        db.execute(
            "INSERT INTO speech_units (id, conversation_id, message_ids, sender, first_message_timestamp, last_message_timestamp, message_count) VALUES (?, 1, ?, 'other', ?, ?, 1)",
            (2 * i + 1, str(mid_f), ts, ts),
        )
        db.execute(
            "INSERT INTO speech_units (id, conversation_id, message_ids, sender, first_message_timestamp, last_message_timestamp, message_count) VALUES (?, 1, ?, 'user', ?, ?, 1)",
            (2 * i + 2, str(mid_t), ts + 30, ts + 30),
        )
        db.execute(
            "INSERT INTO interaction_pairs (id, conversation_id, from_speech_unit_id, to_speech_unit_id, time_gap, from_polarity, to_polarity) VALUES (?, 1, ?, ?, 30, 0, 0)",
            (i + 1, 2 * i + 1, 2 * i + 2),
        )
    db.commit()
    svc = RelationshipLLMService(_model(), http=_FakeHTTP(_ok_content()), is_remote=lambda m: False)
    pairs = svc._sample_interaction_pairs(1)
    total = sum(len(p["from_text"]) + len(p["to_text"]) for p in pairs)
    assert total <= rlmod.MAX_TOTAL_INPUT_CHARS
    assert len(pairs) >= rlmod.MIN_PAIRS
