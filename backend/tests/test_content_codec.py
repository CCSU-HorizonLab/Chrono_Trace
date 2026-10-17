"""消息内容解码与 BLOB 归一迁移的单元测试。

背景：V4 库 content 混有 zstd 压缩 BLOB，旧链路 str(bytes) 产出
b'(\\xb5...' 式 repr 乱码混入 RAG 分段与问答引用；本套件覆盖
content_codec 的各解码分支与 connection 的一次性归一迁移。
"""

import os
import sqlite3
import sys


sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.db.connection import DatabaseConnection
from app.services.wechat.content_codec import (
    ZSTD_MAGIC,
    decode_message_content,
    looks_binary_text,
)


ZSTD_BLOB = ZSTD_MAGIC + b"\x00\x01\x02junkpayload"


class TestDecodeMessageContent:
    def test_none_returns_empty(self):
        assert decode_message_content(None) == ""

    def test_zstd_blob_type1_gives_compressed_text_placeholder(self):
        assert decode_message_content(ZSTD_BLOB, 1) == "[压缩消息]"

    def test_zstd_blob_unmasked_type_masks_first(self):
        # local_type 高 32 位带 flag：6*2^32+49 掩码后应为 49（链接/小程序）
        assert decode_message_content(ZSTD_BLOB, 6 * 4294967296 + 49) == "[链接/小程序]"

    def test_zstd_blob_media_type_gives_typed_placeholder(self):
        assert decode_message_content(ZSTD_BLOB, 3) == "[图片]"
        assert decode_message_content(ZSTD_BLOB, 43) == "[视频]"
        assert decode_message_content(ZSTD_BLOB, 10002) == "[系统消息]"

    def test_zstd_blob_unknown_type_gives_default_placeholder(self):
        assert decode_message_content(ZSTD_BLOB, 88) == "[媒体消息]"

    def test_zstd_blob_without_type_treated_as_text(self):
        assert decode_message_content(ZSTD_BLOB) == "[压缩消息]"

    def test_plain_utf8_bytes_decoded_as_text(self):
        assert decode_message_content("今晚吃火锅吗".encode("utf-8"), 1) == "今晚吃火锅吗"

    def test_non_utf8_bytes_gives_placeholder(self):
        assert decode_message_content(b"\xff\xfe\xfa", 43) == "[视频]"

    def test_utf8_but_binary_looking_bytes_gives_placeholder(self):
        # 旧链路 errors='ignore' 风格的可解码乱码：控制字符占比超三成
        garbage = ("\x00" * 30 + "ab").encode("utf-8")
        assert decode_message_content(garbage, 1) == "[压缩消息]"

    def test_str_passthrough(self):
        assert decode_message_content("普通消息", 1) == "普通消息"

    def test_binary_looking_str_gives_placeholder(self):
        assert decode_message_content("\x00\x01\x02" * 10 + "tail", 1) == "[压缩消息]"

    def test_short_string_never_flagged(self):
        # 短内容（表情、单字）不做乱码判定，避免误伤
        assert looks_binary_text("\x01\x02") is False
        assert decode_message_content("好", 1) == "好"


class TestMessageBlobMigration:
    def _fresh_db(self, tmp_path):
        DatabaseConnection.close()
        DatabaseConnection._db_path = None
        db_path = tmp_path / "blob_migrate.db"
        conn = DatabaseConnection.initialize(str(db_path))
        # initialize 已跑过一次空表迁移并落了标记，撤掉以便注入夹具后重放
        conn.execute("DELETE FROM settings WHERE key = 'migration_message_blob_normalized'")
        return conn

    def _insert_message(self, conn, content, message_type):
        cur = conn.execute(
            """
            INSERT INTO messages
            (conversation_id, talker, is_sender, message_type, content, timestamp, created_at)
            VALUES (1, 'wxid_a', 0, ?, ?, 1000, 1000)
            """,
            (message_type, content),
        )
        return cur.lastrowid

    def test_blob_rows_normalized_and_cache_purged(self, tmp_path):
        conn = self._fresh_db(tmp_path)
        try:
            id_zstd_text = self._insert_message(conn, ZSTD_BLOB, 1)
            id_zstd_link = self._insert_message(conn, ZSTD_BLOB, 49)
            id_plain = self._insert_message(conn, "正常中文".encode("utf-8"), 1)
            id_text_kept = self._insert_message(conn, "普通文本不动", 1)
            id_giant_type = self._insert_message(conn, ZSTD_BLOB, 5 * 4294967296 + 3)
            id_text_giant_type = self._insert_message(conn, "文本但类型带 flag", 4294967296 + 34)
            for mid in (id_zstd_text, id_text_kept):
                conn.execute(
                    "INSERT INTO sentiment_cache (message_id, polarity, intensity, created_at)"
                    " VALUES (?, 1, 0.5, 1)",
                    (mid,),
                )

            DatabaseConnection._migrate_message_blob_content(conn)

            rows = {
                row[0]: (row[1], row[2], row[3])
                for row in conn.execute("SELECT id, message_type, content, typeof(content) FROM messages")
            }
            assert rows[id_zstd_text] == (1, "[压缩消息]", "text")
            assert rows[id_zstd_link] == (49, "[链接/小程序]", "text")
            assert rows[id_plain] == (1, "正常中文", "text")
            assert rows[id_text_kept] == (1, "普通文本不动", "text")
            # 巨型 local_type 无论内容形态一并掩码
            assert rows[id_giant_type][0] == 3
            assert rows[id_giant_type][1] == "[图片]"
            assert rows[id_text_giant_type][0] == 34

            # 乱码 BLOB 的嵌入缓存清除，正常文本的保留
            cached = {
                row[0]
                for row in conn.execute("SELECT message_id FROM sentiment_cache")
            }
            assert id_text_kept in cached
            assert id_zstd_text not in cached

            # 标记落库
            flag = conn.execute(
                "SELECT value FROM settings WHERE key = 'migration_message_blob_normalized'"
            ).fetchone()
            assert flag is not None and flag[0] == "1"
        finally:
            DatabaseConnection.close()
            DatabaseConnection._db_path = None

    def test_migration_is_one_shot_via_flag(self, tmp_path):
        conn = self._fresh_db(tmp_path)
        try:
            DatabaseConnection._migrate_message_blob_content(conn)  # 空表跑一次，落标记
            self._insert_message(conn, ZSTD_BLOB, 1)

            DatabaseConnection._migrate_message_blob_content(conn)  # 有标记，应跳过

            kind = conn.execute(
                "SELECT typeof(content) FROM messages LIMIT 1"
            ).fetchone()[0]
            assert kind == "blob"
        finally:
            DatabaseConnection.close()
            DatabaseConnection._db_path = None

    def test_migration_failure_does_not_set_flag(self, tmp_path, monkeypatch):
        conn = self._fresh_db(tmp_path)
        try:
            self._insert_message(conn, ZSTD_BLOB, 1)

            def boom(content, message_type=None):
                raise RuntimeError("mock failure")

            # 迁移内延迟导入，monkeypatch 模块属性即可命中
            monkeypatch.setattr(
                "app.services.wechat.content_codec.decode_message_content", boom
            )
            DatabaseConnection._migrate_message_blob_content(conn)

            flag = conn.execute(
                "SELECT value FROM settings WHERE key = 'migration_message_blob_normalized'"
            ).fetchone()
            assert flag is None  # 失败不落标记，下次启动重试
        finally:
            DatabaseConnection.close()
            DatabaseConnection._db_path = None
