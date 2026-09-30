"""G1 统一联系人上下文测试:范围解析、歧义拒绝、安全降级、统一装配。"""

import os
import sqlite3
import sys


sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.realtime import generation_context
from app.services.realtime.generation_context import (
    SCOPE_AMBIGUOUS,
    SCOPE_INVALID_CONVERSATION,
    SCOPE_MISSING,
    SCOPE_OK,
    GenerationScope,
    assemble_generation_context,
    new_request_id,
    resolve_generation_scope,
)


def _setup_db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE conversations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            account_wxid TEXT NOT NULL,
            display_name TEXT,
            username TEXT,
            is_deleted INTEGER DEFAULT 0,
            updated_at INTEGER
        )
        """
    )
    conn.executemany(
        "INSERT INTO conversations (account_wxid, display_name, username, is_deleted, updated_at) VALUES (?, ?, ?, ?, ?)",
        [
            ("wxid_a", "昕", "wxid_xin", 0, 100),
            ("wxid_a", "昕", "wxid_xin2", 0, 200),  # 同名第二个联系人
            ("wxid_b", "昕", "wxid_other_account", 0, 300),  # 跨账号同名
            ("wxid_a", "已删除", "wxid_deleted", 1, 400),
        ],
    )
    conn.commit()
    return conn


def test_explicit_conversation_id_owned_by_account(monkeypatch):
    conn = _setup_db()
    monkeypatch.setattr("app.db.connection.get_db", lambda: conn)
    scope = resolve_generation_scope(
        account_wxid="wxid_a",
        conversation_id=1,
        display_name="昕",
        entrypoint="manual",
    )
    assert scope.status == SCOPE_OK
    assert scope.conversation_id == 1
    assert scope.valid


def test_explicit_conversation_id_not_owned_never_falls_back(monkeypatch):
    """显式会话 ID 不属于当前账号时,不得回退显示名猜一个。"""
    conn = _setup_db()
    monkeypatch.setattr("app.db.connection.get_db", lambda: conn)
    scope = resolve_generation_scope(
        account_wxid="wxid_a",
        conversation_id=3,  # 属于 wxid_b
        display_name="昕",
        entrypoint="manual",
    )
    assert scope.status == SCOPE_INVALID_CONVERSATION
    assert not scope.valid


def test_same_display_name_multiple_contacts_is_ambiguous(monkeypatch):
    """同名联系人不得自动选取。"""
    conn = _setup_db()
    monkeypatch.setattr("app.db.connection.get_db", lambda: conn)
    scope = resolve_generation_scope(
        account_wxid="wxid_a",
        display_name="昕",
        entrypoint="full_auto",
    )
    assert scope.status == SCOPE_AMBIGUOUS
    assert not scope.valid


def test_unique_username_match_wins_over_ambiguity(monkeypatch):
    conn = _setup_db()
    monkeypatch.setattr("app.db.connection.get_db", lambda: conn)
    scope = resolve_generation_scope(
        account_wxid="wxid_a",
        display_name="昕",
        username="wxid_xin2",
        entrypoint="semi_auto_trigger",
    )
    assert scope.status == SCOPE_OK
    assert scope.conversation_id == 2


def test_missing_scope_reasons(monkeypatch):
    conn = _setup_db()
    monkeypatch.setattr("app.db.connection.get_db", lambda: conn)
    assert resolve_generation_scope(account_wxid="").status == SCOPE_MISSING
    no_contact = resolve_generation_scope(account_wxid="wxid_a")
    assert no_contact.reason == "no_contact_scope"
    no_match = resolve_generation_scope(account_wxid="wxid_a", display_name="不存在")
    assert no_match.reason == "no_matching_contact"


def test_db_failure_degrades_to_missing_scope(monkeypatch):
    def _boom():
        raise RuntimeError("db down")

    monkeypatch.setattr("app.db.connection.get_db", _boom)
    scope = resolve_generation_scope(account_wxid="wxid_a", display_name="昕")
    assert scope.status == SCOPE_MISSING
    assert scope.reason == "scope_lookup_failed"


def test_apply_generation_scope_degrades_safely(monkeypatch):
    ctx = {
        "account_wxid": "wxid_a",
        "conversation_id": 99,
        "display_name": "昕",
        "contact_profile": {"personality_tags": ["a"]},
        "self_profile": {"typing_style": "b"},
        "relevant_memories": [{"summary": "c"}],
        "relationship_policy": {"stage": "x"},
        "recent_messages": [{"content": "hi"}],
    }
    scope = GenerationScope(
        account_wxid="wxid_a",
        status=SCOPE_AMBIGUOUS,
        reason="ambiguous_display_name_matches=2",
        entrypoint="full_auto",
    )
    generation_context.apply_generation_scope(ctx, scope)
    assert ctx["_generation_scope_missing"] is True
    assert ctx["_generation_scope_reason"] == "ambiguous_display_name_matches=2"
    # 按联系人键控的历史知识全部剥离,防止错配注入
    assert "contact_profile" not in ctx
    assert "self_profile" not in ctx
    assert "relevant_memories" not in ctx
    assert "relationship_policy" not in ctx
    assert "conversation_id" not in ctx
    # 当前窗口上下文保留(安全降级后模型唯一可用的对话依据)
    assert ctx["recent_messages"] == [{"content": "hi"}]
    assert ctx["_generation_request_id"]
    assert ctx["_generation_entrypoint"] == "full_auto"


def test_apply_generation_scope_valid_writes_stable_keys(monkeypatch):
    ctx = {}
    scope = GenerationScope(
        account_wxid="wxid_a",
        conversation_id=1,
        display_name="昕",
        status=SCOPE_OK,
        entrypoint="manual",
    )
    generation_context.apply_generation_scope(ctx, scope)
    assert ctx["account_wxid"] == "wxid_a"
    assert ctx["conversation_id"] == 1
    assert ctx["display_name"] == "昕"
    assert "_generation_scope_missing" not in ctx


def test_assemble_skips_profiles_when_scope_missing(monkeypatch):
    """范围缺失时不取画像/不取会话记忆,但保留当前窗口与情绪。"""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        "CREATE TABLE conversations (id INTEGER PRIMARY KEY AUTOINCREMENT, account_wxid TEXT, display_name TEXT, username TEXT, is_deleted INTEGER DEFAULT 0, updated_at INTEGER)"
    )
    monkeypatch.setattr("app.db.connection.get_db", lambda: conn)

    calls = []
    monkeypatch.setattr(
        "app.services.realtime.contact_profiler.ContactProfiler.get_profile",
        lambda self, display_name, account_wxid="": calls.append(("contact", display_name)) or None,
    )
    monkeypatch.setattr(
        "app.services.realtime.self_profiler.SelfProfiler.get_profile",
        lambda self, display_name, account_wxid="": calls.append(("self", display_name)) or None,
    )

    ctx = {}
    scope = assemble_generation_context(
        ctx,
        entrypoint="manual",
        account_wxid="wxid_a",
        display_name="查无此人",
        emotion_summary={"trend": "neutral"},
    )
    assert not scope.valid
    assert calls == []  # 画像未被调用
    assert ctx["emotion_summary"] == {"trend": "neutral"}
    assert ctx["_generation_scope_missing"] is True


def test_assemble_uses_unified_keys_for_valid_scope(monkeypatch):
    conn = _setup_db()
    monkeypatch.setattr("app.db.connection.get_db", lambda: conn)
    monkeypatch.setattr(
        "app.services.realtime.contact_profiler.ContactProfiler.get_profile",
        lambda self, display_name, account_wxid="": None,
    )
    monkeypatch.setattr(
        "app.services.realtime.self_profiler.SelfProfiler.get_profile",
        lambda self, display_name, account_wxid="": None,
    )
    memory_calls = []
    monkeypatch.setattr(
        "app.services.realtime.session_thread_service.SessionThreadService.retrieve_relevant_memories",
        lambda self, display_name, messages, **kw: memory_calls.append(display_name) or [{"summary": "m"}],
    )

    ctx = {}
    scope = assemble_generation_context(
        ctx,
        entrypoint="manual",
        account_wxid="wxid_a",
        conversation_id=1,
        display_name="昕",
        username="wxid_xin",
        emotion_summary={"trend": "positive"},
    )
    assert scope.valid
    assert scope.conversation_id == 1
    assert ctx["_generation_entrypoint"] == "manual"
    assert ctx["conversation_id"] == 1
    # 返工 1:昕 在账号内同名(conversation 2),画像/线程记忆必须跳过
    assert memory_calls == []
    assert "relevant_memories" not in ctx


def test_new_request_id_unique():
    assert new_request_id() != new_request_id()
