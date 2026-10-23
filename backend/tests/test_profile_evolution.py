"""画像演变测试：章节分段口径 / 快照缓存命中与 force / 取消 / include_self / 会话校验。"""

import sys
import threading
from pathlib import Path

import pytest


backend_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(backend_dir))


import app.services.analysis.relationship_chapters as chaptersmod
from app.db.connection import DatabaseConnection
from app.services.analysis.profile_evolution_service import ProfileEvolutionService
from app.services.realtime.contact_profiler import ContactProfiler
from app.services.realtime.self_profiler import SelfProfiler


@pytest.fixture
def isolated_db(tmp_path):
    DatabaseConnection.close()
    DatabaseConnection._db_path = None

    db_path = tmp_path / "chrono_trace_test.db"
    conn = DatabaseConnection.initialize(str(db_path))
    yield conn

    DatabaseConnection.close()
    DatabaseConnection._db_path = None


@pytest.fixture
def spans(monkeypatch):
    """钉住章节分段（C4 统一口径）：画像演变按章边界切窗，不依赖检测内部。"""
    two = [(1000, 1499), (1500, 2001)]
    monkeypatch.setattr(
        chaptersmod, "chapter_spans",
        lambda cid: {"ok": True, "spans": two, "full_from": two[0][0], "full_to": two[-1][1]},
    )
    return two


def seed_conversation(conn, display_name="老朋友", account="wxid_me"):
    conn.execute(
        """
        INSERT INTO conversations
        (account_wxid, username, display_name, remark, nickname, platform, created_at, updated_at, message_count, is_deleted)
        VALUES (?, 'wxid_friend', ?, '', '', 'wechat', 1, 1, 0, 0)
        """,
        (account, display_name),
    )
    conn.commit()
    return conn.execute(
        "SELECT id FROM conversations WHERE display_name = ?", (display_name,)
    ).fetchone()[0]


@pytest.fixture
def llm_calls(monkeypatch):
    """记录 generate_profile 调用窗口；返回可编程的假画像生成器。"""
    calls: list[tuple] = []

    def fake_contact(self, display_name, budget_level="medium", custom_budget=0,
                     account_wxid="", should_abort=None, from_ts=0, to_ts=0, *a, **kw):
        calls.append(("contact", from_ts, to_ts))
        return {"ok": True, "profile": {"personality_tags": ["温和"]}}

    def fake_self(self, display_name, budget_level="medium", custom_budget=0,
                  account_wxid="", should_abort=None, from_ts=0, to_ts=0, *a, **kw):
        calls.append(("self", from_ts, to_ts))
        return {"ok": True, "profile": {"typing_style": "简短"}}

    monkeypatch.setattr(ContactProfiler, "generate_profile", fake_contact)
    monkeypatch.setattr(SelfProfiler, "generate_profile", fake_self)
    return calls


def test_segments_follow_chapter_spans(isolated_db, llm_calls, spans):
    """段边界与标签来自 chapter_spans（第 N 章），每章各调一次联系人画像。"""
    conn = isolated_db
    conv_id = seed_conversation(conn)

    result = ProfileEvolutionService().generate(conv_id, "wxid_me")

    assert result["ok"] is True
    assert [(h["from_ts"], h["to_ts"]) for h in result["segments"]] == spans
    assert [h["label"] for h in result["segments"]] == ["第 1 章", "第 2 章"]
    assert [("contact", 1000, 1499), ("contact", 1500, 2001)] == [
        (kind, f, t) for kind, f, t in llm_calls
    ]


def test_generation_passes_evolution_origin(isolated_db, monkeypatch, spans):
    """演变生成经 origin='evolution' 透传（快照列表「演变段」徽标依赖该列，
    手动指定窗/滚动窗落 ''）。"""
    conn = isolated_db
    conv_id = seed_conversation(conn)
    seen = []

    def fake(self, display_name, *a, **kw):
        seen.append(kw.get("origin"))
        return {"ok": True, "profile": {"personality_tags": ["温和"]}}

    monkeypatch.setattr(ContactProfiler, "generate_profile", fake)

    result = ProfileEvolutionService().generate(conv_id, "wxid_me")

    assert result["ok"] is True
    assert seen == ["evolution", "evolution"]


def test_no_text_messages_rejected(isolated_db, llm_calls):
    """空会话（chapter_spans 降级也切不出段）：拒绝生成。"""
    conn = isolated_db
    conv_id = seed_conversation(conn)
    # 不钉 spans：真实 chapter_spans 在空消息库上返回空段（诚实降级终点）

    result = ProfileEvolutionService().generate(conv_id, "wxid_me")

    assert result["ok"] is False
    assert "没有文本消息" in result["error"]
    assert llm_calls == []


def test_snapshot_cache_hit_skips_llm(isolated_db, llm_calls, spans):
    """分章快照精确键命中即跳过 LLM；force=True 全部重算。"""
    conn = isolated_db
    conv_id = seed_conversation(conn)
    profiler = ContactProfiler()
    profiler._ensure_table(conn)
    for seg_from, seg_to in spans:
        profiler._save_cache(
            conn, "老朋友", conv_id, {"personality_tags": ["快照画像"]}, 3, {}, "wxid_me",
            window_kind="custom", window_from=seg_from, window_to=seg_to,
        )

    result = ProfileEvolutionService().generate(conv_id, "wxid_me")
    assert result["ok"] is True
    assert llm_calls == []  # 全部命中缓存
    for seg in result["segments"]:
        assert seg["contact"]["cached"] is True
        assert seg["contact"]["profile"] == {"personality_tags": ["快照画像"]}

    # force：无视缓存重算
    result = ProfileEvolutionService().generate(conv_id, "wxid_me", force=True)
    assert result["ok"] is True
    assert len(llm_calls) == 2
    for seg in result["segments"]:
        assert seg["contact"]["cached"] is False


def test_empty_account_resolves_like_save_path(isolated_db, llm_calls, spans, monkeypatch):
    """生产链路 account_wxid=""：查询键与生成侧落库账号同源解析（活跃账号），
    否则快照永远查不中、演变每次全价调 LLM。"""
    import app.services.realtime.contact_profiler as contact_profiler_mod

    monkeypatch.setattr(
        contact_profiler_mod, "get_active_wechat_account_wxid", lambda _s: "wxid_me"
    )
    conn = isolated_db
    conv_id = seed_conversation(conn, account="wxid_me")
    profiler = ContactProfiler()
    profiler._ensure_table(conn)
    for seg_from, seg_to in spans:
        # 生成侧（真实 profiler）按解析后账号 wxid_me 落 custom 快照
        profiler._save_cache(
            conn, "老朋友", conv_id, {"personality_tags": ["存档"]}, 3, {}, "wxid_me",
            window_kind="custom", window_from=seg_from, window_to=seg_to,
        )

    result = ProfileEvolutionService().generate(conv_id, "")

    assert result["ok"] is True
    assert llm_calls == []  # 解析对齐 → 两章都命中
    for seg in result["segments"]:
        assert seg["contact"]["cached"] is True


def test_corrupt_snapshot_row_treated_as_miss(isolated_db, llm_calls, spans):
    """profile_json 损坏/为空的残行视作未命中：走生成并覆盖坏行，
    不让空画像带「历史快照」徽标卡死缓存。"""
    conn = isolated_db
    conv_id = seed_conversation(conn)
    profiler = ContactProfiler()
    profiler._ensure_table(conn)
    profiler._save_cache(
        conn, "老朋友", conv_id, {"personality_tags": ["完好"]}, 3, {}, "wxid_me",
        window_kind="custom", window_from=1000, window_to=1499,
    )
    conn.execute(
        "INSERT INTO contact_profiles (account_wxid, display_name, conversation_id, "
        "window_kind, window_from, window_to, budget_level, profile_json, "
        "features_snapshot, message_sample_count, token_usage, created_at, expires_at) "
        "VALUES ('wxid_me', '老朋友', ?, 'custom', 1500, 2001, 'medium', '', "
        "NULL, 0, 0, 100, 200)",
        (conv_id,),
    )
    conn.commit()

    result = ProfileEvolutionService().generate(conv_id, "wxid_me")

    assert result["ok"] is True
    # 只有坏行章重算，完好章命中缓存
    assert [c[1:] for c in llm_calls] == [(1500, 2001)]
    assert result["segments"][0]["contact"]["cached"] is True
    assert result["segments"][1]["contact"]["cached"] is False
    assert result["segments"][1]["contact"]["profile"] == {"personality_tags": ["温和"]}


def test_partial_cache_only_generates_missing_chapter(isolated_db, llm_calls, spans):
    """只有第 1 章有快照：仅补第 2 章（增量续跑语义）。"""
    conn = isolated_db
    conv_id = seed_conversation(conn)
    profiler = ContactProfiler()
    profiler._ensure_table(conn)
    profiler._save_cache(
        conn, "老朋友", conv_id, {"personality_tags": ["前章"]}, 3, {}, "wxid_me",
        window_kind="custom", window_from=1000, window_to=1499,
    )

    result = ProfileEvolutionService().generate(conv_id, "wxid_me")
    assert result["ok"] is True
    assert [c[0] for c in llm_calls] == ["contact"]  # 只补了第 2 章
    assert llm_calls[0][1:] == (1500, 2001)
    assert result["segments"][0]["contact"]["cached"] is True
    assert result["segments"][1]["contact"]["cached"] is False


def test_cancel_before_generate(isolated_db, llm_calls, spans):
    """取消事件预置：不发起任何生成，直接返回 cancelled。"""
    conn = isolated_db
    conv_id = seed_conversation(conn)
    cancel = threading.Event()
    cancel.set()

    result = ProfileEvolutionService().generate(conv_id, "wxid_me", cancel_event=cancel)

    assert result["ok"] is False
    assert result["cancelled"] is True
    assert llm_calls == []


def test_include_self_generates_both_kinds(isolated_db, llm_calls, spans):
    """include_self=True：每章 contact + self 各一次（默认 2 章共 4 次）。"""
    conn = isolated_db
    conv_id = seed_conversation(conn)

    result = ProfileEvolutionService().generate(conv_id, "wxid_me", include_self=True)

    assert result["ok"] is True
    assert [c[0] for c in llm_calls] == ["contact", "self", "contact", "self"]
    for seg in result["segments"]:
        assert seg["self"] is not None
        assert seg["self"]["profile"] == {"typing_style": "简短"}


def test_missing_conversation_returns_error(isolated_db, llm_calls, spans):
    """会话不存在（或不属于该账号）：拒绝生成。"""
    conn = isolated_db

    result = ProfileEvolutionService().generate(999, "wxid_me")
    assert result["ok"] is False
    assert "未找到会话" in result["error"]
    assert llm_calls == []


def test_unresolvable_account_rejected(isolated_db, llm_calls, spans, monkeypatch):
    """账号解析为空（无活跃账号）：拒绝而不是去掉账号过滤兜底——那会跨账号取会话。"""
    import app.services.realtime.contact_profiler as contact_profiler_mod

    monkeypatch.setattr(
        contact_profiler_mod, "get_active_wechat_account_wxid", lambda _s: ""
    )
    conn = isolated_db
    conv_id = seed_conversation(conn)

    result = ProfileEvolutionService().generate(conv_id, "")

    assert result["ok"] is False
    assert "无法确定当前微信账号" in result["error"]
    assert llm_calls == []
