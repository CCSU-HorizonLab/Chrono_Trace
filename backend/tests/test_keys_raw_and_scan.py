"""keys 子系统单测：raw key 通道（Windows 只读扫描产物）与扫描引擎离线验证。

覆盖：
- db_decryptor_v2.set_raw_key_map：派生覆盖、salt 未命中回落、整库解密往返
- scan_win 纯函数与合成内存全链扫描（needle→node→config→XOR blob→HMAC 验证）
- account_settings 的 key_type/raw_keys 规整与持久化
- ingest._verify_raw_keys
"""
from __future__ import annotations

import struct
import sys
from pathlib import Path

backend_root = Path(__file__).parent.parent
sys.path.insert(0, str(backend_root))
sys.path.insert(0, str(Path(__file__).parent))

import pytest

from app.services.wechat.account_settings import (
    normalize_wechat_account,
    update_wechat_account_import_state,
)
from app.services.wechat.db_decryptor_v2 import WeChatDBDecryptorV2
from app.services.wechat.ingest_service import WeChatIngestService
from app.services.wechat.keys import scan_win
from fixtures.wcdb_factory import build_plain_db, encrypt_db

KEY_HEX = "3c" * 32
SCHEMA = """
CREATE TABLE t(id INTEGER PRIMARY KEY, s TEXT);
INSERT INTO t VALUES (1, 'hello'), (2, 'world');
"""


@pytest.fixture(scope="module")
def encrypted_env(tmp_path_factory):
    """单库加密环境：返回 (src, salt, enc_key_hex, page1)。"""
    tmp = tmp_path_factory.mktemp("rawkeys")
    plain = build_plain_db(tmp / "plain.db", SCHEMA)
    src = tmp / "message_0.db"
    salt, enc_key, _mac = encrypt_db(plain, src, KEY_HEX)
    page1 = src.read_bytes()[:4096]
    return src, salt, enc_key.hex(), page1


# ============================================================
# raw key 通道（decryptor 单点覆盖）
# ============================================================

def test_raw_key_map_validates_with_wrong_passphrase(encrypted_env):
    _src, salt, enc_key_hex, page1 = encrypted_env
    dec = WeChatDBDecryptorV2()
    dec.set_raw_key_map({salt.hex(): enc_key_hex})
    # salt 命中 → raw key 生效，key 参数（错误的 passphrase）被忽略
    assert dec.validate_key(page1, bytes.fromhex("ff" * 32)) is True


def test_raw_key_map_salt_miss_falls_back_to_passphrase(encrypted_env):
    _src, salt, enc_key_hex, page1 = encrypted_env
    dec = WeChatDBDecryptorV2()
    dec.set_raw_key_map({"00" * 16: enc_key_hex})  # salt 不命中
    assert dec.validate_key(page1, bytes.fromhex(KEY_HEX)) is True
    assert dec.validate_key(page1, bytes.fromhex("ff" * 32)) is False


def test_raw_key_map_decrypt_database_roundtrip(encrypted_env, tmp_path):
    src, salt, enc_key_hex, _page1 = encrypted_env
    dec = WeChatDBDecryptorV2()
    dec.set_raw_key_map({salt.hex(): enc_key_hex})
    out = tmp_path / "dec.db"
    ok = dec.decrypt_database(str(src), str(out), "ff" * 32)  # 错误 passphrase 也应成功
    assert ok is True
    import sqlite3
    conn = sqlite3.connect(out)
    assert [r[1] for r in conn.execute("SELECT * FROM t ORDER BY id")] == ["hello", "world"]


# ============================================================
# 扫描引擎（纯函数 + 合成内存）
# ============================================================

def test_config_key_candidates_extracts_enc_key_and_salt(encrypted_env):
    _src, salt, enc_key_hex, _page1 = encrypted_env
    literal = b"x'" + (enc_key_hex + salt.hex()).encode() + b"'"
    blob = scan_win.xor_repeat(literal, scan_win.CONFIG_XOR_MASK)
    assert scan_win.config_key_candidates(blob) == [(enc_key_hex, salt.hex())]
    assert scan_win.config_key_candidates(b"\x00" * 10) == []


def _fake_memory(encrypted_env):
    """构造含 needle→node→config→blob 指针链的合成内存镜像。"""
    _src, salt, enc_key_hex, _page1 = encrypted_env
    base = 0x10000000
    buf = bytearray(0x8000)

    def put(addr: int, data: bytes) -> None:
        buf[addr - base:addr - base + len(data)] = data

    needle_addr = base + 0x1000
    put(needle_addr, scan_win.CONFIG_CIPHER_NAME)
    config_ptr = base + 0x3000
    node = base + 0x2000
    put(node + 0x10, struct.pack("<Q", needle_addr))          # 字符串对象指针
    put(node + 0x18, struct.pack("<Q", len(scan_win.CONFIG_CIPHER_NAME)))
    put(node + 0x28, struct.pack("<Q", config_ptr))           # Config.Cipher 对象
    data_ptr = base + 0x4000
    literal = b"x'" + (enc_key_hex + salt.hex()).encode() + b"'"
    blob = scan_win.xor_repeat(literal, scan_win.CONFIG_XOR_MASK)
    put(config_ptr + 0x88 + 0x8, struct.pack("<Q", data_ptr))
    put(config_ptr + 0x88 + 0x10, struct.pack("<Q", len(blob)))
    put(data_ptr, blob)

    def read_mem(addr: int, size: int):
        off = addr - base
        if off < 0 or off + size > len(buf):
            return None
        return bytes(buf[off:off + size])

    return [(base, len(buf))], read_mem, salt, enc_key_hex


def test_scan_config_cipher_full_chain_on_fake_memory(encrypted_env):
    regions, read_mem, salt, enc_key_hex = _fake_memory(encrypted_env)
    db_pages = {salt.hex(): (encrypted_env[3], 1, "x/message_0.db")}
    found = scan_win.scan_config_cipher(regions, read_mem, read_mem, db_pages)
    assert found == {salt.hex(): enc_key_hex}


def test_scan_config_cipher_no_needle_returns_empty(encrypted_env):
    base = 0x20000000
    regions = [(base, 4096)]
    read = lambda a, s: b"\x00" * s  # noqa: E731
    assert scan_win.scan_config_cipher(regions, read, read, {"aa" * 16: (b"", 1, "")}) == {}


def test_collect_db_pages_and_primary_salt(tmp_path):
    msg_dir = tmp_path / "db_storage" / "message"
    msg_dir.mkdir(parents=True)
    ct_dir = tmp_path / "db_storage" / "contact"
    ct_dir.mkdir(parents=True)
    for d in (msg_dir, ct_dir):
        plain = build_plain_db(tmp_path / f"{d.name}_plain.db", SCHEMA)
        encrypt_db(plain, d / f"{d.name}.db", KEY_HEX)
    pages = scan_win.collect_db_pages(str(tmp_path / "db_storage"))
    assert len(pages) == 2  # 两个库不同 salt
    primary = scan_win._primary_salt(pages)
    assert "message" in pages[primary][2]


def test_scan_wechat_raw_keys_result_shape(tmp_path, monkeypatch, encrypted_env):
    src, salt, enc_key_hex, _page1 = encrypted_env
    # 把加密库放进目录并伪造进程内存
    db_dir = tmp_path / "db_storage" / "message"
    db_dir.mkdir(parents=True)
    db_dir.joinpath("message_0.db").write_bytes(src.read_bytes())
    regions, read_mem, _s, _e = _fake_memory(encrypted_env)
    monkeypatch.setattr(scan_win, "find_wechat_pids_windows", lambda: [(4321, 999999)])
    monkeypatch.setattr(scan_win, "_memory_harness",
                        lambda pid: (regions, read_mem, read_mem, lambda: None))
    result = scan_win.scan_wechat_raw_keys(str(db_dir.parent))
    assert result["ok"] is True
    assert result["key_type"] == "raw"
    assert result["raw_keys"] == {salt.hex(): enc_key_hex}
    assert result["db_key"] == enc_key_hex
    assert result["pid"] == 4321


def test_scan_wechat_raw_keys_wechat_not_running(encrypted_env, tmp_path):
    src, _salt, _enc, _page1 = encrypted_env
    db_dir = tmp_path / "db_storage"
    db_dir.mkdir()
    db_dir.joinpath("message_0.db").write_bytes(src.read_bytes())
    result = scan_win.scan_wechat_raw_keys(str(db_dir), pids=[])
    assert result["ok"] is False
    assert result["code"] == "wechat_not_running"


# ============================================================
# account_settings 与 ingest 验证
# ============================================================

def test_account_normalize_key_type_and_raw_keys():
    account = normalize_wechat_account({
        "wxid": "wxid_a", "db_key": "ab" * 32,
        "key_type": "raw",
        "raw_keys": {"00" * 16: "cd" * 32, "bad": "xx", "11" * 16: "zz"},
    })
    assert account["key_type"] == "raw"
    assert account["raw_keys"] == {"00" * 16: "cd" * 32}  # 非法项剔除
    # 默认为 passphrase
    assert normalize_wechat_account({"wxid": "b"})["key_type"] == "passphrase"


def test_update_import_state_persists_raw_fields():
    settings: dict = {"wechat_accounts": []}
    update_wechat_account_import_state(
        settings, "wxid_a", db_key="ab" * 32, key_type="raw", raw_keys={"00" * 16: "cd" * 32},
    )
    account = settings["wechat_accounts"][0]
    assert account["key_type"] == "raw"
    assert account["raw_keys"] == {"00" * 16: "cd" * 32}
    # passphrase 捕获时清空 raw 映射
    update_wechat_account_import_state(
        settings, "wxid_a", db_key="ef" * 32, key_type="passphrase", raw_keys={},
    )
    assert settings["wechat_accounts"][0]["raw_keys"] == {}


def test_ingest_verify_raw_keys(encrypted_env):
    src, salt, enc_key_hex, _page1 = encrypted_env
    service = WeChatIngestService()
    paths = {"databases": {"message": [str(src)], "contact": []}}
    assert service._verify_raw_keys(paths, {salt.hex(): enc_key_hex})["ok"] is True
    bad = service._verify_raw_keys(paths, {salt.hex(): "00" * 32})
    assert bad["ok"] is False
