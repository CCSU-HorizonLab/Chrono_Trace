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
        key = f"preprocessing_stats_v2_{conv}"
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


class TestLegacyDbMigration:

    def test_old_conversations_get_analysis_columns(self, tmp_path):
        """老库（conversations 无分析新鲜度列）经兼容迁移自动补齐。"""
        import sqlite3

        db_path = tmp_path / "legacy.db"
        raw = sqlite3.connect(db_path)
        raw.executescript(
            """
            CREATE TABLE conversations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                account_wxid TEXT NOT NULL,
                username TEXT NOT NULL,
                display_name TEXT NOT NULL,
                platform TEXT DEFAULT 'wechat',
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL,
                message_count INTEGER DEFAULT 0,
                is_deleted INTEGER DEFAULT 0,
                UNIQUE(account_wxid, username, platform)
            );
            INSERT INTO conversations
                (account_wxid, username, display_name, created_at, updated_at)
            VALUES ('acct', 'legacy_user', '老数据', 1, 1);
            """
        )
        raw.commit()
        raw.close()

        DatabaseConnection.close()
        DatabaseConnection._db_path = None
        try:
            conn = DatabaseConnection.initialize(str(db_path))
            cols = {
                r[1] for r in conn.execute("PRAGMA table_info(conversations)").fetchall()
            }
            assert {"analysis_stale", "analysis_message_count", "analysis_watermark_ts"} <= cols

            row = conn.execute(
                "SELECT analysis_stale, analysis_message_count FROM conversations "
                "WHERE username = 'legacy_user'"
            ).fetchone()
            # 存量会话默认 1（新鲜度未知的诚实语义）
            assert row[0] == 1
            assert row[1] is None
        finally:
            DatabaseConnection.close()
            DatabaseConnection._db_path = None
