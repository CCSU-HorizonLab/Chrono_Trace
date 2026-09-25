"""加密微信库分片增量解密引擎（db_watch 实时监听的地基）。

对运行中的微信 message_*.db 做「mtime 触发 + 页级增量 + WAL 帧合并」的解密快照：
- stat 主库与 -wal 的 (mtime, size)，无变化直接返回（轮询零开销）
- 变化时按页对比密文 sha1，只重解变化页（撕裂页靠 HMAC 校验重读重试）
- 解析 -wal 帧按 page_no 覆盖对应页（帧 salt 与 wal 头不一致即停止，宁少读不错读）
- 解密产物写 cache_dir（0700），close() 删除；连接用 immutable 打开只读

实测依据（Linux 4.1）：运行中 db 文件 rw-r--r-- 属主可直读，带活跃 -wal。
"""
from __future__ import annotations

import hashlib
import logging
import os
import sqlite3
import struct
import time
from pathlib import Path

from .db_decryptor_v2 import WeChatDBDecryptorV2

logger = logging.getLogger(__name__)

PAGE_SIZE = 4096
WAL_HEADER_SIZE = 32
WAL_FRAME_HEADER_SIZE = 24


class EncryptedShardWatcher:
    """单个加密 db 分片的增量解密视图。"""

    def __init__(self, src: Path, key_hex: str, cache_dir: Path,
                 raw_keys: dict | None = None):
        self.src = Path(src)
        self.key_hex = str(key_hex or "").strip()
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.out_path = self.cache_dir / (self.src.stem + ".dec.db")
        self._dec = WeChatDBDecryptorV2()
        if raw_keys:
            # Windows 只读扫描账号：按库 salt 直取 raw key（见 db_decryptor_v2）
            self._dec.set_raw_key_map(raw_keys)
        self._keys: tuple[bytes, bytes] | None = None
        self._page_hashes: dict[int, str] = {}
        self._conn: sqlite3.Connection | None = None
        self._state: tuple[int, int, int, int] = (0, 0, 0, 0)
        # 初始全量解密（100MB 分片约 2-5s）
        self.refresh(force=True)

    # ---------- 对外接口 ----------

    def refresh(self, force: bool = False) -> bool:
        """源文件变化时增量刷新解密视图，返回是否刷新。"""
        state = self._stat_state()
        if not force and state == self._state:
            return False
        self._state = state

        try:
            with open(self.src, "rb") as f:
                size = os.fstat(f.fileno()).st_size
                total_pages = max(1, size // PAGE_SIZE)
                out = open(self.out_path, "wb")
                try:
                    changed = 0
                    failed_pages = 0
                    for page_no in range(1, total_pages + 1):
                        raw = f.read(PAGE_SIZE)
                        if len(raw) < PAGE_SIZE:
                            raw = raw + b"\x00" * (PAGE_SIZE - len(raw))
                        h = hashlib.sha1(raw).hexdigest()
                        if not force and self._page_hashes.get(page_no) == h:
                            # 未变化的页：直接写缓存副本中的原页
                            out.write(self._read_decrypted_page(page_no))
                            continue
                        changed += 1
                        self._page_hashes[page_no] = h
                        try:
                            data = self._decrypt_raw(raw, page_no)
                            if page_no == 1:
                                # 页1 解密结果是 4080B（跳过 salt），补 16B SQLite 头
                                data = self._dec.SQLITE_HEADER + data
                            out.write(data)
                        except RuntimeError:
                            # WAL 模式下主库尾部页可能只在 -wal 里有真实内容
                            # （checkpoint 前的预扩页/半写页，HMAC 必然失败）：
                            # 写占位零页，交由 _apply_wal 用帧覆盖修复
                            failed_pages += 1
                            out.write(b"\x00" * PAGE_SIZE)
                    self._apply_wal(f, out, total_pages)
                    if failed_pages:
                        logger.debug(
                            "[dbwatch] %s: %d/%d 页主库缺帧（占位，待 WAL 覆盖或为无效尾页）",
                            self.src.name, failed_pages, total_pages,
                        )
                finally:
                    out.close()
        except OSError as e:
            logger.warning("[dbwatch] 读取 %s 失败: %s", self.src, e)
            return False

        # 连接重建（immutable 只读，避免在解密副本上产生 -shm/-wal）
        self._close_conn()
        logger.debug("[dbwatch] %s 刷新 %d 页", self.src.name, changed)
        return True

    @property
    def connection(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(
                f"file:{self.out_path}?immutable=1", uri=True
            )
            self._conn.row_factory = sqlite3.Row
        return self._conn

    def close(self) -> None:
        self._close_conn()
        for p in (self.out_path, Path(str(self.out_path) + "-wal"), Path(str(self.out_path) + "-shm")):
            try:
                p.unlink(missing_ok=True)
            except OSError:
                pass

    # ---------- 内部 ----------

    def _stat_state(self) -> tuple[int, int, int, int]:
        def st(p: Path) -> tuple[int, int]:
            try:
                s = p.stat()
                return int(s.st_mtime_ns), int(s.st_size)
            except OSError:
                return (0, 0)
        dm, ds = st(self.src)
        wm, ws = st(Path(str(self.src) + "-wal"))
        return (dm, ds, wm, ws)

    def _decrypt_raw(self, raw: bytes, page_no: int) -> bytes:
        """解密单页（HMAC 失败重读源文件重试，同 W3 策略）。"""
        enc_key, mac_key = self._ensure_keys()
        last_err: Exception | None = None
        for _ in range(3):
            try:
                return self._dec.decrypt_page(raw, enc_key, mac_key, page_no - 1)
            except Exception as e:  # HMAC 失败（撕裂页）：重读源文件该页
                last_err = e
                try:
                    with open(self.src, "rb") as f:
                        f.seek((page_no - 1) * PAGE_SIZE)
                        raw = f.read(PAGE_SIZE)
                except OSError:
                    break
        raise RuntimeError(f"页 {page_no} 解密失败: {last_err}")

    def _salt(self) -> bytes:
        if not hasattr(self, "_salt_cache"):
            with open(self.src, "rb") as f:
                self._salt_cache = f.read(16)
        return self._salt_cache

    def _ensure_keys(self) -> tuple[bytes, bytes]:
        """派生密钥只做一次并缓存（PBKDF2 256k 轮 ≈200ms，绝不能按页重复）。"""
        if self._keys is None:
            self._keys = self._dec.derive_keys(bytes.fromhex(self.key_hex), self._salt())
        return self._keys

    def _read_decrypted_page(self, page_no: int) -> bytes:
        try:
            with open(self.out_path, "rb") as f:
                f.seek((page_no - 1) * PAGE_SIZE)
                data = f.read(PAGE_SIZE)
                if len(data) == PAGE_SIZE:
                    return data
        except OSError:
            pass
        # 输出文件还没有该页（首建）：回退到直接解密
        with open(self.src, "rb") as f:
            f.seek((page_no - 1) * PAGE_SIZE)
            raw = f.read(PAGE_SIZE)
        raw = raw + b"\x00" * (PAGE_SIZE - len(raw))
        self._page_hashes[page_no] = hashlib.sha1(raw).hexdigest()
        return self._decrypt_raw(raw, page_no)

    def _apply_wal(self, main_file, out, total_pages: int) -> None:
        """把 -wal 中的已提交帧覆盖到解密视图（帧 salt 与 wal 头一致才应用）。

        WAL 头与帧头字段均为大端序（SQLite 文件格式规定）——此前误用小端解包，
        真实 WAL 的 magic 读为 0x82067F37 导致整段合并在真实文件上从未生效。
        只应用到「最后一次 commit 帧」为止：宁少读不错读，不应用未提交/回滚数据。
        """
        wal_path = Path(str(self.src) + "-wal")
        if not wal_path.exists():
            return
        try:
            wal = open(wal_path, "rb")
        except OSError:
            return
        try:
            header = wal.read(WAL_HEADER_SIZE)
            if len(header) < WAL_HEADER_SIZE:
                return
            magic, = struct.unpack_from(">I", header, 0)
            if magic not in (0x377F0682, 0x377F0683):
                return
            page_size, = struct.unpack_from(">I", header, 8)
            if page_size != PAGE_SIZE:
                return  # 页大小不符（如 65536 特殊值）：无法按 4096 布局合并
            salt1, salt2 = struct.unpack_from(">II", header, 16)

            frames: list[tuple[int, bytes]] = []
            last_commit = 0
            while True:
                fh = wal.read(WAL_FRAME_HEADER_SIZE)
                if len(fh) < WAL_FRAME_HEADER_SIZE:
                    break
                page_no, commit_size, fsalt1, fsalt2, _ck1, _ck2 = struct.unpack(">IIIIII", fh)
                if (fsalt1, fsalt2) != (salt1, salt2):
                    break  # 代际不一致：之后的帧属于上一轮 checkpoint，停止
                raw = wal.read(PAGE_SIZE)
                if len(raw) < PAGE_SIZE:
                    break
                frames.append((page_no, raw))
                if commit_size:
                    last_commit = len(frames)

            for page_no, raw in frames[:last_commit]:
                if not (1 <= page_no <= 1_000_000):
                    continue  # 垃圾页号护栏（防 seek 出稀疏巨文件）
                try:
                    wal_data = self._decrypt_raw(raw, page_no)
                except RuntimeError:
                    continue  # 单帧损坏不拖垮整个合并
                out.seek((page_no - 1) * PAGE_SIZE)
                if page_no == 1:
                    wal_data = self._dec.SQLITE_HEADER + wal_data
                out.write(wal_data)
                self._page_hashes[page_no] = hashlib.sha1(raw).hexdigest()
        except (OSError, struct.error) as e:
            logger.debug("[dbwatch] wal 合并中止: %s", e)
        finally:
            wal.close()

    def _close_conn(self) -> None:
        if self._conn is not None:
            try:
                self._conn.close()
            except Exception:
                pass
            self._conn = None
