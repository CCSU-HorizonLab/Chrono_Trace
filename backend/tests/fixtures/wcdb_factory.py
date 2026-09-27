"""微信加密库测试构造器。

提供三类 fixture（均与真实微信 4.x 文件格式一致，跨平台纯 Python 构造）：
- build_plain_db: 每页尾部保留 80B 的明文 SQLite 库（解密产物同构布局）
- encrypt_db / encrypt_page: SQLCipher V4 页加密（db_decryptor_v2.decrypt_page 的逆运算）
- build_wal: 真实格式（大端字段）的 WAL 文件
- build_synth_elf: 含 .text/.rodata 节与 PT_LOAD 的合成 ELF64（key_capture_linux 分析用）
"""
from __future__ import annotations

import hashlib
import hmac
import os
import sqlite3
import struct
from pathlib import Path

from Crypto.Cipher import AES

from app.services.wechat.db_decryptor_v2 import WeChatDBDecryptorV2

PAGE = 4096
RESERVE = 80  # IV(16) + HMAC-SHA512(64)
WAL_MAGIC = 0x377F0682

_DEC = WeChatDBDecryptorV2()


def build_plain_db(path, script: str) -> Path:
    """构造每页尾部保留 80B 的明文 SQLite 库（与微信解密后布局一致）。

    SQLite 无法直接建带保留区的库：cell 从页尾向下生长，正常库的 cell 会
    落在 [4016:4096] 保留区内而被加密格式丢弃。采用「空库补丁页头再写入」：
    先以 PRAGMA user_version 触发页1落盘（页内无 cell），补 header[20]=80
    与空页1 cell 起始（4096→4016），此后所有页均按 usable=4016 布局。
    """
    p = Path(path)
    for suffix in ("", "-journal", "-wal", "-shm"):
        Path(str(p) + suffix).unlink(missing_ok=True)
    conn = sqlite3.connect(p)
    conn.execute("PRAGMA page_size=4096")
    conn.execute("PRAGMA user_version=1")  # 只写 header 字段，页1不产生 cell
    conn.commit()
    conn.close()
    data = bytearray(p.read_bytes())
    data[20] = RESERVE
    struct.pack_into(">H", data, 105, PAGE - RESERVE)  # 空页1 cell 起始 = 新 usable
    p.write_bytes(data)
    conn = sqlite3.connect(p)
    conn.executescript(script)
    conn.commit()
    conn.close()
    return p


def encrypt_page(plain_4096: bytes, enc_key: bytes, mac_key: bytes, page_no: int,
                 salt: bytes | None = None, iv: bytes | None = None) -> bytes:
    """SQLCipher V4 单页加密（decrypt_page 的逆运算）。page_no 从 1 起。"""
    page = bytes(plain_4096).ljust(PAGE, b"\x00")
    offset = 16 if page_no == 1 else 0
    data = page[offset:PAGE - RESERVE]
    iv = iv or os.urandom(16)
    ct = AES.new(enc_key, AES.MODE_CBC, iv).encrypt(data)
    # HMAC 覆盖密文 + IV（decrypt_page 校验区间为 [offset:4032]），再接页号
    mac = hmac.new(mac_key, digestmod=hashlib.sha512)
    mac.update(ct + iv)
    mac.update(struct.pack("<I", page_no))
    out = (salt if (page_no == 1 and salt is not None) else b"") + ct + iv + mac.digest()
    assert len(out) == PAGE, len(out)
    return out


def encrypt_db(plain_path, out_path, key_hex: str, salt: bytes | None = None):
    """整库加密（每页独立加密，page1 盐前置）。返回 (salt, enc_key, mac_key)。"""
    salt = salt if salt is not None else os.urandom(16)
    enc_key, mac_key = _DEC.derive_keys(bytes.fromhex(key_hex), salt)
    plain = Path(plain_path).read_bytes()
    with open(out_path, "wb") as f:
        for idx in range(len(plain) // PAGE):
            f.write(encrypt_page(plain[idx * PAGE:(idx + 1) * PAGE],
                                 enc_key, mac_key, idx + 1, salt=salt))
    return salt, enc_key, mac_key


def build_wal(path, frames, salt=(0x11111111, 0x22222222), frame_salt=None):
    """构造真实格式（字段全大端）的 WAL 文件。

    frames: [(page_no, encrypted_page, is_commit)]；
    frame_salt 默认同 header（传不同值可模拟代际错乱）。
    """
    header = (
        struct.pack(">I", WAL_MAGIC)
        + struct.pack(">I", 3007000)   # 版本
        + struct.pack(">I", PAGE)
        + struct.pack(">I", 0)         # checkpoint 序号
        + struct.pack(">II", *salt)
        + b"\x00" * 8                  # 校验和（解析器不校验）
    )
    body = b""
    fsalt = frame_salt if frame_salt is not None else salt
    for page_no, enc_page, is_commit in frames:
        body += struct.pack(">IIIIII", page_no, 1 if is_commit else 0,
                            fsalt[0], fsalt[1], 0, 0)
        body += bytes(enc_page)
    Path(path).write_bytes(header + body)


def build_synth_elf(sections, loads=None) -> bytes:
    """合成 ELF64 小端 x86_64。

    sections: [(name, vaddr, content)]（至少 .text/.rodata，供节表分析）
    loads: [(p_offset, p_vaddr, p_filesz, p_memsz)]（PT_LOAD，供程序头分析）
    """
    shstr = b"\x00"
    names: dict[str, int] = {}
    for name, _, _ in sections:
        if name in names:
            continue
        names[name] = len(shstr)
        shstr += name.encode() + b"\x00"
    shstr += b".shstrtab\x00"
    shstr_name_off = len(shstr) - len(b".shstrtab\x00")

    ehsize, shentsize, phentsize = 64, 64, 56
    phnum = len(loads or [])
    off = ehsize + phnum * phentsize
    placed: list[tuple[str, int, int, int]] = []  # (name, vaddr, offset, size)
    blob = bytearray()
    for name, vaddr, content in sections:
        placed.append((name, vaddr, off, len(content)))
        blob += content
        off += len(content)
    shstr_off = off
    blob += shstr
    shoff = off + len(shstr)

    out = bytearray(ehsize)
    out[0:4] = b"\x7fELF"
    out[4], out[5], out[6] = 2, 1, 1  # ELFCLASS64 / 小端 / 当前版本
    struct.pack_into(
        "<HHIQQQIHHHHHH", out, 16,
        2, 62, 1,                    # ET_EXEC / EM_X86_64 / 版本
        0, ehsize, shoff, 0,         # entry / phoff / shoff / flags
        ehsize, phentsize, phnum,
        shentsize, len(placed) + 2, len(placed) + 1,
    )
    for p_offset, p_vaddr, p_filesz, p_memsz in (loads or []):
        out += struct.pack("<IIQQQQQ", 1, 5, p_offset, p_vaddr, p_vaddr,
                           p_filesz, p_memsz)  # PT_LOAD / RX
    out += blob
    out += bytearray(shentsize)  # NULL 节
    for name, vaddr, offset, size in placed:
        sh = bytearray(shentsize)
        struct.pack_into("<IIQQQQ", sh, 0, names[name], 1, 0, vaddr, offset, size)
        out += sh
    sh = bytearray(shentsize)
    struct.pack_into("<IIQQQQ", sh, 0, shstr_name_off, 3, 0, 0, shstr_off, len(shstr))
    out += sh
    return bytes(out)
