"""P1.2 LLM structured fact extraction tests: adapter, budget, quality gate."""

import json
import os
import sqlite3
import sys


sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.realtime.rag_fact_llm import FACT_EXTRACTION_SYSTEM_PROMPT, LLMFactExtractorAdapter
from app.services.realtime.rag_fact_quality import fact_quality_reason
from app.services.realtime.rag_indexer import RagIndexer
from app.services.realtime.rag_store import RagStore


def _segment(now, messages_spec, start_offset=600):
    from app.services.realtime.rag_segmenter import RagSegment

    messages = [
        {
            "id": mid,
            "is_sender": sender,
            "content": content,
            "timestamp": now - start_offset + idx * 60,
            "message_type": 1,
        }
        for idx, (mid, sender, content) in enumerate(messages_spec)
    ]
    return RagSegment(
        segment_id="s1",
        start_ts=messages[0]["timestamp"],
        end_ts=messages[-1]["timestamp"],
        messages=messages,
        message_ids=[m["id"] for m in messages],
        topics=[],
        entities=[],
        time_label="近期",
    )


class _FakeHTTP:
    def __init__(self, response_content):
        self.response_content = response_content
        self.captured = None

    def __call__(self, **kwargs):
        self.captured = kwargs
        return {
            "choices": [
                {"message": {"content": self.response_content}}
            ]
        }


def _adapter(monkeypatch, http, *, remote=False, redactor=None):
    monkeypatch.setattr(
        "app.services.realtime.rag_fact_llm.post_json_with_retries", http
    )
    monkeypatch.setattr(
        "app.services.realtime.rag_fact_llm.is_remote_llm_model",
        lambda model: remote,
    )
    model = {
        "model_id": "test-model",
        "api_base_url": "http://127.0.0.1:1234/v1",
        "api_key": "sk-test",
    }
    return LLMFactExtractorAdapter(
        model, redactor_factory=(lambda: redactor) if redactor else None
    )


def test_adapter_builds_prompt_and_filters_hallucinated_evidence(monkeypatch):
    now = 1790000000
    payload = json.dumps(
        {
            "task": "extract_atomic_contact_facts",
            "account_wxid": "wxid_a",
            "conversation_id": 1,
            "messages": [
                {"id": 1, "is_sender": 0, "content": "我对虾过敏，千万别点虾"},
                {"id": 2, "is_sender": 1, "content": "好，那我们吃火锅"},
                {"id": 3, "is_sender": 0, "content": "周五见"},
                {"id": 4, "is_sender": 1, "content": "周五见，老地方"},
            ],
        },
        ensure_ascii=False,
    )
    llm_output = json.dumps(
        {
            "facts": [
                {
                    "subject": "对方",
                    "kind": "preference",
                    "content": "对方对虾过敏",
                    "confidence": 0.9,
                    "sensitivity": "normal",
                    "evidence_message_ids": [1, 999],
                }
            ]
        },
        ensure_ascii=False,
    )
    http = _FakeHTTP(llm_output)
    adapter = _adapter(monkeypatch, http)

    result = adapter(payload)

    # prompt 契约：system 指令 + user 携带 [id] 角色: 内容
    sent = http.captured["payload"]["messages"]
    assert sent[0]["role"] == "system" and "记忆抽取器" in sent[0]["content"]
    assert "[1] 对方: 我对虾过敏" in sent[1]["content"]
    # 幻觉 evidence id（999 不在消息里）被过滤
    assert result["facts"][0]["evidence_message_ids"] == [1]


def test_adapter_redacts_for_remote_model_and_skips_failed_lines(monkeypatch):
    class _Redactor:
        def __init__(self):
            self.calls = 0

        def redact(self, text, **kwargs):
            self.calls += 1
            if "住址" in text:
                raise ValueError("redaction blew up")
            class _R:  # noqa: N801
                redacted_text = "[已脱敏]" + text
            return _R()

    redactor = _Redactor()
    payload = json.dumps(
        {
            "messages": [
                {"id": 1, "is_sender": 0, "content": "我说了我的住址在某某小区"},
                {"id": 2, "is_sender": 1, "content": "收到"},
            ]
        }
    )
    http = _FakeHTTP('{"facts": []}')
    adapter = _adapter(monkeypatch, http, remote=True, redactor=redactor)

    adapter(payload)

    user_text = http.captured["payload"]["messages"][1]["content"]
    # 脱敏成功的内容带标记；脱敏失败的行不发送
    assert "[已脱敏]" in user_text
    assert "某某小区" not in user_text
    assert redactor.calls >= 1


def test_adapter_parses_reasoning_fallback_json(monkeypatch):
    llm_output = '前置推理文字 {"facts": [{"subject": "我", "kind": "plan", "content": "我们约了周五见面", "confidence": 0.8, "evidence_message_ids": [3]}]} 后缀'
    http = _FakeHTTP(llm_output)
    # content 为空时 adapter 应从 reasoning 提取——直接把 JSON 塞 content 验证候选提取
    adapter = _adapter(monkeypatch, http)
    result = adapter(json.dumps({"messages": [{"id": 3, "is_sender": 0, "content": "周五见"}]}))
    assert result["facts"][0]["content"] == "我们约了周五见面"


def test_quality_gate_relaxed_mode_for_llm_facts():
    # LLM 陈述句无信号词也应通过（kind 由模型判定）
    assert fact_quality_reason("plan", "我们约了周五在老地方吃火锅", require_kind_signal=False) is None
    # 基础项仍然生效
    assert fact_quality_reason("plan", "好的好的", require_kind_signal=False) in {"generic_turn", "acknowledgement"}
    assert fact_quality_reason("plan", "对方手机号是多少", require_kind_signal=False) == "sensitive_quarantine"
    assert fact_quality_reason("plan", "哪天来着", require_kind_signal=False) == "question_turn"
    # 严格模式（原型路径）仍要求信号词
    assert fact_quality_reason("plan", "我们约了周五在老地方吃火锅") == "kind_signal_missing"


def test_indexer_budget_and_short_segment_skip(monkeypatch):
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    store = RagStore(conn)
    calls = []

    def fake_llm(prompt):
        calls.append(prompt)
        return {"facts": []}

    from app.services.realtime.rag_fact_extractor import StructuredFactExtractor

    indexer = RagIndexer(
        store=store,
        embedding_service=_NoopEmbedding(),
        structured_fact_extractor=StructuredFactExtractor(fake_llm),
    )
    now = 1790000000
    long_segment = _segment(
        now,
        [
            (1, 0, "我对虾过敏，千万别点虾"),
            (2, 1, "好，那我们吃火锅"),
            (3, 0, "周五见"),
            (4, 1, "周五见，老地方"),
        ],
    )
    short_segment = _segment(now, [(5, 0, "嗯"), (6, 1, "好的")], start_offset=100)

    indexer._extract_structured_shadow_facts(
        account_wxid="wxid_a", conversation_id=1, segment=short_segment
    )
    assert len(calls) == 0  # 短段跳过

    indexer._llm_extract_segments_used = indexer.LLM_EXTRACT_SEGMENT_BUDGET
    indexer._extract_structured_shadow_facts(
        account_wxid="wxid_a", conversation_id=1, segment=long_segment
    )
    assert len(calls) == 0  # 预算耗尽跳过

    indexer._llm_extract_segments_used = 0
    indexer._extract_structured_shadow_facts(
        account_wxid="wxid_a", conversation_id=1, segment=long_segment
    )
    assert len(calls) == 1


def test_indexer_consecutive_failure_aborts_round(monkeypatch):
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    store = RagStore(conn)

    def broken_llm(prompt):
        raise ValueError("network down")

    from app.services.realtime.rag_fact_extractor import StructuredFactExtractor

    indexer = RagIndexer(
        store=store,
        embedding_service=_NoopEmbedding(),
        structured_fact_extractor=StructuredFactExtractor(broken_llm),
    )
    now = 1790000000
    segment = _segment(
        now,
        [(1, 0, "我对虾过敏，千万别点虾"), (2, 1, "好"), (3, 0, "周五见"), (4, 1, "周五见")],
    )
    for _ in range(3):
        indexer._extract_structured_shadow_facts(
            account_wxid="wxid_a", conversation_id=1, segment=segment
        )
    assert indexer._llm_extract_consecutive_failures == 3
    # 第 4 段不再调用（直接中止）
    try:
        indexer._extract_structured_shadow_facts(
            account_wxid="wxid_a", conversation_id=1, segment=segment
        )
    except Exception:
        pass
    assert indexer._llm_extract_segments_used == 3


def test_llm_facts_written_as_llm_shadow_through_quality_gate(monkeypatch):
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    store = RagStore(conn)

    def good_llm(prompt):
        return {
            "facts": [
                {
                    "subject": "对方",
                    "kind": "preference",
                    "content": "对方对虾过敏",
                    "confidence": 0.88,
                    "sensitivity": "normal",
                    "evidence_message_ids": [1],
                },
                # 碎片应被宽松质量门拦截
                {
                    "subject": "对方",
                    "kind": "event",
                    "content": "好的好的",
                    "confidence": 0.9,
                    "evidence_message_ids": [2],
                },
            ]
        }

    from app.services.realtime.rag_fact_extractor import StructuredFactExtractor

    indexer = RagIndexer(
        store=store,
        embedding_service=_NoopEmbedding(),
        structured_fact_extractor=StructuredFactExtractor(good_llm),
    )
    monkeypatch.setattr(
        "app.services.realtime.rag_indexer.load_rag_settings",
        lambda: {"rag_fact_shadow_enabled": False},
    )
    now = 1790000000
    segment = _segment(
        now,
        [(1, 0, "我对虾过敏，千万别点虾"), (2, 1, "好的好的"), (3, 0, "周五见"), (4, 1, "周五见")],
    )
    indexer._extract_structured_shadow_facts(
        account_wxid="wxid_a", conversation_id=1, segment=segment
    )
    rows = conn.execute(
        "SELECT kind, content, summary_method FROM rag_facts"
    ).fetchall()
    assert len(rows) == 1
    assert rows[0]["content"] == "对方对虾过敏"
    assert rows[0]["summary_method"] == "llm_shadow"


class _NoopEmbedding:
    def embed_texts(self, texts):
        return [[0.0] * 768 for _ in texts]


def test_watermark_skips_already_extracted_range(monkeypatch):
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    store = RagStore(conn)
    calls = []

    def fake_llm(prompt):
        calls.append(json.loads(prompt)["messages"])
        return {"facts": []}

    from app.services.realtime.rag_fact_extractor import StructuredFactExtractor

    indexer = RagIndexer(
        store=store,
        embedding_service=_NoopEmbedding(),
        structured_fact_extractor=StructuredFactExtractor(fake_llm),
    )
    now = 1790000000
    early = _segment(
        now - 100000,
        [(1, 0, "我对虾过敏，千万别点虾"), (2, 1, "好"), (3, 0, "周五见"), (4, 1, "周五见")],
        start_offset=100060,
    )
    late = _segment(
        now,
        [(5, 0, "我最近在学吉他，指弹"), (6, 1, "酷"), (7, 0, "下周演出来看看"), (8, 1, "好的")],
    )

    # 水位之前：跳过；之后：抽取
    indexer._llm_extract_watermark_ts = now - 50000
    indexer._extract_structured_shadow_facts(
        account_wxid="wxid_a", conversation_id=1, segment=early
    )
    assert len(calls) == 0
    indexer._extract_structured_shadow_facts(
        account_wxid="wxid_a", conversation_id=1, segment=late
    )
    assert len(calls) == 1


def test_context_messages_rendered_but_not_evidence(monkeypatch):
    payload = json.dumps(
        {
            "messages": [
                {"id": 10, "is_sender": 0, "content": "就买一下下嘛"},
                {"id": 11, "is_sender": 1, "content": "哪个皮肤"},
                {"id": 12, "is_sender": 0, "content": "就上次说的那个限定"},
                {"id": 13, "is_sender": 1, "content": "行吧"},
            ],
            "context_messages": [
                {"id": 9, "is_sender": 1, "content": "这个游戏的皮肤好贵"},
            ],
        }
    )
    llm_output = json.dumps(
        {"facts": [{"subject": "对方", "kind": "preference", "content": "对方想要之前讨论过的游戏皮肤",
                    "confidence": 0.85, "evidence_message_ids": [10, 9]}]},
        ensure_ascii=False,
    )
    http = _FakeHTTP(llm_output)
    adapter = _adapter(monkeypatch, http)

    result = adapter(payload)

    user_text = http.captured["payload"]["messages"][1]["content"]
    # 前段上下文出现且带"勿从中抽取"标注
    assert "上一段结尾" in user_text and "[9]" in user_text and "勿从中抽取" in user_text
    # 上下文消息 ID 不得成为 evidence（9 不在本段 messages 里）
    assert result["facts"][0]["evidence_message_ids"] == [10]
