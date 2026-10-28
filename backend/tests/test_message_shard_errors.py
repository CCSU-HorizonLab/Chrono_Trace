"""MessageDBV4 分片级读取缺口收集测试（W4）。

密钥验证失败/页面解密失败/Name2Id 读取失败此前就地 continue 静默吞掉，
get_messages 正常返回——ingest 水位护栏感知不到，缺口会话的消息被
后续增量永久跳过。缺口必须进 read_errors 由上层冻结水位。
"""
from __future__ import annotations

import sys
from pathlib import Path

backend_root = Path(__file__).parent.parent
sys.path.insert(0, str(backend_root))
sys.path.insert(0, str(Path(__file__).parent))

from app.services.wechat.db.v4.message import MessageDBV4


def test_corrupt_shard_records_read_errors(tmp_path):
    """明文损坏分片：Name2Id 与消息表读取失败都进 read_errors。"""
    bad = tmp_path / "message_0.db"
    bad.write_bytes(b"this is not a sqlite database at all" * 50)

    db = MessageDBV4([str(bad)])
    try:
        usernames = db.get_all_conversation_usernames()
        assert usernames == []
        assert any("会话清单" in e for e in db.read_errors), (
            "Name2Id 读取失败必须留痕"
        )

        msgs = db.get_messages("wxid_zhang")
        assert msgs == []
        assert any("读取 wxid_zhang 失败" in e for e in db.read_errors), (
            "消息表读取失败必须留痕"
        )
    finally:
        db.close()


def test_key_verify_failure_records_read_error(tmp_path, monkeypatch):
    """分片密钥验证失败：整分片缺席必须留痕（不得静默 continue）。"""
    import app.services.wechat.snapshot_manager as snap_mod
    monkeypatch.setattr(
        snap_mod, "get_snapshot_manager",
        lambda: (_ for _ in ()).throw(RuntimeError("测试禁用快照")),
    )

    import app.services.wechat.db_decryptor_v2 as dec_mod

    class _RejectKeyDecryptor:
        def set_raw_key_map(self, *_a):
            pass

        def verify_key_from_file(self, *_a):
            return False

    monkeypatch.setattr(dec_mod, "WeChatDBDecryptorV2", _RejectKeyDecryptor)

    src = tmp_path / "message_0.db"
    src.write_bytes(b"\x00" * 4096)

    db = MessageDBV4([str(src)], db_key="ab" * 32, my_wxid="wxid_me")
    try:
        assert any("密钥验证失败" in e for e in db.read_errors), (
            "密钥验证失败必须留痕供水位冻结"
        )
    finally:
        db.close()


def test_healthy_shard_has_no_read_errors(tmp_path):
    """正常明文库：read_errors 保持为空（不误报）。"""
    import hashlib
    import sqlite3
    table = f"Msg_{hashlib.md5('wxid_zhang'.encode()).hexdigest()}"
    good = tmp_path / "message_0.db"
    conn = sqlite3.connect(good)
    conn.executescript(f"""
        CREATE TABLE Name2Id (user_name TEXT PRIMARY KEY);
        INSERT INTO Name2Id VALUES ('wxid_zhang');
        CREATE TABLE [{table}] (
            local_id INTEGER PRIMARY KEY, server_id INTEGER, local_type INTEGER,
            sort_seq INTEGER, real_sender_id INTEGER, create_time INTEGER,
            message_content TEXT
        );
    """)
    conn.commit()
    conn.close()

    db = MessageDBV4([str(good)], my_wxid="wxid_me")
    try:
        assert db.read_errors == []
        assert db.get_all_conversation_usernames() == ["wxid_zhang"]
        assert db.get_messages("wxid_zhang") == []
    finally:
        db.close()
