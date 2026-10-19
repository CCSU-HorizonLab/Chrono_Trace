"""画像长期事实注入测试（RAG 事实层 → 画像 prompt【长期记忆事实】块）。

覆盖：取数口径（链顶过滤/置信排序/条数截断/表缺失降级）、块渲染、
双 profiler prompt 注入、schema v3。
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
from app.services.realtime.profile_facts import (
    PROFILE_FACT_INJECT_LIMIT,
    collect_profile_facts,
    render_facts_block,
)
from app.services.realtime.rag.store import RagStore
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


NOW = 1_780_000_000


@pytest.fixture(autouse=True)
def _rag_enabled_on(monkeypatch):
    """钉死 RAG 开关：load_rag_settings 读真实 settings.json，测试不得依赖环境。"""
    monkeypatch.setattr(
        "app.services.realtime.rag.config.load_rag_settings",
        lambda: {"rag_enabled": True},
    )


def seed_fact(conn, content, confidence=0.8, status="active", enabled=1, as_of=NOW, updated_at=NOW, sensitivity="normal"):
    conn.execute(
        """
        INSERT INTO rag_facts
        (account_wxid, conversation_id, subject, kind, content, status, as_of,
         confidence, sensitivity, enabled, created_at, updated_at)
        VALUES ('wxid_me', 1, 'friend', 'hobby', ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (content, status, as_of, confidence, sensitivity, enabled, updated_at, updated_at),
    )


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
    return conn.execute(
        """
        INSERT INTO messages
        (conversation_id, talker, is_sender, message_type, content, timestamp, created_at)
        VALUES (?, 'wxid_friend', ?, 1, ?, ?, ?)
        """,
        (conv_id, is_sender, content, ts, ts),
    ).lastrowid


class TestCollectFacts:
    def test_chain_top_only_and_confidence_order(self, isolated_db):
        """superseded/uncertain/禁用/敏感不取；置信优先；条数截断。"""
        RagStore(isolated_db)  # 建 rag_facts 表（RAG 侧自建，schema.sql 无）
        seed_fact(isolated_db, "高置信事实", confidence=0.95)
        seed_fact(isolated_db, "次置信事实", confidence=0.70)
        seed_fact(isolated_db, "被演变链取代", confidence=0.99, status="superseded")
        seed_fact(isolated_db, "质量隔离", confidence=0.99, status="uncertain")
        seed_fact(isolated_db, "用户禁用", confidence=0.99, enabled=0)
        seed_fact(isolated_db, "健康隐私", confidence=0.99, sensitivity="sensitive")
        seed_fact(isolated_db, "老库NULL敏感位", confidence=0.98, sensitivity=None)
        isolated_db.commit()

        contents = [f["content"] for f in collect_profile_facts(isolated_db, "wxid_me", 1)]
        # sensitive 排除（对齐检索通道红线）；NULL 敏感位按 normal 保留
        assert "健康隐私" not in contents
        assert contents == ["老库NULL敏感位", "高置信事实", "次置信事实"]

    def test_limit_truncates(self, isolated_db):
        RagStore(isolated_db)
        for i in range(PROFILE_FACT_INJECT_LIMIT + 5):
            seed_fact(isolated_db, f"事实{i}", confidence=0.5 + i * 0.001)
        isolated_db.commit()

        facts = collect_profile_facts(isolated_db, "wxid_me", 1)
        assert len(facts) == PROFILE_FACT_INJECT_LIMIT
        # 置信随 i 递增：低置信端（i=0..4）被截掉，最高置信在列
        contents = [f["content"] for f in facts]
        assert "事实0" not in contents and "事实4" not in contents
        assert "事实28" in contents

    def test_blank_content_excluded_in_sql(self, isolated_db):
        """空白 content 在 SQL 层排除——不占 LIMIT 槽位挤出真事实。"""
        RagStore(isolated_db)
        seed_fact(isolated_db, "   ")
        seed_fact(isolated_db, "真事实", confidence=0.6)
        isolated_db.commit()
        assert collect_profile_facts(isolated_db, "wxid_me", 1, limit=1) == [
            {"content": "真事实", "as_of": NOW, "confidence": 0.6}
        ]

    def test_multiline_content_flattened(self, isolated_db):
        """多行事实压平单行，防破坏列表结构被 LLM 误读为指令。"""
        RagStore(isolated_db)
        seed_fact(isolated_db, "第一行\n第二行  带连续空格")
        isolated_db.commit()
        facts = collect_profile_facts(isolated_db, "wxid_me", 1)
        assert facts[0]["content"] == "第一行 第二行 带连续空格"

    def test_rag_disabled_skips_injection(self, isolated_db, monkeypatch):
        """rag_enabled 关闭即不注入（用户关记忆的预期：不参与任何远程交互）。"""
        RagStore(isolated_db)
        seed_fact(isolated_db, "事实")
        isolated_db.commit()
        monkeypatch.setattr(
            "app.services.realtime.rag.config.load_rag_settings",
            lambda: {"rag_enabled": False},
        )
        assert collect_profile_facts(isolated_db, "wxid_me", 1) == []

    def test_missing_table_degrades_to_empty(self, isolated_db):
        """rag_facts 表不存在（未跑过 RAG 的库）静默降级。"""
        assert collect_profile_facts(isolated_db, "wxid_me", 1) == []

    def test_hard_pii_redacted_before_injection(self, isolated_db):
        """硬 PII 注入前被规则脱敏换占位符——事实存的是未脱敏原文，画像
        LLM 链路无脱敏环节，全时段记忆不得明文出网。"""
        RagStore(isolated_db)
        seed_fact(isolated_db, "TA 的手机号 13812345678 常联系", confidence=0.9)
        seed_fact(isolated_db, "普通事实不带 PII", confidence=0.8)
        isolated_db.commit()

        contents = [f["content"] for f in collect_profile_facts(isolated_db, "wxid_me", 1)]
        joined = "\n".join(contents)
        assert "13812345678" not in joined
        assert "[PHONE_" in joined  # 占位符按值哈希稳定
        assert "普通事实不带 PII" in contents  # 无 PII 事实原样保留

    def test_redaction_failure_drops_fact(self, isolated_db, monkeypatch):
        """脱敏异常 fail-closed：丢条不注入，不让未脱敏原文出网。"""
        RagStore(isolated_db)
        seed_fact(isolated_db, "事实甲", confidence=0.9)
        seed_fact(isolated_db, "事实乙", confidence=0.8)
        isolated_db.commit()

        def _boom(self, text, **kw):
            raise RuntimeError("redactor down")

        monkeypatch.setattr(
            "app.services.realtime.privacy_redactor.PrivacyRedactor.redact", _boom
        )
        assert collect_profile_facts(isolated_db, "wxid_me", 1) == []


class TestRenderBlock:
    def test_render_lines(self):
        block = render_facts_block([
            {"content": "对方喜欢玩卡牌游戏", "as_of": NOW, "confidence": 0.92},
            {"content": "对方养了一只猫", "as_of": 0, "confidence": 0.75},
        ])
        assert block.startswith("【长期记忆事实】")
        assert "对方喜欢玩卡牌游戏（置信0.92，截至 " in block
        # as_of 缺省不带时间标注
        assert "对方养了一只猫（置信0.75）" in block
        assert "截至" not in block.split("对方养了一只猫")[1]

    def test_empty_returns_blank(self):
        assert render_facts_block([]) == ""


class TestPromptInjection:
    @pytest.mark.parametrize("profiler_cls", [ContactProfiler, SelfProfiler])
    def test_prompt_contains_facts_block(self, isolated_db, profiler_cls, monkeypatch):
        conv_id = seed_conversation(isolated_db)
        RagStore(isolated_db)
        seed_fact(isolated_db, "对方两年前就在玩某款游戏", confidence=0.9)
        isolated_db.commit()
        # 窗外历史消息（事实正是从这类全时段语料抽出的）
        add_message(isolated_db, conv_id, 0, "两年前的长消息" * 5, datetime(2024, 6, 1, 10, 0, 0).timestamp())
        add_message(isolated_db, conv_id, 1, "近期的消息", datetime(2026, 9, 1, 10, 0, 0).timestamp())
        isolated_db.commit()

        captured = {}

        def fake_call_llm(self, user_prompt, *args, **kwargs):
            captured["prompt"] = user_prompt
            return {"personality_tags": ["务实"], "summary": "测试画像"}

        monkeypatch.setattr(profiler_cls, "_call_llm", fake_call_llm)
        result = profiler_cls().generate_profile("老朋友", budget_level="high", account_wxid="wxid_me")

        assert result["ok"] is True
        assert "【长期记忆事实】" in captured["prompt"]
        assert "对方两年前就在玩某款游戏" in captured["prompt"]

    def test_no_facts_no_block(self, isolated_db, monkeypatch):
        conv_id = seed_conversation(isolated_db)
        add_message(isolated_db, conv_id, 1, "普通消息", datetime(2026, 9, 1, 10, 0, 0).timestamp())
        isolated_db.commit()

        captured = {}

        def fake_call_llm(self, user_prompt, *args, **kwargs):
            captured["prompt"] = user_prompt
            return {"personality_tags": ["务实"], "summary": "测试画像"}

        monkeypatch.setattr(ContactProfiler, "_call_llm", fake_call_llm)
        ContactProfiler().generate_profile("老朋友", budget_level="high", account_wxid="wxid_me")

        assert "【长期记忆事实】" not in captured["prompt"]


def test_schema_version_is_v3():
    # v3 = 长期记忆事实块（模块级常量，两 profiler 同值同升）
    assert contact_profiler_mod.PROFILE_SNAPSHOT_SCHEMA == 3
    assert self_profiler_mod.PROFILE_SNAPSHOT_SCHEMA == 3
