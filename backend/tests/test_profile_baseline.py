"""画像长期背景（全时段基线）测试。

覆盖：统计口径（分年/活跃天/深夜 CAST 整数比较/窗口覆盖比）、空表降级、
prompt【长期背景】块渲染与注入、schema v2。
"""

import sys
from datetime import datetime
from pathlib import Path

import pytest


backend_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(backend_dir))


from app.db.connection import DatabaseConnection
from app.services.realtime import contact_profiler as contact_profiler_mod
from app.services.realtime import self_profiler as self_profiler_mod
from app.services.realtime.contact_profiler import ContactProfiler
from app.services.realtime.profile_baseline import (
    collect_full_period_baseline,
    render_baseline_block,
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
    ).fetchone()["id"]


def add_message(conn, conv_id, is_sender, content, ts):
    cur = conn.execute(
        """
        INSERT INTO messages
        (conversation_id, talker, is_sender, message_type, content, timestamp, created_at)
        VALUES (?, 'wxid_friend', ?, 1, ?, ?, ?)
        """,
        (conv_id, is_sender, content, ts, ts),
    )
    return cur.lastrowid


class TestCollectBaseline:
    def test_stats_and_coverage(self, isolated_db):
        """跨两年语料：分年量/活跃天/深夜/窗口覆盖比。"""
        conv_id = seed_conversation(isolated_db)
        # 2024 两条（其一深夜 2:30 本地时构造）+ 2026 两条（其一非文本）
        t2024 = datetime(2024, 6, 1, 10, 0, 0).timestamp()
        t2024_late = datetime(2024, 6, 2, 2, 30, 0).timestamp()
        t2026 = datetime(2026, 9, 1, 10, 0, 0).timestamp()
        t2026b = datetime(2026, 9, 2, 11, 0, 0).timestamp()
        add_message(isolated_db, conv_id, 1, "早", t2024)
        add_message(isolated_db, conv_id, 0, "深夜消息", t2024_late)
        add_message(isolated_db, conv_id, 0, "近期的消息", t2026)
        add_message(isolated_db, conv_id, 1, "  ", t2026b)  # 空白文本不计
        isolated_db.commit()

        baseline = collect_full_period_baseline(isolated_db, conv_id, t2026, t2026 + 86400)
        assert baseline["text_total"] == 3
        assert baseline["text_user"] == 1
        assert baseline["text_other"] == 2
        assert baseline["active_days"] == 3
        assert baseline["yearly"] == [("2024", 2), ("2026", 1)]
        # 23 点字符串 BETWEEN 陷阱：只有 2:30 一条入深夜档
        assert baseline["late_night_ratio"] == pytest.approx(1 / 3)
        # 窗口只罩住 2026 那条
        assert baseline["window_text_count"] == 1
        assert baseline["window_coverage"] == pytest.approx(1 / 3)

    def test_empty_conversation_degrades(self, isolated_db):
        conv_id = seed_conversation(isolated_db)
        assert collect_full_period_baseline(isolated_db, conv_id, 0, 100) == {}
        assert render_baseline_block({}) == ""

    def test_render_block_lines(self):
        block = render_baseline_block({
            "first_date": "2024-04-16", "last_date": "2026-10-13",
            "span_days": 911, "active_days": 402,
            "text_total": 4506, "text_user": 2100, "text_other": 2406,
            "yearly": [("2024", 1830), ("2025", 2100)],
            "late_night_ratio": 0.12,
            "window_text_count": 436, "window_coverage": 0.097,
        })
        assert block.startswith("【长期背景】")
        assert "2024 年 1830 条 / 2025 年 2100 条" in block
        assert "深夜（0-5 点）消息占比: 12%" in block
        assert "全时段的 10%（436/4506 条）" in block


class TestPromptInjection:
    """generate_profile 链路注入【长期背景】块（LLM 打桩）。"""

    @pytest.fixture
    def seeded(self, isolated_db):
        conv_id = seed_conversation(isolated_db)
        old = datetime(2024, 6, 1, 10, 0, 0).timestamp()
        add_message(isolated_db, conv_id, 1, "两年前的长消息" * 5, old)
        add_message(isolated_db, conv_id, 0, "近期的消息", datetime(2026, 9, 1, 10, 0, 0).timestamp())
        isolated_db.commit()
        return isolated_db, conv_id

    @pytest.mark.parametrize("profiler_cls", [ContactProfiler, SelfProfiler])
    def test_prompt_contains_baseline(self, seeded, profiler_cls, monkeypatch):
        conn, _ = seeded
        captured = {}

        def fake_call_llm(self, user_prompt, *args, **kwargs):
            captured["prompt"] = user_prompt
            return {"personality_tags": ["务实"], "summary": "测试画像"}

        monkeypatch.setattr(profiler_cls, "_call_llm", fake_call_llm)
        profiler = profiler_cls()
        result = profiler.generate_profile("老朋友", budget_level="high", account_wxid="wxid_me")
        assert result["ok"] is True
        assert "【长期背景】" in captured["prompt"]
        assert "本次窗口样本覆盖" in captured["prompt"]

    def test_schema_version_is_v4(self):
        # 口径变更随行落库：v4 = 长期背景块 + 长期记忆事实块 + 关系章节摘要块（模块级常量，两 profiler 同值同升）
        assert contact_profiler_mod.PROFILE_SNAPSHOT_SCHEMA == 4
        assert self_profiler_mod.PROFILE_SNAPSHOT_SCHEMA == 4
