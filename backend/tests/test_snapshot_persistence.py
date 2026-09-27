"""db_snapshot sidecar 持久化测试：跨进程（重启）复用解密快照。

此前页哈希只在内存：进程重启后即使 .dec.db 还在磁盘上，也要全量重解
19 个分片（~40s）。sidecar 恢复后：源未变零解密；源已变增量解密；
错密钥/换库/损坏 sidecar 一律拒绝复用回退全量。
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

backend_root = Path(__file__).parent.parent
sys.path.insert(0, str(backend_root))
sys.path.insert(0, str(Path(__file__).parent))

import pytest

from app.services.wechat.db_snapshot import EncryptedShardWatcher
from fixtures.wcdb_factory import build_plain_db, encrypt_db, PAGE

KEY_HEX = "1a" * 32
WRONG_KEY_HEX = "2b" * 32

SCHEMA = """
CREATE TABLE name2id (user_name TEXT PRIMARY KEY, is_session INTEGER DEFAULT 0);
CREATE TABLE [Msg_test] (
    local_id INTEGER PRIMARY KEY, server_id INTEGER, local_type INTEGER,
    sort_seq INTEGER, real_sender_id INTEGER, create_time INTEGER,
    message_content TEXT
);
INSERT INTO name2id(user_name, is_session) VALUES ('lishao378', 0), ('wxid_zhang', 1);
INSERT INTO [Msg_test] VALUES
    (1, 1001, 1, 1, 2, 1700000000, '早'),
    (2, 1002, 1, 2, 1, 1700000060, '嗯呢');
"""

EXTRA = "INSERT INTO [Msg_test] VALUES (3, 1003, 1, 3, 2, 1700000120, '中午吃啥');"


def _rows(watcher) -> list:
    return [r[0] for r in watcher.connection.execute(
        "SELECT message_content FROM [Msg_test] ORDER BY sort_seq")]


def _build_src(tmp_path: Path, schema: str = SCHEMA, salt: bytes | None = None) -> Path:
    plain = build_plain_db(tmp_path / "plain.db", schema)
    src = tmp_path / "message_0.db"
    used_salt, _, _ = encrypt_db(plain, src, KEY_HEX, salt=salt)
    # 供"同库更新"场景复用（真实微信库 salt 在建库时固定）
    _build_src.last_salt = used_salt
    return src


def test_first_create_writes_sidecar(tmp_path):
    src = _build_src(tmp_path)
    cache = tmp_path / "cache"
    w = EncryptedShardWatcher(src, KEY_HEX, cache)
    try:
        assert not w.resumed_from_disk
        assert _rows(w) == ["早", "嗯呢"]
        assert (cache / "message_0.dec.db").exists()
        assert (cache / "message_0.dec.db.meta.json").exists()
    finally:
        pass  # 不 close：保留磁盘状态供重启场景


def test_restart_reuses_without_decrypt(tmp_path):
    """模拟进程重启：新 watcher 直接恢复，源未变时 stat 短路零解密。"""
    src = _build_src(tmp_path)
    cache = tmp_path / "cache"
    EncryptedShardWatcher(src, KEY_HEX, cache)  # 首次（不 close，文件留存）

    w2 = EncryptedShardWatcher(src, KEY_HEX, cache)  # 新进程语义
    try:
        assert w2.resumed_from_disk, "sidecar 应命中"
        assert _rows(w2) == ["早", "嗯呢"]
        assert w2.refresh() is False, "源未变应 stat 短路"
        assert w2.refresh() is False
    finally:
        w2.close()
    assert not (cache / "message_0.dec.db.meta.json").exists(), "close 应清理 sidecar"


def test_restart_after_source_change_updates_incrementally(tmp_path):
    """重启后源已更新：按恢复的页哈希增量解密，新数据可见。"""
    src = _build_src(tmp_path)
    cache = tmp_path / "cache"
    EncryptedShardWatcher(src, KEY_HEX, cache)

    # 源更新：同一明文库加一行后重新加密——salt 必须复用（真实库建库时固定）
    plain2 = build_plain_db(tmp_path / "plain2.db", SCHEMA + EXTRA)
    encrypt_db(plain2, src, KEY_HEX, salt=_build_src.last_salt)

    w2 = EncryptedShardWatcher(src, KEY_HEX, cache)
    try:
        assert w2.resumed_from_disk
        assert _rows(w2) == ["早", "嗯呢", "中午吃啥"], "增量刷新后应见新行"
    finally:
        w2.close()


def test_wrong_key_rejected(tmp_path):
    """错密钥：指纹不匹配，拒绝复用（全量重解失败即暴露，绝不吐旧数据）。"""
    src = _build_src(tmp_path)
    cache = tmp_path / "cache"
    EncryptedShardWatcher(src, KEY_HEX, cache)

    w2 = EncryptedShardWatcher(src, WRONG_KEY_HEX, cache)
    try:
        assert not w2.resumed_from_disk, "错密钥不得复用 sidecar"
    finally:
        w2.close()


def test_corrupted_sidecar_falls_back(tmp_path):
    """sidecar 损坏（截断 JSON）：拒绝恢复，回退全量重解仍可用。"""
    src = _build_src(tmp_path)
    cache = tmp_path / "cache"
    EncryptedShardWatcher(src, KEY_HEX, cache)
    meta = cache / "message_0.dec.db.meta.json"
    meta.write_text('{"version": 1, "key_fp": "trunc', encoding="utf-8")

    w2 = EncryptedShardWatcher(src, KEY_HEX, cache)
    try:
        assert not w2.resumed_from_disk
        assert _rows(w2) == ["早", "嗯呢"], "回退全量重解数据应完好"
    finally:
        w2.close()


def test_truncated_dec_db_rejected(tmp_path):
    """解密副本被截断：完整性锚点失配，拒绝复用。"""
    src = _build_src(tmp_path)
    cache = tmp_path / "cache"
    EncryptedShardWatcher(src, KEY_HEX, cache)
    dec = cache / "message_0.dec.db"
    with open(dec, "r+b") as f:
        f.truncate(PAGE)  # 截到一页

    w2 = EncryptedShardWatcher(src, KEY_HEX, cache)
    try:
        assert not w2.resumed_from_disk
        assert _rows(w2) == ["早", "嗯呢"]
    finally:
        w2.close()
