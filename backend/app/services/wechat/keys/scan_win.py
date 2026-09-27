"""Windows 只读密钥扫描（移植自 MIT 许可的 wcdb-key-tool-plus，适配本项目契约）。

原理：微信 4.1+ Windows 版的 WCDB `Config.Cipher` 运行时对象在进程内存中保留
每库派生密钥（SQLCipher raw key 语义：`x'<enc_key><salt>'` 十六进制字面量经
固定掩码 XOR 混淆存储）。与 Linux 不同（Linux 4.1+ 不驻留密钥，只能 GDB 断点）。

只读扫描：OpenProcess + ReadProcessMemory（不注入、不改微信进程、免重启）。
流程：锚点字符串对象 → 持有它的配置节点 → 密钥 blob → 解混淆出候选 →
经本项目 db_decryptor_v2 按库 salt 做 HMAC 验证（宁缺勿错）。

产出 key_type="raw"：每库 enc_key 映射 {salt_hex: enc_key_hex}，无法反推
passphrase，消费方经 WeChatDBDecryptorV2.set_raw_key_map 使用。
所有 win32/ctypes 依赖均为函数内延迟导入——本模块在 Linux 上可导入、
纯函数部分可离线单测。
"""
from __future__ import annotations

import logging
import re
import struct
import subprocess
import time
from pathlib import Path
from typing import Callable, Optional

logger = logging.getLogger(__name__)

KEY_SZ = 32
PAGE_SZ = 4096
SALT_SZ = 16

CONFIG_CIPHER_NAME = b"com.Tencent.WCDB.Config.Cipher"
CONFIG_XOR_MASK = bytes.fromhex(
    "d2c7442458020000004889442450488b"
    "450048844c2448488944254048584c24"
)
MAX_USER_ADDRESS = 0x0000_8000_0000_0000
CONFIG_BLOB_MAX = 1024
CONFIG_LITERAL_RE = re.compile(rb"[xX]'([0-9a-fA-F]{64,192})'")
# 老版本（4.0.x）内存中的 pragma 形态：x'<64hex enc_key><32hex salt>'
LEGACY_HEX_RE = re.compile(rb"x'([0-9a-fA-F]{96,192})'")

WINDOWS_PROCESS_NAMES = ("Weixin.exe", "wechat.exe")


# ============================================================
# 纯函数（跨平台可测）
# ============================================================

def xor_repeat(data: bytes, mask: bytes) -> bytes:
    return bytes(v ^ mask[i % len(mask)] for i, v in enumerate(data))


def u64_from(data: bytes, offset: int) -> int:
    if offset < 0 or offset + 8 > len(data):
        return 0
    return struct.unpack_from("<Q", data, offset)[0]


def probable_32_byte_key(data: bytes) -> bool:
    return (
        len(data) == KEY_SZ
        and len(set(data)) >= 15
        and data not in {b"\x00" * KEY_SZ, b"\xff" * KEY_SZ}
    )


def iter_region_chunks(regions: list[tuple[int, int]],
                       read_region: Callable[[int, int], Optional[bytes]],
                       *, chunk_size: int = 2 * 1024 * 1024, overlap: int = 0):
    """按区域分块产出 (data_base, data)；overlap 保留块尾以跨块命中模式。"""
    for base, size in regions:
        offset = 0
        tail = b""
        tail_base = base
        while offset < size:
            current = min(chunk_size, size - offset)
            chunk = read_region(base + offset, current) or b""
            data_base = tail_base if tail else base + offset
            data = tail + chunk
            if data:
                yield data_base, data
                if overlap:
                    tail = data[-overlap:]
                    tail_base = data_base + max(0, len(data) - len(tail))
                else:
                    tail = b""
                    tail_base = base + offset + current
            else:
                tail = b""
                tail_base = base + offset + current
            offset += current


def find_bytes_in_regions(regions, read_region, needle: bytes) -> set[int]:
    addresses: set[int] = set()
    overlap = max(0, len(needle) - 1)
    for data_base, data in iter_region_chunks(regions, read_region, overlap=overlap):
        pos = data.find(needle)
        while pos >= 0:
            addresses.add(data_base + pos)
            pos = data.find(needle, pos + 1)
    return addresses


def config_key_candidates(blob: bytes) -> list[tuple[str, Optional[str]]]:
    """从解混淆后的 Config.Cipher blob 提取 (enc_key_hex, embedded_salt_hex|None)。"""
    if not blob or len(blob) > CONFIG_BLOB_MAX:
        return []
    decoded = xor_repeat(blob, CONFIG_XOR_MASK)
    out: list[tuple[str, Optional[str]]] = []
    seen: set[tuple[str, Optional[str]]] = set()
    for match in CONFIG_LITERAL_RE.finditer(decoded):
        run = match.group(1).decode("ascii", errors="replace").lower()
        starts = [0]
        if len(run) > 96:
            starts.extend(range(0, len(run) - 63, 32))
            starts.append(len(run) - 64)
        for start in dict.fromkeys(starts):
            if start < 0 or start + 64 > len(run):
                continue
            enc_key_hex = run[start:start + 64]
            try:
                enc_key = bytes.fromhex(enc_key_hex)
            except ValueError:
                continue
            if not probable_32_byte_key(enc_key):
                continue
            embedded_salt = run[start + 64:start + 96] if start + 96 <= len(run) else None
            item = (enc_key_hex, embedded_salt)
            if item not in seen:
                seen.add(item)
                out.append(item)
    return out


def verify_candidate(enc_key_hex: str, salt_hex: str, page1: bytes) -> bool:
    """候选 raw key 对某库首页做 HMAC 校验（复用项目解密器，保证语义一致）。"""
    from ..db_decryptor_v2 import WeChatDBDecryptorV2
    dec = WeChatDBDecryptorV2()
    dec.set_raw_key_map({salt_hex: enc_key_hex})
    try:
        return dec.validate_key(page1, b"\x00" * KEY_SZ)
    except Exception:
        return False


def collect_db_pages(db_dir: str) -> dict[str, tuple[bytes, int, str]]:
    """遍历数据目录，返回 {salt_hex: (page1, 库数量, 代表路径)}。"""
    pages: dict[str, tuple[bytes, int, str]] = {}
    for path in sorted(Path(db_dir).rglob("*.db")):
        if path.name.endswith("-wal") or path.name.endswith("-shm"):
            continue
        try:
            if path.stat().st_size < PAGE_SZ:
                continue
            page1 = path.read_bytes()[:PAGE_SZ]
        except OSError:
            continue
        salt_hex = page1[:SALT_SZ].hex()
        count, _rep, rep = pages.get(salt_hex, (0, b"", ""))
        pages[salt_hex] = (page1, count + 1, str(path))
    return pages


# ============================================================
# 只读扫描主路径（微信 4.1+ Config.Cipher）
# ============================================================

def scan_config_cipher(regions, read_region, read_mem, db_pages) -> dict[str, str]:
    """扫描进程内存中的 Config.Cipher 对象，返回验证通过的 {salt_hex: enc_key_hex}。"""
    remaining = set(db_pages.keys())
    raw_keys: dict[str, str] = {}

    needle_addresses = find_bytes_in_regions(regions, read_region, CONFIG_CIPHER_NAME)
    if not needle_addresses:
        return raw_keys
    pair_patterns = [
        struct.pack("<Q", addr) + struct.pack("<Q", len(CONFIG_CIPHER_NAME))
        for addr in needle_addresses
    ]
    seen: set[tuple[str, Optional[str]]] = set()

    for base, data in iter_region_chunks(regions, read_region, overlap=0x80):
        if not remaining:
            break
        for pattern in pair_patterns:
            pos = data.find(pattern)
            while pos >= 0:
                node_base = base + pos - 0x10
                node = read_mem(node_base, 0x50)
                if node and len(node) >= 0x40:
                    if (u64_from(node, 0x10) in needle_addresses
                            and u64_from(node, 0x18) == len(CONFIG_CIPHER_NAME)):
                        config_ptr = u64_from(node, 0x28)
                        if 0x10000 <= config_ptr < MAX_USER_ADDRESS:
                            obj = read_mem(config_ptr + 0x88, 0x28)
                            if obj and len(obj) >= 0x18:
                                data_ptr = u64_from(obj, 0x8)
                                data_len = u64_from(obj, 0x10)
                                if (0 < data_len <= CONFIG_BLOB_MAX
                                        and 0x10000 <= data_ptr < MAX_USER_ADDRESS):
                                    blob = read_mem(data_ptr, int(data_len))
                                    if blob and len(blob) == data_len:
                                        _absorb_candidates(
                                            blob, db_pages, raw_keys, remaining, seen
                                        )
                pos = data.find(pattern, pos + 1)
    return raw_keys


def _absorb_candidates(blob, db_pages, raw_keys, remaining, seen) -> None:
    for enc_key_hex, embedded_salt in config_key_candidates(blob):
        if (enc_key_hex, embedded_salt) in seen:
            continue
        seen.add((enc_key_hex, embedded_salt))
        target_salts = (
            [embedded_salt] if embedded_salt in remaining else list(remaining)
        )
        for salt_hex in target_salts:
            if salt_hex not in remaining:
                continue
            page1 = db_pages[salt_hex][0]
            if verify_candidate(enc_key_hex, salt_hex, page1):
                raw_keys[salt_hex] = enc_key_hex
                remaining.discard(salt_hex)
                break


def scan_legacy_hex(regions, read_region, db_pages) -> dict[str, str]:
    """老版本（4.0.x）回退：内存中明文 pragma `x'<enc><salt>'` 模式。"""
    remaining = set(db_pages.keys())
    raw_keys: dict[str, str] = {}
    for _base, data in iter_region_chunks(regions, read_region):
        if not remaining:
            break
        for m in LEGACY_HEX_RE.finditer(data):
            run = m.group(1).decode("ascii", errors="replace").lower()
            for start in range(0, min(len(run) - 95, 64), 32):
                enc_hex, salt_hex = run[start:start + 64], run[start + 64:start + 96]
                if salt_hex not in remaining:
                    continue
                if verify_candidate(enc_hex, salt_hex, db_pages[salt_hex][0]):
                    raw_keys[salt_hex] = enc_hex
                    remaining.discard(salt_hex)
                break
    return raw_keys


# ============================================================
# win32 运行时挂点（函数内延迟导入）
# ============================================================

def find_wechat_pids_windows() -> list[tuple[int, int]]:
    """返回 [(pid, 内存KB)]，按内存降序（主进程优先）。"""
    pids: list[tuple[int, int]] = []
    for name in WINDOWS_PROCESS_NAMES:
        try:
            r = subprocess.run(
                ["tasklist", "/FI", f"IMAGENAME eq {name}", "/FO", "CSV", "/NH"],
                capture_output=True, text=True, timeout=15,
            )
        except (OSError, subprocess.SubprocessError):
            continue
        for line in r.stdout.strip().split("\n"):
            if not line.strip():
                continue
            parts = line.strip('"').split('","')
            if len(parts) >= 5:
                try:
                    pid = int(parts[1])
                    mem = int(parts[4].replace(",", "").replace(" K", "").strip() or "0")
                except ValueError:
                    continue
                if (pid, mem) not in pids:
                    pids.append((pid, mem))
    pids.sort(key=lambda x: x[1], reverse=True)
    return pids


def _memory_harness(pid: int):
    """打开进程并返回 (regions, read_region, read_mem, closer)。只读权限。"""
    import ctypes

    kernel32 = ctypes.windll.kernel32  # noqa: win32 专属（函数内延迟导入）
    MEM_COMMIT = 0x1000
    READABLE = {0x02, 0x04, 0x08, 0x10, 0x20, 0x40, 0x80}

    class MBI(ctypes.Structure):
        _fields_ = [
            ("BaseAddress", ctypes.c_uint64), ("AllocationBase", ctypes.c_uint64),
            ("AllocationProtect", ctypes.c_uint32), ("_pad1", ctypes.c_uint32),
            ("RegionSize", ctypes.c_uint64), ("State", ctypes.c_uint32),
            ("Protect", ctypes.c_uint32), ("Type", ctypes.c_uint32), ("_pad2", ctypes.c_uint32),
        ]

    handle = kernel32.OpenProcess(0x0010 | 0x0400, False, pid)  # PROCESS_VM_READ|QUERY_INFORMATION
    if not handle:
        raise RuntimeError(f"无法打开微信进程 PID={pid}（尝试以管理员身份运行）")

    def read_mem(addr: int, size: int) -> Optional[bytes]:
        buf = ctypes.create_string_buffer(size)
        nread = ctypes.c_size_t(0)
        if kernel32.ReadProcessMemory(handle, ctypes.c_uint64(addr), buf, size, ctypes.byref(nread)):
            return buf.raw[:nread.value]
        return None

    def enum_regions() -> list[tuple[int, int]]:
        regs = []
        addr = 0
        mbi = MBI()
        while addr < 0x7FFFFFFFFFFF:
            if kernel32.VirtualQueryEx(handle, ctypes.c_uint64(addr), ctypes.byref(mbi), ctypes.sizeof(mbi)) == 0:
                break
            if (mbi.State == MEM_COMMIT and mbi.Protect in READABLE
                    and 0 < mbi.RegionSize < 500 * 1024 * 1024):
                regs.append((mbi.BaseAddress, mbi.RegionSize))
            nxt = mbi.BaseAddress + mbi.RegionSize
            if nxt <= addr:
                break
            addr = nxt
        return regs

    def closer() -> None:
        kernel32.CloseHandle(handle)

    regions = enum_regions()
    return regions, read_mem, read_mem, closer


# ============================================================
# 对外入口
# ============================================================

def scan_wechat_raw_keys(wechat_dir: str, timeout_seconds: int = 60,
                         pids: Optional[list[tuple[int, int]]] = None) -> dict:
    """只读扫描全部微信进程，返回与 Provider 同形的结果。

    成功：{"ok": True, "db_key": <主库 raw key hex>, "key_type": "raw",
           "raw_keys": {salt_hex: enc_key_hex}, "pid": int}
    失败：{"ok": False, "code": ..., "error": ...}
    """
    db_pages = collect_db_pages(wechat_dir)
    if not db_pages:
        return {"ok": False, "code": "scan_no_db",
                "error": f"数据目录未找到数据库: {wechat_dir}"}

    if pids is None:
        pids = find_wechat_pids_windows()
    if not pids:
        return {"ok": False, "code": "wechat_not_running", "error": "微信未运行"}

    deadline = time.monotonic() + max(15, timeout_seconds)
    raw_keys: dict[str, str] = {}
    hit_pid: Optional[int] = None
    tried_legacy = False

    for pid, _mem in pids:
        if time.monotonic() > deadline or len(raw_keys) == len(db_pages):
            break
        try:
            regions, read_region, read_mem, closer = _memory_harness(pid)
        except (RuntimeError, OSError, ImportError) as exc:
            logger.info("[KeyScan] PID=%s 不可读: %s", pid, exc)
            continue
        try:
            raw_keys.update(scan_config_cipher(regions, read_region, read_mem, db_pages))
            if raw_keys:
                hit_pid = pid
            if len(raw_keys) < len(db_pages) and not tried_legacy:
                raw_keys.update(scan_legacy_hex(regions, read_region, db_pages))
                tried_legacy = True
        finally:
            closer()

    if not raw_keys:
        return {"ok": False, "code": "scan_no_match",
                "error": "只读扫描未找到可用密钥（微信版本可能不驻留 Config.Cipher），回退登录捕获"}

    primary_salt = _primary_salt(db_pages)
    return {
        "ok": True,
        "db_key": raw_keys.get(primary_salt) or next(iter(raw_keys.values())),
        "key_type": "raw",
        "raw_keys": raw_keys,
        "pid": hit_pid or pids[0][0],
    }


def _primary_salt(db_pages: dict[str, tuple[bytes, int, str]]) -> str:
    """主库 salt：优先 message 目录，其次库数量最多的 salt。"""
    best_count, best = -1, ""
    for salt, (_page, count, path) in db_pages.items():
        is_message = "message" in Path(path).parts
        score = count + (1000 if is_message else 0)
        if score > best_count:
            best_count, best = score, salt
    return best
