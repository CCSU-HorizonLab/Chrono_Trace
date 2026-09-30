"""审核返工回归测试:锁定更强审核 agent 指出的六类缺陷,防止复发。"""

import os
import sqlite3
import sys
from dataclasses import dataclass


sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.realtime.generation_context import (
    assemble_generation_context,
    resolve_generation_scope,
)
from app.services.realtime.historical_context import augment_context_with_historical_data
from app.services.realtime.llm_engine import LLMSuggestionEngine
from app.services.realtime.rag.context_builder import RagContextBuilder
from app.services.realtime.rag.store import RagStore
from app.services.realtime.recent_window import (
    KIND_HUMAN_CHAT,
    KIND_SYSTEM_NOTICE,
    KIND_TRANSFER_EVENT,
    classify_message_kind,
)


# ---- 返工 1:联系人来源一致性 -----------------------------------------------

def _scope_db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE conversations (
            id INTEGER PRIMARY KEY AUTOINCREMENT, account_wxid TEXT, display_name TEXT,
            username TEXT, is_deleted INTEGER DEFAULT 0, updated_at INTEGER
        )
        """
    )
    conn.executemany(
        "INSERT INTO conversations (account_wxid, display_name, username, is_deleted, updated_at) VALUES (?, ?, ?, 0, ?)",
        [
            ("wxid_a", "联系人A", "wxid_a1", 100),
            ("wxid_a", "联系人B", "wxid_b1", 200),
        ],
    )
    conn.commit()
    return conn


def test_explicit_conversation_id_db_identity_wins(monkeypatch):
    """传 A 的有效会话 ID + B 的名字 → 身份必须是 A(数据库为准)。"""
    conn = _scope_db()
    monkeypatch.setattr("app.db.connection.get_db", lambda: conn)
    scope = resolve_generation_scope(
        account_wxid="wxid_a", conversation_id=1, display_name="联系人B", entrypoint="manual",
    )
    assert scope.status == "ok"
    assert scope.conversation_id == 1
    assert scope.display_name == "联系人A"  # 数据库身份覆盖调用方传入的名字


def test_assemble_skips_profiles_when_display_name_shared(monkeypatch):
    """同名联系人:contact_profiles/session_threads 按 display_name 键控,必须跳过。"""
    conn = _scope_db()
    conn.execute(
        "INSERT INTO conversations (account_wxid, display_name, username, is_deleted, updated_at) "
        "VALUES ('wxid_a', '联系人A', 'wxid_a1_twin', 0, 300)"
    )
    conn.commit()
    monkeypatch.setattr("app.db.connection.get_db", lambda: conn)
    profile_calls = []
    monkeypatch.setattr(
        "app.services.realtime.contact_profiler.ContactProfiler.get_profile",
        lambda self, display_name, account_wxid="": profile_calls.append(display_name) or None,
    )
    memory_calls = []
    monkeypatch.setattr(
        "app.services.realtime.session_thread_service.SessionThreadService.retrieve_relevant_memories",
        lambda self, display_name, messages, **kw: memory_calls.append(display_name) or [],
    )

    ctx = {}
    scope = assemble_generation_context(
        ctx, entrypoint="manual", account_wxid="wxid_a", conversation_id=1, display_name="联系人A",
    )
    assert scope.valid and scope.display_name == "联系人A"
    assert profile_calls == []      # 显示名在账号内不唯一 → 画像跳过
    assert memory_calls == []       # 线程记忆同样跳过


def test_assemble_drops_self_profile_from_other_conversation(monkeypatch):
    """self_profiles 带 conversation_id:与本次范围不一致时必须丢弃。"""
    conn = _scope_db()
    monkeypatch.setattr("app.db.connection.get_db", lambda: conn)
    monkeypatch.setattr(
        "app.services.realtime.contact_profiler.ContactProfiler.get_profile",
        lambda self, display_name, account_wxid="": None,
    )
    monkeypatch.setattr(
        "app.services.realtime.self_profiler.SelfProfiler.get_profile",
        lambda self, display_name, account_wxid="": {
            "conversation_id": 999,  # 属于别的会话
            "profile": {"typing_style": "x"},
            "features_snapshot": {"user_msg_style": {"avg_chars_per_msg": 9.0}},
            "created_at": 0, "expires_at": 9999999999, "expired": False,
        },
    )

    ctx = {}
    assemble_generation_context(
        ctx, entrypoint="manual", account_wxid="wxid_a", conversation_id=1, display_name="联系人A",
    )
    assert "self_profile" not in ctx
    assert "self_profile_features" not in ctx


def test_historical_context_uses_explicit_conversation_id(monkeypatch):
    """好感/风格缓存按显式会话号读取,不再依赖画像缓存。"""
    loaded_ids = []

    def fake_loader(conversation_id):
        loaded_ids.append(conversation_id)
        return (None, {"overall_score": 70})

    ctx = {}
    augment_context_with_historical_data(
        ctx, self_profile_cache=None, load_style_inputs=fake_loader, conversation_id=7,
    )
    assert loaded_ids == [7]
    assert ctx["affinity_result"]["overall_score"] == 70


# ---- 返工 2:好感对象适配与偏好先排序后截断 ----------------------------------

@dataclass
class _FakeAffinity:
    overall_score: float = 70.0
    overall_interpretation: str = "互动积极"
    analysis_timestamp: int = 1790000000
    status: str = "completed"


def test_relationship_signal_accepts_dataclass_with_analysis_timestamp():
    engine = LLMSuggestionEngine()
    lines = engine._build_relationship_signal_lines(
        {"affinity_result": _FakeAffinity()},
        {"chat_window": [{"sender_attr": "friend", "content": "hi", "sentiment": {"polarity": 1}}]},
    )
    text = "\n".join(lines)
    assert "70/100" in text                    # 不再 unknown
    assert "分析时间: unknown" not in text      # analysis_timestamp 被读取
    assert "资金往来事件不反映对方态度" in text


def test_preferences_rank_before_truncate(monkeypatch):
    """第 7 位的游戏偏好必须能通过排序进入前 6(先排序后截断)。"""
    builder = RagContextBuilder(store=RagStore(sqlite3.connect(":memory:")))
    monkeypatch.setattr(
        "app.services.realtime.rag.context_builder.load_rag_settings",
        lambda: {
            "rag_relationship_policy_injection_enabled": True,
            "rag_relationship_policy_shadow_enabled": True,
        },
    )
    rows = [{"id": i, "slot_kind": "preference", "summary": f"无关偏好{i}", "confidence": 0.9,
             "support_count": 1, "sensitivity": "normal", "policy_version": "v1"} for i in range(1, 7)]
    rows.append({"id": 7, "slot_kind": "preference", "summary": "喜欢联机开黑打游戏", "confidence": 0.6,
                 "support_count": 2, "sensitivity": "normal", "policy_version": "v1"})
    monkeypatch.setattr(builder.store, "list_contact_preferences", lambda *a, **kw: rows)
    context = {
        "_task_routing": {
            "task": "invitation_planning",
            "output": "answer_with_speeches",
            "knowledge_needs": ["facts"],
        }
    }
    ids = builder._inject_contact_preferences(
        context, account_wxid="wxid_a", conversation_id=1, remote_model=False, redaction_disabled=False,
    )
    assert ids[0] == 7  # 游戏偏好排第一,尽管原序在第 7 位
    assert len(ids) <= 6


# ---- 返工 3:消息净化不误伤正常聊天 ------------------------------------------

def _msg(sender, content):
    return {"sender_attr": sender, "content": content, "message_type": "text"}


def test_normal_transfer_mentions_stay_human_chat():
    assert classify_message_kind(_msg("self", "我明天给你转账")) == KIND_HUMAN_CHAT
    assert classify_message_kind(_msg("friend", "你收到转账了吗")) == KIND_HUMAN_CHAT
    assert classify_message_kind(_msg("self", "上次说的转账的事别忘了")) == KIND_HUMAN_CHAT


def test_normal_boundary_expression_not_system_notice():
    assert classify_message_kind(_msg("friend", "别再给我拍了拍了")) == KIND_HUMAN_CHAT
    assert classify_message_kind(_msg("system", "对方拍了拍我")) == KIND_SYSTEM_NOTICE


def test_real_event_bubbles_still_classified():
    assert classify_message_kind(_msg("friend", "￥42.50 已被接收 微信转账")) == KIND_TRANSFER_EVENT
    assert classify_message_kind(_msg("friend", "已收款")) == KIND_TRANSFER_EVENT
    assert classify_message_kind(_msg("friend", "向你转账100.00元")) == KIND_TRANSFER_EVENT


# ---- 返工 3:prompt 契约(审核点名的四类输出问题) ----------------------------

def test_prompt_contracts_present():
    engine = LLMSuggestionEngine()
    # 转账事件告诫
    prompt = engine._build_prompt(
        "topic_cooling", "maintain",
        {"recent_messages": [{"id": 1, "timestamp": 1, "sender_attr": "friend", "content": "￥40.00 已收款 微信转账"}]},
    )
    assert "不代表对方态度" in prompt
    # 范围降级禁虚构
    prompt = engine._build_prompt(
        "manual_request", "maintain",
        {"user_context": [{"role": "user", "content": "怎么约她出来"}], "_generation_scope_missing": True},
    )
    assert "不要虚构具体地点、店铺、时间" in prompt
    # 话术贴合目标
    prompt = engine._build_prompt(
        "manual_request", "intimate",
        {"user_context": [{"role": "user", "content": "怎么回她关于周末的邀约"}]},
    )
    assert "不得擅自引入用户没提到的行动、地点或既成事实" in prompt
    # 共同经历区分
    prompt = engine._build_prompt(
        "manual_request", "maintain",
        {
            "user_context": [{"role": "user", "content": "我们玩过什么游戏"}],
            "retrieval_context": {
                "items": [{
                    "document_id": 1, "doc_type": "fact_memory", "content": "对方常打杀戮尖塔",
                    "score": 0.8, "time_label": "3天前", "fact_status": "active",
                    "fact_confidence": 0.8, "evidence_message_ids": [], "subject": "对方",
                    "memory_kind": "hobby_or_game", "as_of": 1700000000,
                }],
                "retrieval_status": "hit", "no_hit_guard": False, "query": "我们玩过什么游戏",
                "memory_intent": {"mode": "memory_request"},
            },
        },
    )
    assert "只有标注 主体=共同 的事实是双方共同经历" in prompt
    # 雷点自查
    prompt = engine._build_prompt(
        "manual_request", "maintain",
        {
            "user_context": [{"role": "user", "content": "怎么开玩笑不越界"}],
            "contact_preferences": [{"pref_id": 1, "slot_kind": "avoid", "summary": "介意被说穷", "confidence": 0.9}],
        },
    )
    assert "不得与上述任何雷点/偏好冲突" in prompt
    # 直答 reply 非空
    prompt = engine._build_prompt(
        "manual_request", "maintain",
        {"user_context": [{"role": "user", "content": "我们玩过什么游戏"}]},
    )
    assert "`reply` 不得为空字符串" in prompt


# ---- 三审修复:用户提问优先仲裁 + 关系判断不确定性 ---------------------------

def test_system_prompt_has_user_question_arbitration_rule():
    """三审 major(task_routing-01 偏题):用户显式提问必须高于窗口走向的自行解读。"""
    from app.services.realtime.llm_engine import SYSTEM_PROMPT

    assert "仲裁规则" in SYSTEM_PROMPT
    assert "永远高于你对【最近对话】走向的自行解读" in SYSTEM_PROMPT
    assert "不得因为窗口看起来" in SYSTEM_PROMPT


def test_relationship_signal_requires_uncertain_phrasing():
    """三审 minor(09 过度确定):关系信号块要求不确定性表述。"""
    engine = LLMSuggestionEngine()
    lines = engine._build_relationship_signal_lines({}, {"chat_window": []})
    text = "\n".join(lines)
    assert "保留不确定性" in text
    assert "禁止下确定性结论" in text
