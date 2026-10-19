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
import shutil
import sqlite3
import struct
import threading
import time
from pathlib import Path

from .db_decryptor_v2 import WeChatDBDecryptorV2

logger = logging.getLogger(__name__)

PAGE_SIZE = 4096
WAL_HEADER_SIZE = 32
WAL_FRAME_HEADER_SIZE = 24


class EncryptedShardWatcher:
    """单个加密 db 分片的增量解密视图。

    跨进程复用：页哈希与 stat 状态持久化到 sidecar（.meta.json），进程
    重启后 __init__ 直接恢复——源未变时零解密开销（此前页哈希只在内存，
    每次重启都要全量重解 19 个分片 ~40s）。密钥指纹绑定 salt，错密钥/
    换库绝不复用旧状态。
    """

    META_VERSION = 1

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
        # refresh/close 互斥锁（必须在首次 refresh 前建好）：两线程并发 refresh
        # 会因固定 .tmp 路径互相顶掉对方的临时文件 → os.replace Errno 2，
        # 且被替换的可能是两线程交错写的撕裂文件（实测可致 sidecar 错乱）
        self._lock = threading.Lock()
        self._overlay_dirty = False  # WAL 帧有跳过（撕裂帧），待 reconcile 重放
        self.resumed_from_disk = False  # sidecar 命中（跨进程零/增量解密）
        if self._load_meta():
            # 恢复成功：源未变 → refresh 立即 stat 短路（零解密）；
            # 源已变 → 按恢复的页哈希增量解密
            self.resumed_from_disk = True
            self.refresh()
        else:
            # 初始全量解密（100MB 分片约 2-5s）
            self.refresh(force=True)

    # ---------- 对外接口 ----------

    def refresh(self, force: bool = False, reconcile: bool = False) -> bool:
        """刷新解密视图，返回是否执行了刷新。

        分派：主库 stat 未变 → WAL-only 快路径（拷贝旧快照+重放 -wal 帧）；
        主库变了 → 全量路径（逐页哈希增量解密）。_state 只在刷新完整成功后
        提交：中途异常（如微信写入瞬间的撕裂页 HMAC 失败）保留旧 state，
        下一轮 stat 仍不同 → 自动重试。此前在开头就提交新 state，一次失败
        即永久短路（stat 不再变化），新消息从此收不到（实测 12:02 页 11507
        异常后监听恒 0 条）。

        reconcile=True 且上次快路径有跳帧（_overlay_dirty）时，即使 stat
        未变也重放一次 WAL——撕裂帧被跳过后 stat 不再变化，靠周期性重放
        兜底（同 PG 主从「持续 WAL 流 + 周期 resync」）。实例锁贯穿全程：
        stat 判断→tmp 写→replace→state/meta 提交→关连接必须原子。
        """
        with self._lock:
            state = self._stat_state()
            replay = reconcile and self._overlay_dirty
            if not force and not replay and state == self._state:
                return False
            if (not force and self._page_hashes and self.out_path.exists()
                    and state[0:2] == self._state[0:2]):
                return self._refresh_wal_only(state, replay)
            return self._refresh_full(state, force)

    def _refresh_wal_only(self, state: tuple[int, int, int, int], replay: bool) -> bool:
        """WAL-only 快路径：主库 stat 未变时跳过全库逐页重读+SHA1。

        主库页全部可信（未被写过），内核级拷贝旧快照后仅叠加 -wal 当前
        已提交帧——全量路径每次 0.4~0.6s（100MB 重哈希+整文件重写），此处
        ~0.1s。快路径每次重放全部已提交帧（非增量记进度），只要下一次
        刷新赶在 checkpoint 前就不漏；checkpoint 必写主库 → 自动回全量
        路径逐页重 derive，即 checkpoint 节奏（实测 10~70s 一波）就是天然
        的全库对账点，无需定时强制全量。
        """
        tmp_out_path = self.out_path.with_name(self.out_path.name + ".tmp")
        try:
            shutil.copyfile(self.out_path, tmp_out_path)
            with open(tmp_out_path, "r+b") as out:
                applied, skipped = self._apply_wal(out)
            # 先关连接再替换：替换瞬间旧连接仍指旧 inode，会继续读旧内容
            self._close_conn()
            os.replace(tmp_out_path, self.out_path)
        except Exception as e:
            self._discard_tmp(tmp_out_path)
            logger.warning("[dbwatch] 快路径刷新 %s 失败（保留旧快照，待重试）: %s",
                           self.src, e)
            return False

        self._state = state
        # 有跳帧（撕裂/损坏帧解密失败被跳过）→ 标脏，等 reconcile 重放
        self._overlay_dirty = skipped > 0
        self._save_meta()
        logger.debug("[dbwatch] %s WAL 快路径应用 %d 帧（跳过 %d）%s",
                     self.src.name, applied, skipped, "〔重放〕" if replay else "")
        return True

    def _refresh_full(self, state: tuple[int, int, int, int], force: bool) -> bool:
        """全量路径：逐页读主库、密文 sha1 对比增量解密 + WAL 帧合并。"""
        tmp_out_path = self.out_path.with_name(self.out_path.name + ".tmp")
        try:
            with open(self.src, "rb") as f:
                size = os.fstat(f.fileno()).st_size
                total_pages = max(1, size // PAGE_SIZE)
                # 写临时文件、成功后原子替换：此前直接 "wb" 打开 out 会先清零，
                # 而未变化页又要从 out 读旧内容——同文件边读边写，回退路径必然
                # 触发且页 1 漏拼 SQLite 头（「file is not a database」根源）
                out = open(tmp_out_path, "wb")
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
                    applied, skipped = self._apply_wal(out)
                    if failed_pages:
                        logger.debug(
                            "[dbwatch] %s: %d/%d 页主库缺帧（占位，待 WAL 覆盖或为无效尾页）",
                            self.src.name, failed_pages, total_pages,
                        )
                finally:
                    out.close()
                # 先关连接再替换（见快路径注释）。原子替换仅在页循环 + WAL 合并
                # 完整成功后执行：中途异常由外层 except 丢弃 .tmp。此前 replace
                # 写在 finally 里无条件执行，半截临时文件会覆盖完好的旧快照
                # （malformed 库根源）
                self._close_conn()
                os.replace(tmp_out_path, self.out_path)
        except Exception as e:
            # 解密/WAL 合并中途失败：不提交新 state（见 refresh），下一轮自动
            # 重试；旧快照原封未动（写的是 .tmp），直接丢弃临时文件
            self._discard_tmp(tmp_out_path)
            logger.warning("[dbwatch] 刷新 %s 中途失败（保留旧快照，待重试）: %s",
                           self.src, e)
            return False

        # 全量处理成功才提交新 state
        self._state = state
        self._overlay_dirty = skipped > 0
        self._save_meta()
        logger.debug("[dbwatch] %s 全量刷新 %d 页 / WAL %d 帧（跳过 %d）",
                     self.src.name, changed, applied, skipped)
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
        # 只关连接、清临时残留，不删 sidecar/meta：跨启动复用已解密副本
        # （停止监听→再启动免 45s+ 全量重解密；错密钥/换库由 _load_meta
        # 的 key 指纹校验兜住不会误用），与 import_cache 持久口径一致
        with self._lock:
            self._close_conn()
            for p in (Path(str(self.out_path) + ".tmp"),
                      Path(str(self._meta_path()) + ".tmp"),
                      Path(str(self.out_path) + "-wal"), Path(str(self.out_path) + "-shm")):
                try:
                    p.unlink(missing_ok=True)
                except OSError:
                    pass

    # ---------- 内部 ----------

    @staticmethod
    def _discard_tmp(tmp_out_path: Path) -> None:
        try:
            tmp_out_path.unlink(missing_ok=True)
        except OSError:
            pass

    def _meta_path(self) -> Path:
        return Path(str(self.out_path) + ".meta.json")

    def _key_fingerprint(self) -> str:
        """密钥+库 salt 指纹：错密钥/换库绝不复用旧解密状态。"""
        salt_hex = ""
        try:
            with open(self.src, "rb") as f:
                salt_hex = f.read(16).hex()
        except OSError:
            pass
        return hashlib.sha1(f"{self.key_hex}:{salt_hex}".encode("utf-8")).hexdigest()

    def _load_meta(self) -> bool:
        """从 sidecar 恢复页哈希与 stat 状态。任何不一致都拒绝（回退全量）。"""
        try:
            import json

            meta = json.loads(self._meta_path().read_text(encoding="utf-8"))
            if meta.get("version") != self.META_VERSION:
                return False
            if meta.get("key_fp") != self._key_fingerprint():
                return False
            if not self.out_path.exists():
                return False
            pages = meta.get("pages")
            hashes = meta.get("page_hashes")
            if not isinstance(pages, int) or pages <= 0 or not isinstance(hashes, dict):
                return False
            # 解密副本完整性锚点：页数×页大小必须吻合（截断/膨胀即弃）
            if self.out_path.stat().st_size != pages * PAGE_SIZE:
                return False
            if len(hashes) != pages:
                return False
            self._page_hashes = {int(k): str(v) for k, v in hashes.items()}
            state = meta.get("state") or []
            if len(state) != 4:
                return False
            self._state = (int(state[0]), int(state[1]), int(state[2]), int(state[3]))
            return True
        except Exception:
            return False

    def _save_meta(self) -> None:
        """刷新成功后原子保存 sidecar（失败只丢跨进程复用，不影响当次）。"""
        try:
            import json

            payload = {
                "version": self.META_VERSION,
                "key_fp": self._key_fingerprint(),
                "pages": len(self._page_hashes),
                "state": list(self._state),
                "page_hashes": {str(k): v for k, v in self._page_hashes.items()},
            }
            meta_path = self._meta_path()
            tmp = Path(str(meta_path) + ".tmp")
            tmp.write_text(json.dumps(payload), encoding="utf-8")
            os.replace(tmp, meta_path)
        except Exception as e:
            logger.debug("[dbwatch] %s sidecar 保存失败（忽略）: %s", self.src.name, e)

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
        # 输出文件还没有该页（上次刷新中断被截短，但哈希缓存仍在）：
        # 回退直接解密；WAL-only 尾页必然 HMAC 失败——返回零占位与主循环
        # 同策略，交给本轮稍后的 _apply_wal 用帧覆盖。此前此处无兜底，
        # RuntimeError 直接打断整轮刷新且每次重试卡死在同一页
        # （实测 message_1 页 15859 恒失败 → 监听恒 0 条）。
        with open(self.src, "rb") as f:
            f.seek((page_no - 1) * PAGE_SIZE)
            raw = f.read(PAGE_SIZE)
        raw = raw + b"\x00" * (PAGE_SIZE - len(raw))
        self._page_hashes[page_no] = hashlib.sha1(raw).hexdigest()
        try:
            data = self._decrypt_raw(raw, page_no)
        except Exception:
            return b"\x00" * PAGE_SIZE
        if page_no == 1:
            # 页1 解密产物 4080B（跳过 salt）——与主循环一致补 16B SQLite 头
            data = self._dec.SQLITE_HEADER + data
        return data

    def _apply_wal(self, out) -> tuple[int, int]:
        """把 -wal 中的已提交帧覆盖到解密视图，返回 (应用帧数, 跳过帧数)。

        WAL 头与帧头字段均为大端序（SQLite 文件格式规定）——此前误用小端解包，
        真实 WAL 的 magic 读为 0x82067F37 导致整段合并在真实文件上从未生效。
        只应用到「最后一次 commit 帧」为止：宁少读不错读，不应用未提交/回滚数据。
        """
        wal_path = Path(str(self.src) + "-wal")
        if not wal_path.exists():
            return 0, 0
        try:
            wal = open(wal_path, "rb")
        except OSError:
            return 0, 0
        applied = 0
        skipped = 0
        try:
            header = wal.read(WAL_HEADER_SIZE)
            if len(header) < WAL_HEADER_SIZE:
                return 0, 0
            magic, = struct.unpack_from(">I", header, 0)
            if magic not in (0x377F0682, 0x377F0683):
                return 0, 0
            page_size, = struct.unpack_from(">I", header, 8)
            if page_size != PAGE_SIZE:
                return 0, 0  # 页大小不符（如 65536 特殊值）：无法按 4096 布局合并
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

            # 帧解密不走 _decrypt_raw 的「重读主库」重试通道：帧撕裂时重读到的
            # 是主库旧页，会把过期内容当帧内容静默应用且无从自愈——帧失败
            # 必须跳过并标脏，交给 reconcile 周期重放兜底
            enc_key, mac_key = self._ensure_keys()
            for page_no, raw in frames[:last_commit]:
                if not (1 <= page_no <= 1_000_000):
                    continue  # 垃圾页号护栏（防 seek 出稀疏巨文件）
                try:
                    wal_data = self._dec.decrypt_page(raw, enc_key, mac_key, page_no - 1)
                except Exception:
                    skipped += 1  # 单帧损坏不拖垮整个合并（reconcile 周期重放兜底）
                    continue
                out.seek((page_no - 1) * PAGE_SIZE)
                if page_no == 1:
                    wal_data = self._dec.SQLITE_HEADER + wal_data
                out.write(wal_data)
                self._page_hashes[page_no] = hashlib.sha1(raw).hexdigest()
                applied += 1
            return applied, skipped
        except (OSError, struct.error) as e:
            logger.debug("[dbwatch] wal 合并中止: %s", e)
            return applied, skipped
        finally:
            wal.close()

    def _close_conn(self) -> None:
        if self._conn is not None:
            try:
                self._conn.close()
            except Exception:
                pass
            self._conn = None
