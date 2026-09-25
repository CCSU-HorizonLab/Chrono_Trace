"""db_snapshot（EncryptedShardWatcher）单测：加密库增量解密视图。

覆盖：初始全量解密可查询、stat 短路、源更新增量刷新、
主库缺帧页占位 + WAL 已提交帧修复、WAL 代际错乱防护、未提交帧不应用。
"""
from __future__ import annotations

import os
import sqlite3
import sys
from pathlib import Path

backend_root = Path(__file__).parent.parent
sys.path.insert(0, str(backend_root))
sys.path.insert(0, str(Path(__file__).parent))

import pytest

from app.services.wechat.db_snapshot import EncryptedShardWatcher
from fixtures.wcdb_factory import build_plain_db, build_wal, encrypt_db, encrypt_page, PAGE

KEY_HEX = "1a" * 32

SCHEMA_V1 = """
CREATE TABLE name2id (user_name TEXT PRIMARY KEY, is_session INTEGER DEFAULT 0);
CREATE TABLE [Msg_test] (
    local_id INTEGER PRIMARY KEY, server_id INTEGER, local_type INTEGER,
    sort_seq INTEGER, real_sender_id INTEGER, create_time INTEGER,
    message_content TEXT
);
INSERT INTO name2id(user_name, is_session) VALUES ('lishao378', 0), ('wxid_zhang', 1);
INSERT INTO [Msg_test] VALUES
    (1, 1001, 1, 1, 2, 1700000000, '早'),
    (2, 1002, 1, 2, 1, 1700000060, '嗯呢'),
    (3, 1003, 1, 3, 2, 1700000120, '中午吃啥');
"""

EXTRA_ROW = ("INSERT INTO [Msg_test] VALUES "
             "(4, 1004, 1, 4, 1, 1700000180, '晚上好');")


def _diff_page_no(data_a: bytes, data_b: bytes) -> int:
    """返回 v1→v2 中变化的首个非页1数据页页号（1 起）。"""
    assert len(data_a) == len(data_b), "fixture 布局应保持同页数"
    for off in range(PAGE, len(data_a), PAGE):
        if data_a[off:off + PAGE] != data_b[off:off + PAGE]:
            return off // PAGE + 1
    raise AssertionError("两个 fixture 版本没有数据页差异")


def test_initial_decrypt_produces_queryable_view(tmp_path):
    plain = build_plain_db(tmp_path / "plain.db", SCHEMA_V1)
    src = tmp_path / "message_0.db"
    encrypt_db(plain, src, KEY_HEX)

    watcher = EncryptedShardWatcher(src, KEY_HEX, tmp_path / "cache")
    try:
        rows = watcher.connection.execute(
            "SELECT message_content FROM [Msg_test] ORDER BY sort_seq"
        ).fetchall()
        assert [r[0] for r in rows] == ["早", "嗯呢", "中午吃啥"]
        # 页1 解密产物需补 16B SQLite 头才是合法库
        assert watcher.out_path.read_bytes()[:16] == b"SQLite format 3\x00"
        assert watcher.connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    finally:
        watcher.close()
    # close 清理解密产物
    assert not watcher.out_path.exists()


def test_refresh_short_circuits_when_source_unchanged(tmp_path):
    plain = build_plain_db(tmp_path / "plain.db", SCHEMA_V1)
    src = tmp_path / "message_0.db"
    encrypt_db(plain, src, KEY_HEX)
    watcher = EncryptedShardWatcher(src, KEY_HEX, tmp_path / "cache")
    try:
        assert watcher.refresh() is False  # (mtime,size) 未变 → 零开销短路
    finally:
        watcher.close()


def test_source_update_visible_after_incremental_refresh(tmp_path):
    plain_v1 = build_plain_db(tmp_path / "v1.db", SCHEMA_V1)
    src = tmp_path / "message_0.db"
    salt, _, _ = encrypt_db(plain_v1, src, KEY_HEX)
    watcher = EncryptedShardWatcher(src, KEY_HEX, tmp_path / "cache")
    try:
        plain_v2 = build_plain_db(tmp_path / "v2.db", SCHEMA_V1 + EXTRA_ROW)
        # 同盐重加密（盐随库固定；换盐等于换库）
        encrypt_db(plain_v2, src, KEY_HEX, salt=salt)
        st = src.stat()
        os.utime(src, ns=(st.st_atime_ns, st.st_mtime_ns + 2_000_000_000))

        assert watcher.refresh() is True
        rows = watcher.connection.execute(
            "SELECT message_content FROM [Msg_test] ORDER BY sort_seq"
        ).fetchall()
        assert [r[0] for r in rows] == ["早", "嗯呢", "中午吃啥", "晚上好"]
    finally:
        watcher.close()


def test_wal_committed_frame_repairs_missing_main_page(tmp_path):
    """主库缺帧页（HMAC 必然失败）占位后由 WAL 已提交帧修复——WAL 头/帧头大端格式。"""
    plain_v1 = build_plain_db(tmp_path / "v1.db", SCHEMA_V1)
    plain_v2 = build_plain_db(tmp_path / "v2.db", SCHEMA_V1 + EXTRA_ROW)
    data1 = plain_v1.read_bytes()
    data2 = plain_v2.read_bytes()
    page_no = _diff_page_no(data1, data2)

    src = tmp_path / "message_0.db"
    salt, enc_key, mac_key = encrypt_db(plain_v1, src, KEY_HEX)
    # 模拟 WAL 模式主库尾部缺帧页：该页密文为垃圾 → 解密失败 → 零占位
    with open(src, "r+b") as f:
        f.seek((page_no - 1) * PAGE)
        f.write(os.urandom(PAGE))

    frame = encrypt_page(data2[(page_no - 1) * PAGE:page_no * PAGE],
                         enc_key, mac_key, page_no)
    build_wal(tmp_path / "message_0.db-wal", [(page_no, frame, True)])

    watcher = EncryptedShardWatcher(src, KEY_HEX, tmp_path / "cache")
    try:
        rows = watcher.connection.execute(
            "SELECT message_content FROM [Msg_test] ORDER BY sort_seq"
        ).fetchall()
        assert [r[0] for r in rows] == ["早", "嗯呢", "中午吃啥", "晚上好"]
    finally:
        watcher.close()


def test_wal_frame_generation_mismatch_is_ignored(tmp_path):
    """帧 salt 与 wal 头不一致（上一轮 checkpoint 残留）：整帧不应用，宁少读不错读。"""
    plain_v1 = build_plain_db(tmp_path / "v1.db", SCHEMA_V1)
    plain_v2 = build_plain_db(tmp_path / "v2.db", SCHEMA_V1 + EXTRA_ROW)
    data1 = plain_v1.read_bytes()
    data2 = plain_v2.read_bytes()
    page_no = _diff_page_no(data1, data2)

    src = tmp_path / "message_0.db"
    _, enc_key, mac_key = encrypt_db(plain_v1, src, KEY_HEX)
    with open(src, "r+b") as f:
        f.seek((page_no - 1) * PAGE)
        f.write(os.urandom(PAGE))

    frame = encrypt_page(data2[(page_no - 1) * PAGE:page_no * PAGE],
                         enc_key, mac_key, page_no)
    build_wal(
        tmp_path / "message_0.db-wal", [(page_no, frame, True)],
        salt=(0x11111111, 0x22222222), frame_salt=(0x99999999, 0x88888888),
    )

    watcher = EncryptedShardWatcher(src, KEY_HEX, tmp_path / "cache")
    try:
        # 缺帧页保持零占位：该表数据页损坏，查询应报错而不是给出错的数据
        with pytest.raises(sqlite3.DatabaseError):
            watcher.connection.execute(
                "SELECT message_content FROM [Msg_test] ORDER BY sort_seq"
            ).fetchall()
    finally:
        watcher.close()


def test_wal_uncommitted_frames_are_not_applied(tmp_path):
    """最后一次 commit 帧之后的未提交帧不应用（宁少读不错读）。"""
    plain_v1 = build_plain_db(tmp_path / "v1.db", SCHEMA_V1)
    plain_v2 = build_plain_db(tmp_path / "v2.db", SCHEMA_V1 + EXTRA_ROW)
    data1 = plain_v1.read_bytes()
    data2 = plain_v2.read_bytes()
    page_no = _diff_page_no(data1, data2)

    src = tmp_path / "message_0.db"
    _, enc_key, mac_key = encrypt_db(plain_v1, src, KEY_HEX)
    with open(src, "r+b") as f:
        f.seek((page_no - 1) * PAGE)
        f.write(os.urandom(PAGE))

    frame = encrypt_page(data2[(page_no - 1) * PAGE:page_no * PAGE],
                         enc_key, mac_key, page_no)
    build_wal(tmp_path / "message_0.db-wal", [(page_no, frame, False)])  # 无 commit 帧

    watcher = EncryptedShardWatcher(src, KEY_HEX, tmp_path / "cache")
    try:
        with pytest.raises(sqlite3.DatabaseError):
            watcher.connection.execute(
                "SELECT message_content FROM [Msg_test] ORDER BY sort_seq"
            ).fetchall()
    finally:
        watcher.close()
