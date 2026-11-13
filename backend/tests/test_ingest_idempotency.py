"""导入幂等与对账测试——此前 `_insert_message_batch`（含 W1 对账）零测试覆盖。

增量导入的正确性地基：
- (conversation_id, local_id) 部分唯一索引 + INSERT OR IGNORE = 任意重放安全；
- local_id IS NULL 的实时行不受该索引约束（文档化现状）；
- realtime↔long 对账 ±59s 窗口去冗余；
- touched 才打脏（全 skip 的重复导入不误报 stale）；
- 老库（conversations 无分析新鲜度列）经兼容迁移自动补列。
"""

import time
from pathlib import Path

import pytest
import sys

backend_root = Path(__file__).parent.parent
sys.path.insert(0, str(backend_root))

from app.db.connection import DatabaseConnection, get_db
from app.services.analysis.preprocessing_orchestrator import PREPROCESSING_ALGO_VERSION
from app.services.wechat.ingest_service import WeChatIngestService


@pytest.fixture
def test_db(tmp_path):
    DatabaseConnection.close()
    DatabaseConnection._db_path = None
    conn = DatabaseConnection.initialize(str(tmp_path / "chrono_ingest.db"))
    yield conn
    DatabaseConnection.close()
    DatabaseConnection._db_path = None


def _msg(talker, local_id, content, ts, is_sender=0, message_type=1):
    return {
        "talker": talker,
        "local_id": local_id,
        "sender": talker,
        "is_sender": is_sender,
        "message_type": message_type,
        "content": content,
        "timestamp": ts,
    }


def _conv_id(username):
    return get_db().execute(
        "SELECT id FROM conversations WHERE username = ? AND platform = 'wechat'",
        (username,),
    ).fetchone()[0]


class TestInsertMessageBatchIdempotency:

    def test_first_insert_then_replay_all_skip(self, test_db):
        """首插计数正确；同批重放全跳过（local_id 幂等）。"""
        service = WeChatIngestService()
        batch = [
            _msg("wxid_a", 1, "消息一", 1_700_000_100),
            _msg("wxid_a", 2, "消息二", 1_700_000_200, is_sender=1),
            _msg("wxid_b", 1, "另一个会话", 1_700_000_300),
        ]
        cache, touched = {}, {}
        result = service._insert_message_batch(batch, "acct", cache, touched)
        assert result == {"inserted": 3, "skipped": 0}
        assert set(touched) == {_conv_id("wxid_a"), _conv_id("wxid_b")}

        # 重放：同 local_id 全部 OR IGNORE
        cache2, touched2 = {}, {}
        result2 = service._insert_message_batch(batch, "acct", cache2, touched2)
        assert result2 == {"inserted": 0, "skipped": 3}
        assert touched2 == {}, "全 skip 不应产生 touched（stale 误报来源）"

        total = get_db().execute("SELECT COUNT(*) FROM messages").fetchone()[0]
        assert total == 3

    def test_conversation_cache_reused(self, test_db):
        """同批内 conversation_cache 命中——会话只 INSERT OR IGNORE 一次。"""
        service = WeChatIngestService()
        batch = [_msg("wxid_a", i, f"消息{i}", 1_700_000_000 + i) for i in range(5)]
        cache, touched = {}, {}
        service._insert_message_batch(batch, "acct", cache, touched)
        assert list(cache.keys()) == ["wxid_a"], "同 talker 应复用缓存"

    def test_excluded_talker_skipped(self, test_db):
        """排除的系统账号（如 weixin/gh_）跳过且不建会话。"""
        service = WeChatIngestService()
        batch = [_msg("weixin", 1, "系统消息", 1_700_000_000)]
        result = service._insert_message_batch(batch, "acct", {}, {})
        assert result["skipped"] == 1
        row = get_db().execute(
            "SELECT 1 FROM conversations WHERE username = 'weixin'"
        ).fetchone()
        assert row is None

    def test_null_local_id_realtime_rows_not_constrained(self, test_db):
        """local_id NULL（实时行）不受部分唯一索引约束——同签名可多条并存。

        现状文档化：实时行幂等靠查询判重（monitor_service._message_exists_in_history），
        非 DB 约束；与 long 行的去冗余由对账逻辑负责。
        """
        db = get_db()
        db.execute(
            """
            INSERT INTO conversations
            (account_wxid, username, display_name, platform, created_at, updated_at)
            VALUES ('acct', 'wxid_a', 'A', 'wechat', 1, 1)
            """
        )
        conv = _conv_id("wxid_a")
        for _ in range(2):
            db.execute(
                """
                INSERT INTO messages
                (conversation_id, local_id, talker, is_sender, message_type,
                 content, timestamp, source, created_at)
                VALUES (?, NULL, 'wxid_a', 0, 1, '同样的实时消息', ?, 'realtime', ?)
                """,
                (conv, 1_700_000_050, int(time.time())),
            )
        db.commit()
        total = get_db().execute(
            "SELECT COUNT(*) FROM messages WHERE conversation_id = ?", (conv,)
        ).fetchone()[0]
        assert total == 2, "NULL local_id 行不受唯一索引约束（两条都应存在）"

    def test_reconcile_deletes_realtime_covered_by_long(self, test_db):
        """对账窗口 ±59s：窗内同签名 realtime 行删除，窗外保留。"""
        db = get_db()
        db.execute(
            """
            INSERT INTO conversations
            (account_wxid, username, display_name, platform, created_at, updated_at)
            VALUES ('acct', 'wxid_a', 'A', 'wechat', 1, 1)
            """
        )
        conv = _conv_id("wxid_a")

        def _add_realtime(local_null, content, ts):
            db.execute(
                """
                INSERT INTO messages
                (conversation_id, local_id, talker, is_sender, message_type,
                 content, timestamp, source, created_at)
                VALUES (?, NULL, 'wxid_a', 0, 1, ?, ?, 'realtime', ?)
                """,
                (conv, content, ts, int(time.time())),
            )

        _add_realtime(None, "窗口内的实时消息", 1_700_000_100)   # 与 long 行差 30s → 删
        _add_realtime(None, "窗口外的实时消息", 1_700_000_500)   # 差 400s → 留
        db.commit()

        service = WeChatIngestService()
        batch = [_msg("wxid_a", 1, "窗口内的实时消息", 1_700_000_130, is_sender=0)]
        service._insert_message_batch(batch, "acct", {}, {})

        rows = get_db().execute(
            "SELECT content FROM messages WHERE conversation_id = ? ORDER BY id",
            (conv,),
        ).fetchall()
        contents = [r["content"] for r in rows]
        assert contents.count("窗口内的实时消息") == 1, "窗内 realtime 行应被 long 行对账删除"
        assert "窗口外的实时消息" in contents, "窗外 realtime 行应保留"

    def test_refresh_conversation_stats(self, test_db):
        """touched 会话的 message_count/updated_at 重算（含 MAX 语义）。"""
        service = WeChatIngestService()
        batch = [
            _msg("wxid_a", 1, "早消息", 1_700_000_100),
            _msg("wxid_a", 2, "晚消息", 1_700_000_900, is_sender=1),
        ]
        touched = {}
        service._insert_message_batch(batch, "acct", {}, touched)
        conv = _conv_id("wxid_a")

        # 手动压低计数，验证 refresh 修正
        get_db().execute(
            "UPDATE conversations SET message_count = 0 WHERE id = ?", (conv,)
        )
        service._refresh_conversation_stats(touched)
        row = get_db().execute(
            "SELECT message_count, updated_at FROM conversations WHERE id = ?", (conv,)
        ).fetchone()
        assert row["message_count"] == 2
        # MAX(updated_at, batch_max)：会话创建时的 wall time 已大于批次时间戳时不回退
        assert row["updated_at"] >= 1_700_000_900


class TestStaleHookOnImport:

    def test_touched_marks_stale_and_drops_stats_cache(self, test_db):
        """有新插入消息：stale=1 且 preprocessing_stats 缓存行被删（陈旧 bug 修复）。"""
        service = WeChatIngestService()
        conv_cache, touched = {}, {}
        service._insert_message_batch(
            [_msg("wxid_a", 1, "消息", 1_700_000_100)], "acct", conv_cache, touched
        )
        conv = _conv_id("wxid_a")

        db = get_db()
        key = f"preprocessing_stats_v{PREPROCESSING_ALGO_VERSION}_{conv}"
        db.execute(
            "INSERT INTO settings (key, value, updated_at) VALUES (?, '{}', 1)", (key,)
        )
        # 模拟既有分析结果（stale=0）
        db.execute("UPDATE conversations SET analysis_stale = 0 WHERE id = ?", (conv,))
        db.commit()

        # 复刻 _import_messages_v4 尾部钩子序列
        service._refresh_conversation_stats(touched)
        from app.services.analysis.analysis_state import mark_conversations_stale

        mark_conversations_stale(touched.keys())

        row = db.execute(
            "SELECT analysis_stale FROM conversations WHERE id = ?", (conv,)
        ).fetchone()
        assert row["analysis_stale"] == 1
        assert db.execute(
            "SELECT 1 FROM settings WHERE key = ?", (key,)
        ).fetchone() is None

    def test_all_skip_keeps_stale_clear(self, test_db):
        """全 skip 的重复导入：touched 空 → 不打脏。"""
        service = WeChatIngestService()
        batch = [_msg("wxid_a", 1, "消息", 1_700_000_100)]
        service._insert_message_batch(batch, "acct", {}, {})
        conv = _conv_id("wxid_a")

        db = get_db()
        db.execute("UPDATE conversations SET analysis_stale = 0 WHERE id = ?", (conv,))
        db.commit()

        touched2 = {}
        service._insert_message_batch(batch, "acct", {}, touched2)
        assert touched2 == {}
        row = db.execute(
            "SELECT analysis_stale FROM conversations WHERE id = ?", (conv,)
        ).fetchone()
        assert row["analysis_stale"] == 0, "重复导入不应打脏"



class TestWatermarkOnFailedConversations:
    """会话失败与水位推进：失败会话窗口内消息不得被水位越过。"""

    def _run_import(self, monkeypatch, conversations, fail_usernames, watermark_ts=0):
        from unittest.mock import MagicMock
        import app.services.wechat.ingest_service as ingest_mod

        fake_db = MagicMock()
        fake_db.get_all_conversation_usernames.return_value = conversations

        def _get_messages(username, **_kwargs):
            if username in fail_usernames:
                raise RuntimeError("页面解密失败")
            base_ts = 1_700_000_000
            return [
                _msg(username, i, f"消息{i}", base_ts + i * 100)
                for i in range(1, 4)
            ]

        fake_db.get_messages.side_effect = _get_messages
        monkeypatch.setattr(ingest_mod, "MessageDBV4", lambda *a, **k: fake_db)
        service = WeChatIngestService()
        return service._import_messages_v4(
            ["/dev/null"], b"k" * 32, "wxid_me", "acct", 0,
            watermark_ts=watermark_ts,
        )

    def test_failed_conversation_freezes_watermark(self, monkeypatch, test_db):
        """有会话失败：水位冻结原值，失败区间留待下轮增量重扫。"""
        stats = self._run_import(
            monkeypatch,
            ["wxid_ok", "wxid_bad"], {"wxid_bad"},
            watermark_ts=1_699_000_000,
        )
        assert stats["failed_conversations"] == 1
        assert stats["total"] == 3
        # 成功会话已见最大 ts=1_700_000_300，但失败会话在场 → 不推进
        assert stats["watermark_ts"] == 1_699_000_000

    def test_watermark_advances_when_all_ok(self, monkeypatch, test_db):
        """全部成功：水位正常推进到本次最大 create_time。"""
        stats = self._run_import(
            monkeypatch, ["wxid_ok", "wxid_ok2"], set(),
            watermark_ts=1_699_000_000,
        )
        assert stats["failed_conversations"] == 0
        assert stats["watermark_ts"] == 1_700_000_300

    def test_full_import_failure_keeps_zero_watermark(self, monkeypatch, test_db):
        """首导（水位 0）即有失败：水位保持 0，下轮仍全量窗口重扫。"""
        stats = self._run_import(monkeypatch, ["wxid_bad"], {"wxid_bad"})
        assert stats["failed_conversations"] == 1
        assert stats["watermark_ts"] == 0


class TestChatroomDisplayName:
    """群成员 sender 显示名：contact 昵称映射优先、wxid 短名兜底。"""

    def test_name_map_hit_stores_display_name(self, test_db):
        """映射命中：sender 记备注/昵称（真名），消息内容剥前缀。"""
        service = WeChatIngestService()
        batch = [
            _msg("123@chatroom", 1, "wxid_abc123:\n群里说句话", 1_700_000_100),
        ]
        cache, touched = {}, {}
        service._insert_message_batch(
            batch, "acct", cache, touched,
            chatroom_names={"wxid_abc123": "张三"},
        )
        row = get_db().execute(
            "SELECT sender, content FROM messages WHERE conversation_id = ?",
            (_conv_id("123@chatroom"),),
        ).fetchone()
        assert row[0] == "张三"
        assert row[1] == "群里说句话"

    def test_name_map_miss_falls_back_to_wxid_short(self, test_db):
        """映射未命中/未提供：wxid 短名兜底（原行为不变）。"""
        service = WeChatIngestService()
        batch = [
            _msg("123@chatroom", 1, "wxid_abc123:\n没映射", 1_700_000_100),
            _msg("123@chatroom", 2, "wxid_def456:\n有空映射", 1_700_000_200),
        ]
        service._insert_message_batch(
            batch, "acct", {}, {},
            chatroom_names={"wxid_def456": "李四"},
        )
        senders = [
            r[0] for r in get_db().execute(
                "SELECT sender FROM messages WHERE conversation_id = ? ORDER BY local_id",
                (_conv_id("123@chatroom"),),
            )
        ]
        assert senders == ["abc123", "李四"]

    def test_resolve_display_name_priority(self):
        """纯函数：map 命中 > wxid 短名 > 纯数字短号兜底 > fallback。"""
        from app.services.wechat.chatroom import resolve_chatroom_display_name

        assert resolve_chatroom_display_name("wxid_x1", name_map={"wxid_x1": "备注名"}) == "备注名"
        assert resolve_chatroom_display_name("wxid_x1") == "x1"
        assert resolve_chatroom_display_name("987654321") == "成员4321"
        assert resolve_chatroom_display_name(None) == "成员"

class TestChatroomUsernamePrefix:
    """自定义微信号前缀（非 wxid_ 形态）：剥前缀 + 映射解析显示名。"""

    def test_username_prefix_stripped_and_mapped(self, test_db):
        """`wwmilk:\\n内容` 前缀剥除，sender 记映射昵称。"""
        service = WeChatIngestService()
        batch = [_msg("123@chatroom", 10, "wwmilk:\n这个可以有", 1_700_000_100)]
        service._insert_message_batch(
            batch, "acct", {}, {},
            chatroom_names={"wwmilk": "机智SOLO"},
        )
        row = get_db().execute(
            "SELECT sender, content FROM messages WHERE local_id = 10"
        ).fetchone()
        assert row[0] == "机智SOLO"
        assert row[1] == "这个可以有"

    def test_sender_without_prefix_also_mapped(self, test_db):
        """无前缀消息（sender 来自 Name2id 反查的 username）也过映射。"""
        service = WeChatIngestService()
        batch = [
            _msg("123@chatroom", 11, "系统提示文本", 1_700_000_200),
        ]
        batch[0]["sender"] = "lwj780123"
        service._insert_message_batch(
            batch, "acct", {}, {},
            chatroom_names={"lwj780123": "刘文江"},
        )
        row = get_db().execute(
            "SELECT sender FROM messages WHERE local_id = 11"
        ).fetchone()
        assert row[0] == "刘文江"

    def test_prefix_regex_forms(self):
        """三种前缀形态识别；普通文本不误伤。"""
        from app.services.wechat.chatroom import parse_chatroom_message

        roster = {"wwmilk", "qq454709763", "-987654", "987654321"}
        # wxid_ 形态特异，无条件剥
        assert parse_chatroom_message("wxid_abc123:\n你好")[0] == "wxid_abc123"
        # 字母自定义号/纯数字形态有歧义，命中花名册才剥
        assert parse_chatroom_message("wwmilk:\n这个可以有", roster) == ("wwmilk", "这个可以有")
        assert parse_chatroom_message("qq454709763:\n哦哦", roster) == ("qq454709763", "哦哦")
        assert parse_chatroom_message("-987654:\n嗯", roster)[0] == "-987654"
        # 无前缀正文原样返回（不以 :\n 结尾形态开头的文本不受影响）
        sid, text = parse_chatroom_message("就一句话")
        assert sid is None and text == "就一句话"

    def test_prefix_requires_roster_for_ambiguous_forms(self):
        """字母/纯数字前缀未命中花名册（或未提供）：不剥，正文原样。"""
        from app.services.wechat.chatroom import parse_chatroom_message

        roster = {"wwmilk"}
        # 白名单不含：Warning:/日期/手机号形态是普通正文，不可误伤
        assert parse_chatroom_message("Warning:\n系统警告正文", roster) == (None, "Warning:\n系统警告正文")
        assert parse_chatroom_message("20261113:\n那天记得", roster)[0] is None
        assert parse_chatroom_message("13800001111:\n打这个号码", roster)[0] is None
        # 白名单缺席（contact 库降级）：歧义形态一律不剥，wxid_ 仍工作
        assert parse_chatroom_message("wwmilk:\n这个可以有")[0] is None
        assert parse_chatroom_message("wxid_abc123:\n你好")[0] == "wxid_abc123"
