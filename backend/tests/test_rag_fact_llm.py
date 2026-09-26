"""P1.2 LLM structured fact extraction tests: adapter, budget, quality gate."""

import json
import os
import sqlite3
import sys


sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.realtime.rag.fact_llm import (
    FACT_EXTRACTION_SYSTEM_PROMPT,
    FACT_FUSION_SYSTEM_PROMPT,
    FactRedactionUnavailable,
    LLMFactExtractorAdapter,
)
from app.services.realtime.rag.fact_quality import fact_quality_reason
from app.services.realtime.rag.indexer import RagIndexer
from app.services.realtime.rag.store import RagStore


def _segment(now, messages_spec, start_offset=600):
    from app.services.realtime.rag.segmenter import RagSegment

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
        "app.services.realtime.rag.fact_llm.post_json_with_retries", http
    )
    monkeypatch.setattr(
        "app.services.realtime.rag.fact_llm.is_remote_llm_model",
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

    from app.services.realtime.rag.fact_extractor import StructuredFactExtractor

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

    from app.services.realtime.rag.fact_extractor import StructuredFactExtractor

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

    from app.services.realtime.rag.fact_extractor import StructuredFactExtractor

    indexer = RagIndexer(
        store=store,
        embedding_service=_NoopEmbedding(),
        structured_fact_extractor=StructuredFactExtractor(good_llm),
    )
    monkeypatch.setattr(
        "app.services.realtime.rag.indexer.load_rag_settings",
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

    from app.services.realtime.rag.fact_extractor import StructuredFactExtractor

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


def test_zero_fact_segment_advances_progress(monkeypatch):
    """T5：抽取成功但零事实也要推进段级进度（不再被每轮重抽）。"""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    store = RagStore(conn)
    store.upsert_status("wxid_a", 1, status="ready")

    from app.services.realtime.rag.fact_extractor import StructuredFactExtractor

    indexer = RagIndexer(
        store=store,
        embedding_service=_NoopEmbedding(),
        structured_fact_extractor=StructuredFactExtractor(lambda prompt: {"facts": []}),
    )
    now = 1790000000
    segment = _segment(
        now,
        [(1, 0, "嗯嗯"), (2, 1, "好滴"), (3, 0, "哈哈哈哈"), (4, 1, "666")],
    )
    indexer._extract_structured_shadow_facts(
        account_wxid="wxid_a", conversation_id=1, segment=segment
    )
    status = store.get_status("wxid_a", 1)
    assert status["fact_extract_watermark_ts"] == segment.end_ts
    assert status["fact_extract_prompt_version"] == indexer.FACT_EXTRACT_PROMPT_VERSION


def test_failed_segment_freezes_watermark_for_round(monkeypatch):
    """T5：段失败后冻结水位，后续段成功不得越过失败段（下轮重试）。"""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    store = RagStore(conn)
    store.upsert_status("wxid_a", 1, status="ready")
    state = {"fail": True}

    def flaky_llm(prompt):
        payload = json.loads(prompt)
        if state["fail"]:
            raise ValueError("network down")
        return {
            "facts": [
                {
                    "subject": "对方",
                    "kind": "preference",
                    "content": "对方对虾过敏",
                    "confidence": 0.8,
                    "evidence_message_ids": [5],
                }
            ]
        }

    from app.services.realtime.rag.fact_extractor import StructuredFactExtractor

    indexer = RagIndexer(
        store=store,
        embedding_service=_NoopEmbedding(),
        structured_fact_extractor=StructuredFactExtractor(flaky_llm),
    )
    now = 1790000000
    seg1 = _segment(
        now,
        [(1, 0, "我对虾过敏，千万别点虾"), (2, 1, "好"), (3, 0, "周五见"), (4, 1, "周五见")],
    )
    seg2 = _segment(
        now + 100000,
        [(5, 0, "我对虾过敏，千万别点虾"), (6, 1, "好"), (7, 0, "周五见"), (8, 1, "周五见")],
        start_offset=100060,
    )
    indexer._extract_structured_shadow_facts(account_wxid="wxid_a", conversation_id=1, segment=seg1)
    state["fail"] = False
    indexer._extract_structured_shadow_facts(account_wxid="wxid_a", conversation_id=1, segment=seg2)

    # 失败段之后：水位不推进（seg2 虽成功也不越过 seg1）
    status = store.get_status("wxid_a", 1)
    assert status["fact_extract_watermark_ts"] is None
    # 但 seg2 的事实照常入库（不因冻结而丢弃）
    rows = conn.execute("SELECT content FROM rag_facts").fetchall()
    assert len(rows) == 1 and rows[0]["content"] == "对方对虾过敏"


def test_prompt_version_change_invalidates_watermark():
    """T5：prompt 版本变化时旧水位失效，全量重抽。"""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    store = RagStore(conn)
    store.upsert_status("wxid_a", 1, status="ready")
    store.set_fact_extract_progress(
        "wxid_a", 1, watermark_ts=1790000000, prompt_version="p1.2"
    )
    indexer = RagIndexer(store=store, embedding_service=_NoopEmbedding())
    indexer._init_llm_extract_progress("wxid_a", 1)
    assert indexer._llm_extract_watermark_ts is None  # 旧版本水位失效

    store.set_fact_extract_progress(
        "wxid_a", 1, watermark_ts=1790000000, prompt_version=indexer.FACT_EXTRACT_PROMPT_VERSION
    )
    indexer._init_llm_extract_progress("wxid_a", 1)
    assert indexer._llm_extract_watermark_ts == 1790000000  # 同版本水位保留


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


def test_remote_model_without_redactor_blocks_segment(monkeypatch):
    """T1 红线：远程模型脱敏器不可用时阻断整段，绝不降级发原文。"""
    payload = json.dumps(
        {
            "messages": [
                {"id": 1, "is_sender": 0, "content": "我的手机号是13800000000"},
                {"id": 2, "is_sender": 1, "content": "收到"},
            ]
        }
    )
    http = _FakeHTTP('{"facts": []}')

    # factory 缺失
    monkeypatch.setattr(
        "app.services.realtime.rag.fact_llm.post_json_with_retries", http
    )
    monkeypatch.setattr(
        "app.services.realtime.rag.fact_llm.is_remote_llm_model", lambda model: True
    )
    model = {"model_id": "m", "api_base_url": "https://api.example.com/v1"}
    adapter = LLMFactExtractorAdapter(model, redactor_factory=None)
    try:
        adapter(payload)
        raise AssertionError("expected FactRedactionUnavailable")
    except FactRedactionUnavailable:
        pass

    # factory 抛异常
    adapter = LLMFactExtractorAdapter(model, redactor_factory=lambda: (_ for _ in ()).throw(ValueError("db locked")))
    try:
        adapter(payload)
        raise AssertionError("expected FactRedactionUnavailable")
    except FactRedactionUnavailable:
        pass

    # factory 返回 None
    adapter = LLMFactExtractorAdapter(model, redactor_factory=lambda: None)
    try:
        adapter(payload)
        raise AssertionError("expected FactRedactionUnavailable")
    except FactRedactionUnavailable:
        pass

    # 三种情况都不发任何 HTTP 请求
    assert http.captured is None


def test_adapter_routes_fusion_payload_to_fusion_prompt(monkeypatch):
    """T2：融合任务（new_fact/active_candidates）走 decisions 协议。"""
    payload = json.dumps(
        {
            "task": "maintain_atomic_contact_facts",
            "account_wxid": "wxid_a",
            "conversation_id": 1,
            "new_fact": {
                "subject": "对方",
                "kind": "preference",
                "content": "对方以前不吃香菜，现在因为一起吃过几次改观了，开始喜欢吃了",
                "confidence": 0.8,
            },
            "active_candidates": [
                {
                    "fact_id": 501,
                    "content": "对方不喜欢吃香菜",
                    "confidence": 0.7,
                    "evidence_message_ids": [11],
                },
                {
                    "fact_id": 502,
                    "content": "对方在准备考研",
                    "confidence": 0.75,
                    "evidence_message_ids": [12],
                },
            ],
        },
        ensure_ascii=False,
    )
    llm_output = json.dumps(
        {
            "decisions": [
                {"fact_id": 501, "action": "UPDATE", "reason": "同一食物偏好的立场演变"},
                {"fact_id": 502, "action": "ADD", "reason": "主题无关"},
            ]
        },
        ensure_ascii=False,
    )
    http = _FakeHTTP(llm_output)
    adapter = _adapter(monkeypatch, http)

    result = adapter(payload)

    sent = http.captured["payload"]["messages"]
    assert "记忆事实维护器" in sent[0]["content"]
    assert sent[0]["content"] == FACT_FUSION_SYSTEM_PROMPT
    assert "改观" in sent[1]["content"] and "[501] 对方不喜欢吃香菜" in sent[1]["content"]
    assert result["decisions"][0]["action"] == "UPDATE"
    assert result["decisions"][0]["fact_id"] == 501


def test_fusion_response_without_decisions_raises(monkeypatch):
    payload = json.dumps(
        {
            "task": "maintain_atomic_contact_facts",
            "new_fact": {"subject": "对方", "kind": "preference", "content": "对方喜欢徒步"},
            "active_candidates": [{"fact_id": 9, "content": "对方喜欢爬山", "confidence": 0.7}],
        },
        ensure_ascii=False,
    )
    # 抽取协议的响应（facts）喂给融合任务必须报错，由上层安全回退 ADD
    http = _FakeHTTP('{"facts": []}')
    adapter = _adapter(monkeypatch, http)
    try:
        adapter(payload)
        raise AssertionError("expected ValueError")
    except ValueError as exc:
        assert "decisions" in str(exc)


def test_json_candidates_prefers_after_think_tail():
    """思考模型（Qwen3.5-9B 实测形态）：思考段回显模板 JSON，真答案在 </think> 之后。"""
    from app.services.realtime.rag.fact_llm import LLMFactExtractorAdapter

    probe = (
        "我们需要分析……只输出JSON对象 {\"facts\":[{\"content\":\"...\",\"kind\":\"...\"}]} "
        "对话里 B 只是提醒……因此无事实。输出 {\"facts\":[]}。\n</think>\n\n{\"facts\":[]}"
    )
    candidates = LLMFactExtractorAdapter._json_candidates(probe)
    assert candidates, "应至少解析出一个候选"
    assert candidates[-1] == "{\"facts\":[]}", f"末尾真答案应被选中: {candidates}"


def test_json_candidates_extra_data_salvage():
    """原「首个 { 到末个 }」跨度在多对象场景必然 Extra data——现应逐对象可解析。"""
    from app.services.realtime.rag.fact_llm import LLMFactExtractorAdapter

    text = '前言 {"facts":[{"content":"示例"}]} 中间说明 {"facts":[]} 结尾废话}'
    candidates = LLMFactExtractorAdapter._json_candidates(text)
    assert '{"facts":[]}' in candidates
    # 旧实现返回 text[first{:last}] 必然 json 失败；新 _json_candidate 返回可解析末位
    assert LLMFactExtractorAdapter._json_candidate(text) == '{"facts":[]}'


def test_json_candidates_no_json_returns_empty():
    from app.services.realtime.rag.fact_llm import LLMFactExtractorAdapter
    assert LLMFactExtractorAdapter._json_candidates("没有任何对象") == []
