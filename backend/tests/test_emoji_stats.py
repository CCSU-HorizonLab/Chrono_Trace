"""表情包统计服务测试（docs/product-redesign-2026-11.md §6.1）。"""

import json
import os
import sqlite3
import sys
import time
from typing import Any

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import app.services.analysis.emoji_stats_service as ess


def _make_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        "CREATE TABLE messages (id INTEGER PRIMARY KEY AUTOINCREMENT, conversation_id INTEGER,"
        " is_sender INTEGER, message_type INTEGER, content TEXT, timestamp INTEGER)"
    )
    conn.execute(
        "CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT, updated_at TEXT)"
    )
    return conn


@pytest.fixture
def db(monkeypatch):
    conn = _make_db()
    monkeypatch.setattr("app.db.connection.get_db", lambda: conn)
    yield conn
    conn.close()


def _msg(conn, is_sender: int, mtype: int, content: str, ts: int):
    conn.execute(
        "INSERT INTO messages(conversation_id, is_sender, message_type, content, timestamp)"
        " VALUES (1, ?, ?, ?, ?)",
        (is_sender, mtype, content, ts),
    )


class TestExtractUnicodeEmojis:
    def test_plain_text_and_placeholder_not_emoji(self):
        assert ess.extract_unicode_emojis("普通中文abc123[呲牙]") == []

    def test_single_and_duplicate(self):
        assert ess.extract_unicode_emojis("哈哈😂😂") == ["😂", "😂"]

    def test_variation_selector_merged_in_key(self):
        clusters = ess.extract_unicode_emojis("❤️⭐️")
        assert len(clusters) == 2
        assert ess._cluster_key(clusters[0]) == ess._cluster_key("❤")

    def test_zwj_sequence_kept_whole(self):
        # 家庭/ZWJ 组合表情不得拆成单表情（拆开会重复计数）
        assert ess.extract_unicode_emojis("👨‍👩‍👧‍👦到齐") == ["👨‍👩‍👧‍👦"]

    def test_skin_tone_attached(self):
        assert ess.extract_unicode_emojis("👍🏽") == ["👍🏽"]

    def test_keycap(self):
        assert ess.extract_unicode_emojis("1️⃣2️⃣上分") == ["1️⃣", "2️⃣"]

    def test_regional_pair_flag(self):
        assert ess.extract_unicode_emojis("🇨🇳") == ["🇨🇳"]

    def test_text_symbols_excluded(self):
        # 几何/杂项符号区的 text-presentation 默认项是标点不是表情（实测污染 Top）
        assert ess.extract_unicode_emojis("●重点◎注意☆星号→方向") == []


class TestExtractCustomAndBuiltin:
    def test_custom_md5_attr(self):
        md5 = "a1b2c3d4e5f60718293a4b5c6d7e8f90"
        xml = f'<msg><emoji md5="{md5}" type="2"/></msg>'
        assert ess.extract_custom_emoji(xml, 47) == md5

    def test_custom_bare_hex(self):
        md5 = "ffffffffffffffffffffffffffffffff"
        assert ess.extract_custom_emoji(f"prefix {md5} suffix", 47) == md5

    def test_custom_placeholder_to_anonymous(self):
        # V4 压缩通道解不出原文时 content 是 [表情] 占位——落匿名桶而非丢弃
        assert ess.extract_custom_emoji("[表情]", 47) == ess.ANONYMOUS_CUSTOM_KEY

    def test_non_47_not_custom(self):
        assert ess.extract_custom_emoji("😂", 1) is None

    def test_builtin_words(self):
        # [动画表情] 是 47 类媒体占位无表情语义，不进 builtin 统计
        assert ess.extract_builtin_placeholders("你[呲牙]我[偷笑][动画表情]") == ["呲牙", "偷笑"]

    def test_builtin_wordlist_shared_with_cleaning(self):
        # 词表单一来源：清洗认的表情统计也认（import 而非复制）
        from app.services.analysis.preprocessing.cleaning import EMOJI_PLACEHOLDER_WORDS

        for word in EMOJI_PLACEHOLDER_WORDS:
            assert ess.extract_builtin_placeholders(f"[{word}]") == [word]


class TestCollectStats:
    def _seed(self, conn):
        t0 = int(time.time()) - 86400 * 40  # 上月
        t1 = int(time.time()) - 3600  # 本月深夜 23 点附近则不保证，仅做月桶断言
        _msg(conn, 1, 1, "哈哈😂😂[呲牙]", t0)
        _msg(conn, 0, 1, "你好[偷笑]", t0 + 60)
        _msg(conn, 0, 47, '<msg><emoji md5="a1b2c3d4e5f60718293a4b5c6d7e8f90"/></msg>', t0 + 120)
        _msg(conn, 1, 47, '[表情]', t1)
        _msg(conn, 0, 1, "无表情纯文本", t1 + 60)

    def test_top_sides_and_kinds(self, db):
        self._seed(db)
        snap = ess.collect_emoji_stats(1)
        me_unicode = {i["key"]: i["count"] for i in snap["top_me"]["unicode"]}
        ta_builtin = {i["key"]: i["count"] for i in snap["top_ta"]["builtin"]}
        assert me_unicode["😂"] == 2
        assert ta_builtin["偷笑"] == 1
        assert {i["key"]: i["count"] for i in snap["top_me"]["builtin"]}["呲牙"] == 1

    def test_custom_wall_and_anonymous(self, db):
        self._seed(db)
        snap = ess.collect_emoji_stats(1)
        assert len(snap["custom_wall"]) == 1
        wall = snap["custom_wall"][0]
        assert wall["md5"] == "a1b2c3d4e5f60718293a4b5c6d7e8f90"
        assert wall["count"] == 1 and wall["count_ta"] == 1
        assert snap["custom_anonymous"]["me"] == 1  # [表情] 占位的 47 类
        assert snap["custom_anonymous"]["ta"] == 0

    def test_months_and_hourly(self, db):
        self._seed(db)
        snap = ess.collect_emoji_stats(1)
        assert len(snap["months"]) == 2  # 上月 + 本月
        assert sum(snap["hourly"]) == 4  # 命中表情的消息数（纯文本不计）
        assert snap["peak_count"] == max(snap["hourly"])

    def test_scanned_counts_all_messages(self, db):
        self._seed(db)
        snap = ess.collect_emoji_stats(1)
        assert snap["scanned_messages"] == 5

    def test_window_excludes_outside(self, db):
        # 年度报告/纪念册按窗口取表情页：窗口外的消息不进榜不计数
        self._seed(db)
        t0 = int(time.time()) - 86400 * 40
        snap = ess.collect_emoji_stats(1, from_ts=t0 - 3600, to_ts=t0 + 3600)
        assert snap["scanned_messages"] == 3
        me_unicode = {i["key"]: i["count"] for i in snap["top_me"]["unicode"]}
        assert me_unicode["😂"] == 2  # 窗口内两条 😂
        assert snap["custom_anonymous"]["me"] == 0  # [表情] 在窗口外（t1）


class TestSnapshotCache:
    def test_first_call_computes_and_caches(self, db):
        _msg(db, 1, 1, "😂", int(time.time()))
        calls = []
        orig = ess.collect_emoji_stats
        db_wrapper = db

        def counting(conversation_id):
            calls.append(conversation_id)
            return orig(conversation_id)

        ess.collect_emoji_stats = counting
        try:
            s1 = ess.get_emoji_stats(1)
            s2 = ess.get_emoji_stats(1)
        finally:
            ess.collect_emoji_stats = orig
        assert calls == [1]  # 第二次走缓存
        assert s2 == s1
        row = db.execute(
            "SELECT value FROM settings WHERE key = 'emoji_stats_v1_1'"
        ).fetchone()
        assert row and json.loads(row[0])["fingerprint"] == s1["fingerprint"]

    def test_new_message_invalidates(self, db):
        _msg(db, 1, 1, "😂", int(time.time()))
        ess.get_emoji_stats(1)
        _msg(db, 0, 1, "🥰", int(time.time()) + 10)
        snap = ess.get_emoji_stats(1)
        ta_keys = {i["key"] for i in snap["top_ta"]["unicode"]}
        assert "🥰" in ta_keys

    def test_equal_delete_insert_invalidates(self, db):
        # 等量删插：删一条旧消息再插一条同时间戳新消息，计数与 max 都
        # 不变——指纹带 SUM(id) 兜底，缓存必须失效重算
        ts = int(time.time()) - 100
        _msg(db, 1, 1, "😂", ts)
        ess.get_emoji_stats(1)
        db.execute("DELETE FROM messages WHERE conversation_id = 1")
        _msg(db, 0, 1, "🥰", ts)  # 同计数、同 max_ts，内容已换
        db.commit()
        snap = ess.get_emoji_stats(1)
        ta_keys = {i["key"] for i in snap["top_ta"]["unicode"]}
        me_keys = {i["key"] for i in snap["top_me"]["unicode"]}
        assert "🥰" in ta_keys and "😂" not in me_keys

    def test_force_refresh(self, db):
        _msg(db, 1, 1, "😂", int(time.time()))
        ess.get_emoji_stats(1)
        ess.get_emoji_stats(1, force_refresh=True)  # 不炸即过，缓存重写

    def test_empty_conversation(self, db):
        assert ess.get_emoji_stats(999) == {"ok": False, "reason": "no_messages"}


class TestRhythmLabel:
    def test_windows(self):
        assert "深夜" in ess.hour_window_label(23)
        assert "凌晨" in ess.hour_window_label(2)
        assert "下午" in ess.hour_window_label(15)
