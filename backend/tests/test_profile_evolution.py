"""画像演变测试：对半口径 / 快照缓存命中与 force / 取消 / include_self / 会话校验。"""

import sys
import threading
from pathlib import Path

import pytest


backend_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(backend_dir))


from app.db.connection import DatabaseConnection
from app.services.analysis.profile_evolution_service import ProfileEvolutionService
from app.services.realtime.contact_profiler import (
    PROFILE_CUSTOM_MAX_SPAN,
    ContactProfiler,
)
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


def test_halves_boundary_matches_wordcloud_formula(isolated_db, llm_calls):
    """对半公式与词云严格同式：mid=(f+t)//2，前 [f, mid-1] 后 [mid, t] 闭区间。"""
    conn = isolated_db
    conv_id = seed_conversation(conn)

    result = ProfileEvolutionService().generate(conv_id, 1000, 2001, "wxid_me")

    assert result["ok"] is True
    assert result["mid_ts"] == 1500
    assert result["halves"][0]["from_ts"] == 1000
    assert result["halves"][0]["to_ts"] == 1499
    assert result["halves"][1]["from_ts"] == 1500
    assert result["halves"][1]["to_ts"] == 2001
    assert [h["label"] for h in result["halves"]] == ["前半段", "后半段"]
    # 两个半窗各调一次联系人画像（默认不含我的画像）
    assert [("contact", 1000, 1499), ("contact", 1500, 2001)] == [
        (kind, f, t) for kind, f, t in llm_calls
    ]


def test_snapshot_cache_hit_skips_llm(isolated_db, llm_calls):
    """半窗快照精确键命中即跳过 LLM；force=True 全部重算。"""
    conn = isolated_db
    conv_id = seed_conversation(conn)
    profiler = ContactProfiler()
    profiler._ensure_table(conn)
    for half_from, half_to in ((1000, 1499), (1500, 2001)):
        profiler._save_cache(
            conn, "老朋友", conv_id, {"personality_tags": ["快照画像"]}, 3, {}, "wxid_me",
            window_kind="custom", window_from=half_from, window_to=half_to,
        )

    result = ProfileEvolutionService().generate(conv_id, 1000, 2001, "wxid_me")
    assert result["ok"] is True
    assert llm_calls == []  # 全部命中缓存
    for half in result["halves"]:
        assert half["contact"]["cached"] is True
        assert half["contact"]["profile"] == {"personality_tags": ["快照画像"]}

    # force：无视缓存重算
    result = ProfileEvolutionService().generate(conv_id, 1000, 2001, "wxid_me", force=True)
    assert result["ok"] is True
    assert len(llm_calls) == 2
    for half in result["halves"]:
        assert half["contact"]["cached"] is False


def test_empty_account_resolves_like_save_path(isolated_db, llm_calls, monkeypatch):
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
    for half_from, half_to in ((1000, 1499), (1500, 2001)):
        # 生成侧（真实 profiler）按解析后账号 wxid_me 落 custom 快照
        profiler._save_cache(
            conn, "老朋友", conv_id, {"personality_tags": ["存档"]}, 3, {}, "wxid_me",
            window_kind="custom", window_from=half_from, window_to=half_to,
        )

    result = ProfileEvolutionService().generate(conv_id, 1000, 2001, "")

    assert result["ok"] is True
    assert llm_calls == []  # 解析对齐 → 两个半窗都命中
    for half in result["halves"]:
        assert half["contact"]["cached"] is True


def test_corrupt_snapshot_row_treated_as_miss(isolated_db, llm_calls):
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

    result = ProfileEvolutionService().generate(conv_id, 1000, 2001, "wxid_me")

    assert result["ok"] is True
    # 只有坏行半窗重算，完好半窗命中缓存
    assert [c[1:] for c in llm_calls] == [(1500, 2001)]
    assert result["halves"][0]["contact"]["cached"] is True
    assert result["halves"][1]["contact"]["cached"] is False
    assert result["halves"][1]["contact"]["profile"] == {"personality_tags": ["温和"]}


def test_partial_cache_only_generates_missing_half(isolated_db, llm_calls):
    """只有前半窗有快照：仅补后半窗（增量续跑语义）。"""
    conn = isolated_db
    conv_id = seed_conversation(conn)
    profiler = ContactProfiler()
    profiler._ensure_table(conn)
    profiler._save_cache(
        conn, "老朋友", conv_id, {"personality_tags": ["前段"]}, 3, {}, "wxid_me",
        window_kind="custom", window_from=1000, window_to=1499,
    )

    result = ProfileEvolutionService().generate(conv_id, 1000, 2001, "wxid_me")
    assert result["ok"] is True
    assert [c[0] for c in llm_calls] == ["contact"]  # 只补了后半窗
    assert llm_calls[0][1:] == (1500, 2001)
    assert result["halves"][0]["contact"]["cached"] is True
    assert result["halves"][1]["contact"]["cached"] is False


def test_cancel_before_generate(isolated_db, llm_calls):
    """取消事件预置：不发起任何生成，直接返回 cancelled。"""
    conn = isolated_db
    conv_id = seed_conversation(conn)
    cancel = threading.Event()
    cancel.set()

    result = ProfileEvolutionService().generate(
        conv_id, 1000, 2001, "wxid_me", cancel_event=cancel
    )

    assert result["ok"] is False
    assert result["cancelled"] is True
    assert llm_calls == []


def test_include_self_generates_both_kinds(isolated_db, llm_calls):
    """include_self=True：每半窗 contact + self 各一次（共 4 次）。"""
    conn = isolated_db
    conv_id = seed_conversation(conn)

    result = ProfileEvolutionService().generate(
        conv_id, 1000, 2001, "wxid_me", include_self=True
    )

    assert result["ok"] is True
    assert [c[0] for c in llm_calls] == ["contact", "self", "contact", "self"]
    for half in result["halves"]:
        assert half["self"] is not None
        assert half["self"]["profile"] == {"typing_style": "简短"}


def test_missing_conversation_returns_error(isolated_db, llm_calls):
    """会话不存在（或不属于该账号）：拒绝生成。"""
    conn = isolated_db

    result = ProfileEvolutionService().generate(999, 1000, 2001, "wxid_me")
    assert result["ok"] is False
    assert "未找到会话" in result["error"]
    assert llm_calls == []


def test_window_too_short(isolated_db):
    """窗口不足两天：对半后前半窗为空区间，直接拒绝。"""
    conn = isolated_db

    result = ProfileEvolutionService().generate(1, 1000, 1001, "wxid_me")
    assert result["ok"] is False
    assert "太短" in result["error"]


def test_span_exceeds_custom_limit(isolated_db, llm_calls):
    """全窗跨度超过 730 天上限直接拒绝：对半后单半窗虽各自达标，
    但「任意窗 ≤730 天」的口径不能被演变全窗绕过。"""
    conn = isolated_db
    conv_id = seed_conversation(conn)

    result = ProfileEvolutionService().generate(
        conv_id, 1000, 1000 + PROFILE_CUSTOM_MAX_SPAN + 86400, "wxid_me"
    )

    assert result["ok"] is False
    assert "跨度不能超过" in result["error"]
    assert llm_calls == []


def test_unresolvable_account_rejected(isolated_db, llm_calls, monkeypatch):
    """账号解析为空（无活跃账号）：拒绝而不是去掉账号过滤兜底——那会跨账号取会话。"""
    import app.services.realtime.contact_profiler as contact_profiler_mod

    monkeypatch.setattr(
        contact_profiler_mod, "get_active_wechat_account_wxid", lambda _s: ""
    )
    conn = isolated_db
    conv_id = seed_conversation(conn)

    result = ProfileEvolutionService().generate(conv_id, 1000, 2001, "")

    assert result["ok"] is False
    assert "无法确定当前微信账号" in result["error"]
    assert llm_calls == []
