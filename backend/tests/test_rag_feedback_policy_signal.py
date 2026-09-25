"""P2.1 反馈策略信号影子层测试：fact feedback / suggestion outcome / attribution。"""

import json
import os
import sqlite3
import sys
import time


sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.realtime.rag_relationship_policy import refresh_after_fact_feedback
from app.services.realtime.rag_store import RagStore
from app.services.realtime.suggestion_observer import record_observation


def _store():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    return conn, RagStore(conn)


def _seed_fact(store, *, content="对方不喜欢被追问情绪", kind="relationship_boundary", confidence=0.7):
    return store.upsert_fact(
        account_wxid="wxid_a",
        conversation_id=1,
        subject="对方",
        kind=kind,
        content=content,
        confidence=confidence,
        as_of=1789900000,
        evidence_message_ids=[11],
        summary_method="llm_shadow",
    )


def test_fact_feedback_writes_policy_signal(monkeypatch):
    """不准确反馈 → 刷新策略 + 信号行记录受影响策略与结果。"""
    conn, store = _store()
    fact_id = _seed_fact(store)
    store.upsert_relationship_state(
        account_wxid="wxid_a", conversation_id=1,
        stage="高频互动/对方更主动", closeness_band="high",
        initiative_pattern="对方更主动", evidence_hash="hash-1",
        evidence_fact_ids=[fact_id], confidence=0.7,
    )
    conn.commit()
    monkeypatch.setattr(
        "app.services.realtime.rag_relationship_policy.load_rag_settings",
        lambda: {"rag_relationship_policy_shadow_enabled": True},
    )

    refresh_after_fact_feedback(store, fact_id, action="inaccurate")
    signals = store.list_feedback_policy_signals("wxid_a", 1)
    assert len(signals) == 1
    signal = signals[0]
    assert signal["fact_id"] == fact_id
    assert signal["action"] == "inaccurate"
    assert signal["signal_kind"] == "fact_feedback"
    # state id 在受影响策略列表（反馈前引用了该事实）
    assert json.loads(signal["affected_policy_ids_json"])
    assert signal["outcome"] in {"refreshed", "no_change"}


def test_unreferenced_fact_feedback_records_noop(monkeypatch):
    """反馈未引用事实：信号仍记录（outcome=noop 路径），策略不动。"""
    conn, store = _store()
    fact_id = _seed_fact(store)
    monkeypatch.setattr(
        "app.services.realtime.rag_relationship_policy.load_rag_settings",
        lambda: {"rag_relationship_policy_shadow_enabled": False},
    )
    refresh_after_fact_feedback(store, fact_id, action="forget")
    signals = store.list_feedback_policy_signals("wxid_a", 1)
    assert len(signals) == 1
    assert json.loads(signals[0]["affected_policy_ids_json"]) == []
    assert signals[0]["outcome"] == "disabled"  # 开关关闭的 skipped 原因如实记录


def test_suggestion_outcome_signal_binds_retrieval_log():
    """adopted/rewritten 事件 → 信号绑定该建议检索日志的策略/注入项。"""
    conn, store = _store()
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS realtime_suggestions (
            id INTEGER PRIMARY KEY, account_wxid TEXT, batch_id TEXT,
            display_name TEXT, trigger_type TEXT, created_at INTEGER
        )
        """
    )
    conn.execute(
        "INSERT INTO realtime_suggestions (id, account_wxid, batch_id, display_name, trigger_type, created_at)"
        " VALUES (5, 'wxid_a', 'b1', '昕', 'ambient', ?)",
        (int(time.time()),),
    )
    log_id = store.insert_retrieval_log(
        account_wxid="wxid_a", conversation_id=1, query_text="[m]",
        document_ids=[], retrieval_scores={}, index_status="ready",
        elapsed_ms=3, rag_enabled=True, rag_retrieved=True,
        policy_ids=[9], contact_preference_ids=[21, 22],
        injected_item_ids=[101],
    )
    conn.execute("UPDATE rag_retrieval_logs SET suggestion_id = 5 WHERE id = ?", (log_id,))
    conn.commit()

    record_observation(
        conn, suggestion_id=5, account_wxid="wxid_a",
        event_type="adopted", selected_speech="今晚一起吃火锅？",
    )
    # 重复事件不重复记信号（singleton 去重）
    record_observation(
        conn, suggestion_id=5, account_wxid="wxid_a",
        event_type="adopted", selected_speech="今晚一起吃火锅？",
    )
    signals = store.list_feedback_policy_signals("wxid_a", 1)
    assert len(signals) == 1
    signal = signals[0]
    assert signal["signal_kind"] == "suggestion_outcome"
    assert signal["action"] == "adopted"
    assert signal["suggestion_id"] == 5
    assert signal["retrieval_log_id"] == log_id
    detail = json.loads(signal["detail_json"])
    assert detail["contact_preference_ids"] == [21, 22]
    assert detail["injected_item_ids"] == [101]
    assert json.loads(signal["affected_policy_ids_json"]) == [9]


def test_attribution_positive_writes_signal():
    """正归因（rewritten）→ 信号记录实际发送文本与策略绑定。"""
    conn, store = _store()
    log_id = store.insert_retrieval_log(
        account_wxid="wxid_a", conversation_id=1, query_text="[m]",
        document_ids=[], retrieval_scores={}, index_status="ready",
        elapsed_ms=3, rag_enabled=True, rag_retrieved=True,
        policy_ids=[3], contact_preference_ids=[7],
    )
    conn.execute("UPDATE rag_retrieval_logs SET suggestion_id = 12 WHERE id = ?", (log_id,))
    conn.commit()

    from app.services.realtime.feedback_attribution import SuggestionFeedbackAttributor

    attributor = SuggestionFeedbackAttributor(conn)
    suggestion = {"id": 12, "account_wxid": "wxid_a", "batch_id": "b1", "created_at": int(time.time())}
    result = {
        "attribution_type": "rewritten",
        "confidence": 0.85,
        "candidate_messages": [],
        "selected_speech": "多吃点",
        "final_message": "多吃点，别饿着",
    }
    attributor._write_policy_signal(suggestion, result, conversation_id=1)
    signals = store.list_feedback_policy_signals("wxid_a", 1)
    assert len(signals) == 1
    signal = signals[0]
    assert signal["signal_kind"] == "suggestion_attribution"
    assert signal["action"] == "rewritten"
    detail = json.loads(signal["detail_json"])
    assert detail["final_message"] == "多吃点，别饿着"
    assert detail["confidence"] == 0.85
    assert json.loads(signal["affected_policy_ids_json"]) == [3]


def test_rewritten_attribution_creates_shadow_candidates(monkeypatch):
    """P2.1 影子闭环：rewritten 正归因 → 偏好候选（uncertain 影子行，不进读侧）。"""
    conn, store = _store()
    monkeypatch.setattr(
        "app.services.realtime.feedback_attribution.SuggestionFeedbackAttributor._resolve_conversation_id",
        lambda self, suggestion: 1,
    )
    monkeypatch.setattr(
        "app.services.realtime.feedback_attribution.load_rag_settings" if False else
        "app.services.realtime.rag_config.load_rag_settings",
        lambda settings=None: {"rag_structured_fact_extraction_enabled": True},
    )
    import app.services.realtime.rag_fact_llm as fact_llm

    class _FakeAdapter:
        def extract_feedback_signals(self, *, original_speech, final_message):
            assert "多吃点" in original_speech
            return [
                {
                    "subject": "我",
                    "kind": "preference",
                    "content": "用户倾向把建议改得更口语化，加语气词软化语气",
                    "confidence": 0.8,
                    "evidence": "原始建议较书面，用户加了语气词",
                },
                # 碎片被质量门拦截
                {"subject": "我", "kind": "preference", "content": "好的好的",
                 "confidence": 0.9, "evidence": "-"},
            ]

    monkeypatch.setattr(fact_llm, "build_llm_fact_extractor", lambda: _FakeAdapter())

    from app.services.realtime.feedback_attribution import SuggestionFeedbackAttributor

    attributor = SuggestionFeedbackAttributor(conn)
    suggestion = {"id": 21, "account_wxid": "wxid_a", "batch_id": "b1", "created_at": int(time.time())}
    result = {
        "attribution_type": "rewritten",
        "confidence": 0.85,
        "candidate_messages": [],
        "selected_speech": "多吃点",
        "final_message": "多吃点呀，别饿着自己~",
    }
    created = attributor._try_extract_feedback_candidates(suggestion, result)
    assert len(created) == 1  # 碎片被拦，1 条候选

    row = conn.execute("SELECT * FROM rag_facts WHERE id = ?", (created[0],)).fetchone()
    assert row["status"] == "uncertain" and row["summary_method"] == "feedback_shadow"
    assert json.loads(row["source_window_json"])["evidence"].startswith("原始建议较书面")
    assert store.list_facts("wxid_a", 1) == []  # uncertain 不进读侧

    # 同一建议去重：再跑不重复抽取
    again = attributor._try_extract_feedback_candidates(suggestion, result)
    assert again == []
    assert conn.execute(
        "SELECT COUNT(*) FROM rag_facts WHERE summary_method='feedback_shadow'"
    ).fetchone()[0] == 1


def test_feedback_candidates_require_settings_and_type(monkeypatch):
    """accepted 不触发；开关关闭不触发。"""
    conn, store = _store()
    monkeypatch.setattr(
        "app.services.realtime.rag_config.load_rag_settings",
        lambda settings=None: {"rag_structured_fact_extraction_enabled": False},
    )
    from app.services.realtime.feedback_attribution import SuggestionFeedbackAttributor

    attributor = SuggestionFeedbackAttributor(conn)
    suggestion = {"id": 31, "account_wxid": "wxid_a", "created_at": int(time.time())}
    rewritten = {
        "attribution_type": "rewritten", "confidence": 0.9,
        "candidate_messages": [], "selected_speech": "a", "final_message": "b",
    }
    assert attributor._try_extract_feedback_candidates(suggestion, rewritten) == []

    monkeypatch.setattr(
        "app.services.realtime.rag_config.load_rag_settings",
        lambda settings=None: {"rag_structured_fact_extraction_enabled": True},
    )
    accepted = dict(rewritten, attribution_type="accepted")
    assert attributor._try_extract_feedback_candidates(suggestion, accepted) == []
