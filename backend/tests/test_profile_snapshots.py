"""画像快照缓存与时间窗口径测试。

覆盖：旧结构 DROP 重建 / 窗口键多快照共存 / 同窗 REPLACE / TTL 只作用
rolling / 裁剪上限 / custom 窗采样边界与防呆 / 特征同窗化 / 续期保档位 /
relationship_policy rolling 过滤。
"""

import sys
import time
from pathlib import Path

import pytest


backend_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(backend_dir))


from app.db.connection import DatabaseConnection
from app.services.realtime.contact_profiler import (
    PROFILE_SNAPSHOT_KEEP,
    PROFILE_SNAPSHOT_KEEP_CUSTOM,
    PROFILE_TTL,
    ContactProfiler,
)
from app.services.realtime.self_profiler import SelfProfiler


# (profiler 类, 表名)：两个 profiler 快照行为同构，逐用例参数化
PROFILER_TABLES = [
    (ContactProfiler, "contact_profiles"),
    (SelfProfiler, "self_profiles"),
]


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


def add_msg(conn, conv_id, content, ts, is_sender=0):
    cur = conn.execute(
        """
        INSERT INTO messages
        (conversation_id, talker, is_sender, message_type, content, timestamp, created_at)
        VALUES (?, 'wxid_friend', ?, 1, ?, ?, ?)
        """,
        (conv_id, is_sender, content, ts, ts),
    )
    return cur.lastrowid


def save_snapshot(profiler, conn, profile, *, window_kind="rolling",
                  window_from=10, window_to=20, budget_level="medium",
                  display_name="老朋友", account="wxid_me"):
    profiler._save_cache(
        conn, display_name, 1, profile, 3, {}, account,
        window_kind=window_kind, window_from=window_from, window_to=window_to,
        budget_level=budget_level,
    )


# ==================== 表结构 ====================

@pytest.mark.parametrize("profiler_cls,table", PROFILER_TABLES)
def test_ensure_table_drops_legacy_and_rebuilds(isolated_db, profiler_cls, table):
    """旧结构（单行覆盖）→ DROP 重建为快照结构，旧行不迁移；已是新结构二次调用零 DDL。"""
    conn = isolated_db
    conn.execute(f"""
        CREATE TABLE {table} (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            account_wxid TEXT NOT NULL, display_name TEXT NOT NULL, conversation_id INTEGER,
            profile_json TEXT NOT NULL, features_snapshot TEXT,
            message_sample_count INTEGER, token_usage INTEGER,
            created_at INTEGER NOT NULL, expires_at INTEGER NOT NULL,
            UNIQUE(account_wxid, display_name)
        )
    """)
    conn.execute(
        f"INSERT INTO {table} (account_wxid, display_name, profile_json, created_at, expires_at)"
        " VALUES ('wxid_me', '老朋友', '{}', 1, 2)"
    )
    conn.commit()

    profiler_cls()._ensure_table(conn)

    cols = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
    assert {"window_kind", "window_from", "window_to", "budget_level"} <= cols
    assert conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0

    # 已是快照结构：再次调用不触发任何 DDL
    statements = []
    conn.set_trace_callback(statements.append)
    try:
        profiler_cls()._ensure_table(conn)
    finally:
        conn.set_trace_callback(None)
    assert not any(
        "DROP" in s.upper() or "CREATE" in s.upper() for s in statements
    )


# ==================== 快照共存与读取语义 ====================

@pytest.mark.parametrize("profiler_cls,table", PROFILER_TABLES)
def test_rolling_and_custom_coexist_get_reads_rolling(isolated_db, profiler_cls, table):
    """rolling 与 custom 快照共存；get_profile 只取 rolling 最新一条。"""
    conn = isolated_db
    profiler = profiler_cls()
    save_snapshot(profiler, conn, {"tag": "rolling"}, window_kind="rolling")
    save_snapshot(profiler, conn, {"tag": "custom"}, window_kind="custom", window_from=1, window_to=2)
    assert conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 2

    cached = profiler.get_profile("老朋友", "wxid_me")
    assert cached is not None
    assert cached["profile"] == {"tag": "rolling"}
    assert cached["window_kind"] == "rolling"
    assert cached["budget_level"] == "medium"

    snapshots = profiler.list_snapshots("老朋友", account_wxid="wxid_me")
    kinds = {s["window_kind"] for s in snapshots}
    assert kinds == {"rolling", "custom"}
    assert all(s["profile"] for s in snapshots)


@pytest.mark.parametrize("profiler_cls,table", PROFILER_TABLES)
def test_same_window_replace_single_row(isolated_db, profiler_cls, table):
    """同窗口键重试：INSERT OR REPLACE 同键覆盖，不堆积。"""
    conn = isolated_db
    profiler = profiler_cls()
    save_snapshot(profiler, conn, {"v": 1})
    save_snapshot(profiler, conn, {"v": 2})
    assert conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 1
    assert profiler.get_profile("老朋友", "wxid_me")["profile"] == {"v": 2}


@pytest.mark.parametrize("profiler_cls,table", PROFILER_TABLES)
def test_ttl_only_applies_to_rolling(isolated_db, profiler_cls, table):
    """rolling 行 7 天 TTL；custom 快照是存档品，免 TTL（占位一年）。"""
    conn = isolated_db
    profiler = profiler_cls()
    save_snapshot(profiler, conn, {"tag": "rolling"}, window_kind="rolling")
    save_snapshot(profiler, conn, {"tag": "custom"}, window_kind="custom", window_from=1, window_to=2)

    rows = {
        row["window_kind"]: row
        for row in conn.execute(
            f"SELECT window_kind, created_at, expires_at FROM {table}"
        )
    }
    assert rows["rolling"]["expires_at"] - rows["rolling"]["created_at"] == PROFILE_TTL
    assert rows["custom"]["expires_at"] - rows["custom"]["created_at"] >= 364 * 86400


@pytest.mark.parametrize("profiler_cls,table", PROFILER_TABLES)
def test_trim_keeps_recent_snapshots(isolated_db, profiler_cls, table):
    """rolling 快照自然累积，每 (账号,联系人,窗口类) 分组保留最近 8 条。"""
    conn = isolated_db
    profiler = profiler_cls()
    for i in range(PROFILE_SNAPSHOT_KEEP + 2):
        # 每次续期 now 前移 → 窗口键不同 → 新行；created_at 也递增保证裁剪可判定
        save_snapshot(profiler, conn, {"i": i}, window_from=i, window_to=100 + i)
        conn.execute(f"UPDATE {table} SET created_at = ? WHERE window_from = ?", (1000 + i, i))
        conn.commit()

    rows = conn.execute(
        f"SELECT window_from FROM {table} ORDER BY created_at DESC"
    ).fetchall()
    assert len(rows) == PROFILE_SNAPSHOT_KEEP
    kept = {r["window_from"] for r in rows}
    assert PROFILE_SNAPSHOT_KEEP - 1 in kept  # 保留最新
    assert 0 not in kept  # 最旧的被裁掉


@pytest.mark.parametrize("profiler_cls,table", PROFILER_TABLES)
def test_trim_custom_keeps_archive_limit(isolated_db, profiler_cls, table):
    """custom 分组（画像演变半窗 + 手动指定窗共用）按存档上限 24 裁剪——
    回廊能展示的快照（list_snapshots 24 条）不会被逐出，演变续跑免费不失效。"""
    conn = isolated_db
    profiler = profiler_cls()
    for i in range(PROFILE_SNAPSHOT_KEEP_CUSTOM + 3):
        save_snapshot(
            profiler, conn, {"i": i}, window_kind="custom",
            window_from=1000 + i * 10, window_to=2000 + i * 10,
        )
        conn.execute(
            f"UPDATE {table} SET created_at = ? WHERE window_from = ?",
            (1000 + i, 1000 + i * 10),
        )
        conn.commit()

    rows = conn.execute(
        f"SELECT window_from FROM {table} WHERE window_kind = 'custom' ORDER BY created_at DESC"
    ).fetchall()
    assert len(rows) == PROFILE_SNAPSHOT_KEEP_CUSTOM
    kept = {r["window_from"] for r in rows}
    assert 1000 + PROFILE_SNAPSHOT_KEEP_CUSTOM * 10 in kept   # 保留最新
    assert 1000 not in kept                                     # 最旧的被裁掉


@pytest.mark.parametrize("profiler_cls,table", PROFILER_TABLES)
def test_schema_version_blinds_old_rows(isolated_db, profiler_cls, table):
    """结构版本随行落库、读取处过滤：旧口径行（schema_version=0）失明——
    即便 created_at 更新也不得混入新口径结果（同 big5 的 prompt_version 机制）。"""
    conn = isolated_db
    profiler = profiler_cls()
    save_snapshot(profiler, conn, {"v": "当前"})
    # 旧行改成版本 0 且 created_at 最大：缺版本过滤时会赢得「最新」读取
    conn.execute(
        f"UPDATE {table} SET schema_version = 0, created_at = 9999 WHERE profile_json LIKE '%当前%'"
    )
    save_snapshot(profiler, conn, {"v": "最新"}, window_from=30, window_to=40)
    conn.commit()

    cached = profiler.get_profile("老朋友", "wxid_me")
    assert cached["profile"] == {"v": "最新"}
    assert [s["profile"] for s in profiler.list_snapshots("老朋友", account_wxid="wxid_me")] == [
        {"v": "最新"}
    ]


@pytest.mark.parametrize("profiler_cls", [ContactProfiler, SelfProfiler])
def test_list_snapshots_skips_corrupt_rows(isolated_db, profiler_cls):
    """损坏/空 profile_json 残行不进列表——回廊不该展示空画像卡。"""
    conn = isolated_db
    profiler = profiler_cls()
    save_snapshot(profiler, conn, {"ok": 1})
    save_snapshot(
        profiler, conn, {"bad": 1}, window_kind="custom", window_from=1, window_to=2
    )
    conn.execute("UPDATE contact_profiles SET profile_json = '' WHERE window_from = 1"
                 if profiler_cls is ContactProfiler else
                 "UPDATE self_profiles SET profile_json = '' WHERE window_from = 1")
    conn.commit()

    snapshots = profiler.list_snapshots("老朋友", account_wxid="wxid_me")
    assert [s["profile"] for s in snapshots] == [{"ok": 1}]


# ==================== origin 来源列（v5） ====================

@pytest.mark.parametrize("profiler_cls,table", PROFILER_TABLES)
def test_origin_column_defaults_and_persisted(isolated_db, profiler_cls, table, monkeypatch):
    """generate_profile 的 origin 透传落库：缺省 ''（滚动/手动指定窗）、
    演变段 'evolution'——快照列表靠它区分来源，不靠窗口形状猜。"""
    conn = isolated_db
    conv_id = seed_conversation(conn)
    add_msg(conn, conv_id, "窗内的消息内容", 1500)
    conn.commit()
    monkeypatch.setattr(
        profiler_cls, "_call_llm",
        lambda self, prompt, should_abort=None, account_wxid="": {"personality_tags": ["温和"]},
    )

    profiler_cls().generate_profile(
        "老朋友", account_wxid="wxid_me", from_ts=1000, to_ts=1600
    )
    profiler_cls().generate_profile(
        "老朋友", account_wxid="wxid_me", from_ts=1000, to_ts=2000, origin="evolution"
    )

    origins = [
        row[0] for row in conn.execute(
            f"SELECT origin FROM {table} ORDER BY created_at"
        )
    ]
    assert origins == ["", "evolution"]

    snapshots = profiler_cls().list_snapshots("老朋友", account_wxid="wxid_me")
    assert {s["origin"] for s in snapshots} == {"", "evolution"}


# ==================== 窗口覆盖比（徽标三件套） ====================

def test_window_coverage_ratio(isolated_db):
    """窗口文本消息数 / 全会话文本消息数（3 位小数）；非文本与空白不计；
    查不到会话或缺参返回 None（前端隐藏该项）。"""
    conn = isolated_db
    conv_id = seed_conversation(conn)
    add_msg(conn, conv_id, "窗内消息", 1000)
    add_msg(conn, conv_id, "窗外的旧消息", 500)
    conn.execute(
        "INSERT INTO messages (conversation_id, talker, is_sender, message_type, content, timestamp, created_at)"
        " VALUES (?, 'wxid_friend', 0, 3, '[图片]', 1200, 1200)",  # 非文本不计
        (conv_id,),
    )
    conn.execute(
        "INSERT INTO messages (conversation_id, talker, is_sender, message_type, content, timestamp, created_at)"
        " VALUES (?, 'wxid_friend', 0, 1, '   ', 1300, 1300)",     # 空白不计
        (conv_id,),
    )
    conn.commit()

    from app.webview.api.profile import _window_coverage
    assert _window_coverage(conv_id, 800, 1100) == 0.5   # 罩 1/2
    assert _window_coverage(conv_id, 400, 2000) == 1.0   # 全罩
    assert _window_coverage(999, 0, 100) is None          # 无该会话消息
    assert _window_coverage(conv_id, 0, 0) is None        # 缺窗参数


# ==================== custom 时间窗 ====================

@pytest.mark.parametrize("profiler_cls", [ContactProfiler, SelfProfiler])
def test_custom_window_samples_hard_boundary(isolated_db, profiler_cls, monkeypatch):
    """custom 窗闭区间采样：只取窗内消息，内容不足也不向更早顺延。"""
    conn = isolated_db
    conv_id = seed_conversation(conn)
    add_msg(conn, conv_id, "窗外的旧消息", 500)       # 早于窗 → 顺延也不该进样本
    add_msg(conn, conv_id, "窗内消息甲", 1000)        # 边界起点（闭区间）
    add_msg(conn, conv_id, "窗内消息乙", 2000)        # 边界终点（闭区间）
    add_msg(conn, conv_id, "窗外的新消息", 3000)      # 晚于窗
    conn.commit()

    monkeypatch.setattr(
        profiler_cls, "_call_llm",
        lambda self, prompt, should_abort=None, account_wxid="": {"personality_tags": ["温和"]},
    )
    result = profiler_cls().generate_profile(
        "老朋友", account_wxid="wxid_me", from_ts=1000, to_ts=2000
    )
    assert result["ok"] is True

    table = "contact_profiles" if profiler_cls is ContactProfiler else "self_profiles"
    row = conn.execute(
        f"SELECT window_kind, window_from, window_to FROM {table} WHERE display_name = '老朋友'"
    ).fetchone()
    assert row["window_kind"] == "custom"
    assert (row["window_from"], row["window_to"]) == (1000, 2000)


def test_custom_window_empty_returns_error(isolated_db, monkeypatch):
    """窗内没有文本消息：硬报错提示调整窗口，不顺延也不落快照。"""
    conn = isolated_db
    conv_id = seed_conversation(conn)
    add_msg(conn, conv_id, "只有窗外消息", 5000)
    conn.commit()
    monkeypatch.setattr(
        ContactProfiler, "_call_llm",
        lambda self, prompt, should_abort=None, account_wxid="": {"personality_tags": []},
    )
    ContactProfiler()._ensure_table(conn)  # 先建表，断言「失败不落快照」才有意义

    result = ContactProfiler().generate_profile(
        "老朋友", account_wxid="wxid_me", from_ts=1000, to_ts=2000
    )
    assert result["ok"] is False
    assert "时间窗" in result["error"]
    assert conn.execute("SELECT COUNT(*) FROM contact_profiles").fetchone()[0] == 0


@pytest.mark.parametrize("from_ts,to_ts,desc", [
    (2000, 1000, "起点晚于终点"),
    (0, 1000, "起点非正"),
    (1000, int(time.time()) + 10 * 86400, "终点太靠未来"),
])
def test_custom_window_guards(from_ts, to_ts, desc):
    """custom 窗防呆三例：均直接拒绝，不触库不调 LLM。（不设跨度上限——
    按调用方切分的时窗如实生成，采样量按档位固定，窗口长只影响粒度。）"""
    result = ContactProfiler().generate_profile(
        "老朋友", from_ts=from_ts, to_ts=to_ts
    )
    assert result["ok"] is False, desc
    assert "时间窗" in result["error"]


# ==================== 特征同窗化 ====================

@pytest.mark.parametrize("profiler_cls", [ContactProfiler, SelfProfiler])
def test_collect_features_windowed(isolated_db, profiler_cls):
    """窗口内特征只统计 [from,to]：initiative 按 sessions.start_time、响应时间
    JOIN messages.timestamp、字数按窗口内消息；好感度带全时段口径标注。"""
    conn = isolated_db
    conv_id = seed_conversation(conn)
    in_user = add_msg(conn, conv_id, "哈哈", 1500, is_sender=1)
    add_msg(conn, conv_id, "你好呀朋友", 1600, is_sender=0)
    out_user = add_msg(conn, conv_id, "窗外的长消息内容", 5000, is_sender=1)
    # 会话：窗内对方发起 / 窗外我方发起
    conn.execute(
        "INSERT INTO sessions (conversation_id, start_time, end_time, message_count, initiator, created_at)"
        " VALUES (?, 1200, 1300, 2, 'other', 1)",
        (conv_id,),
    )
    conn.execute(
        "INSERT INTO sessions (conversation_id, start_time, end_time, message_count, initiator, created_at)"
        " VALUES (?, 5000, 5100, 2, 'user', 1)",
        (conv_id,),
    )
    # 响应时间：窗内 30s / 窗外 300s
    conn.execute(
        "INSERT INTO response_times (conversation_id, sent_message_id, reply_message_id, response_time_seconds, is_abnormal, created_at)"
        " VALUES (?, ?, ?, 30, 0, 1)",
        (conv_id, in_user, in_user),
    )
    conn.execute(
        "INSERT INTO response_times (conversation_id, sent_message_id, reply_message_id, response_time_seconds, is_abnormal, created_at)"
        " VALUES (?, ?, ?, 300, 0, 1)",
        (conv_id, out_user, out_user),
    )
    from app.services.analysis.affinity_analysis_service import AffinityAnalysisService
    conn.execute(
        "INSERT INTO affinity_scores (conversation_id, analysis_version, overall_score,"
        " emotional_resonance_score, chat_positivity_score, attitude_tendency_score,"
        " preference_compatibility_score, message_count, interaction_pair_count, created_at)"
        " VALUES (?, ?, 80, 80, 80, 80, 80, 10, 5, 1)",
        (conv_id, AffinityAnalysisService.CALIBER_VERSION),
    )
    conn.commit()

    features = profiler_cls()._collect_features(conn, conv_id, 1000, 2000)
    assert features["initiative"]["total_sessions"] == 1
    assert features["initiative"]["initiative_rate"] == 1.0
    assert features["response_time"]["count"] == 1
    assert features["response_time"]["avg_seconds"] == 30
    assert features["word_counts"] == {"user_chars": 2, "other_chars": 5, "ratio": 2.5}
    assert features["affinity"]["caliber"] == "full_period"

    # 不带窗（缺省 0）为全时段口径，窗外数据纳入
    full = profiler_cls()._collect_features(conn, conv_id)
    assert full["initiative"]["total_sessions"] == 2
    assert full["response_time"]["count"] == 2
    assert full["word_counts"]["user_chars"] == 2 + len("窗外的长消息内容")


# ==================== 续期保档位 ====================

def test_renew_profiles_keeps_budget_level(isolated_db, monkeypatch):
    """后台续期沿用各自 rolling 快照的原生成档位，不回落 medium。"""
    conn = isolated_db
    seed_conversation(conn)
    save_snapshot(ContactProfiler(), conn, {"a": 1}, budget_level="high")
    save_snapshot(SelfProfiler(), conn, {"b": 2}, budget_level="low")

    calls = []
    monkeypatch.setattr(
        ContactProfiler, "generate_profile",
        lambda self, name, budget_level="medium", *a, **kw:
            calls.append(("contact", budget_level)) or {"ok": True},
    )
    monkeypatch.setattr(
        SelfProfiler, "generate_profile",
        lambda self, name, budget_level="medium", *a, **kw:
            calls.append(("self", budget_level)) or {"ok": True},
    )

    import app.services.realtime.generation_context as gc
    gc.renew_profiles_in_background("老朋友", "wxid_me")

    deadline = time.time() + 5
    while "wxid_me:老朋友" in gc._profile_renewal_inflight and time.time() < deadline:
        time.sleep(0.01)
    assert calls == [("contact", "high"), ("self", "low")]


# ==================== relationship_policy rolling 过滤 ====================

def test_relationship_policy_reads_rolling_only(isolated_db):
    """关系状态推导只读 rolling 快照：更新的 custom 快照不得污染实时链路。"""
    conn = isolated_db
    save_snapshot(ContactProfiler(), conn, {"kind": "rolling"}, window_kind="rolling")
    save_snapshot(
        ContactProfiler(), conn, {"kind": "custom"},
        window_kind="custom", window_from=1, window_to=2,
    )
    # custom 更晚生成：若缺 rolling 过滤，ORDER BY 最新会错误读到它
    conn.execute(
        "UPDATE contact_profiles SET created_at = 9999 WHERE window_kind = 'custom'"
    )
    conn.commit()

    from app.services.realtime.rag.relationship_policy import _load_profile_cache
    cache = _load_profile_cache("wxid_me", "老朋友", conn=conn)
    assert cache is not None
    assert cache["profile"] == {"kind": "rolling"}
