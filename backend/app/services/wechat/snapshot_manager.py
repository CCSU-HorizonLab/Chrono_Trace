"""共享增量解密快照管理器：导入链路复用 watcher 解密副本，免全量重解密。

问题：ContactDBV4 / MessageDBV4 每次构造都把加密库**全量解密到临时文件**
（~19 分片×几十 MB 全页 AES），增量同步也要付全量代价（~45s）。

方案：模块级单例维护 EncryptedShardWatcher 实例——首次调用做全量解密
（与原路径等价），后续调用 watcher.refresh() 仅解密变化页（增量秒级）。
适配器（ContactDBV4 / MessageDBV4）优先从本管理器取解密副本路径。
"""
from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
from pathlib import Path

from .db_snapshot import EncryptedShardWatcher
from ...config import TEMP_DIR_PATH

logger = logging.getLogger(__name__)

# 快照陈旧容差（秒）：源库比快照新超过该值说明变化长期没能刷进快照
# （持续撕裂/锁竞争），旧快照不得再当当前数据交给导入——水位会越过缺口
STALE_TOLERANCE_SECONDS = 60

_MANAGER: "SharedSnapshotManager | None" = None
_MANAGER_LOCK = threading.Lock()


def _key_identity(key_hex: str, raw_keys: dict | None) -> str:
    """内存缓存键的密钥指纹：key_hex + raw_keys 排序指纹。"""
    raw_fp = ""
    if raw_keys:
        raw_fp = hashlib.sha1(
            json.dumps(raw_keys, sort_keys=True, ensure_ascii=False).encode("utf-8")
        ).hexdigest()
    return f"{str(key_hex or '').strip()}:{raw_fp}"


class SharedSnapshotManager:
    """跨调用共享的加密库增量解密视图集合（进程级单例）。"""

    def __init__(self):
        self._watchers: dict[str, EncryptedShardWatcher] = {}
        self._lock = threading.Lock()
        self._cache_dir = Path(TEMP_DIR_PATH) / "import_cache"
        self._cache_dir.mkdir(parents=True, exist_ok=True, mode=0o700)

    def get_decrypted_path(self, src: str | Path, key_hex: str,
                           raw_keys: dict | None = None) -> Path | None:
        """返回解密副本路径；首次全量解密，后续增量刷新（仅变化页）。

        返回 None 表示解密失败（调用方走原全量路径兜底）。
        """
        src_path = Path(src)
        # 缓存键必须含密钥指纹：换账号/密钥重捕获后同一路径拿到旧 watcher，
        # 旧密钥解新数据全 HMAC 失败（磁盘 sidecar 有 key_fp 校验，内存没有）
        cache_key = f"{src_path.resolve()}|{_key_identity(key_hex, raw_keys)}"
        with self._lock:
            watcher = self._watchers.get(cache_key)
            if watcher is None:
                try:
                    watcher = EncryptedShardWatcher(
                        src_path, key_hex, self._cache_dir, raw_keys=raw_keys
                    )
                    self._watchers[cache_key] = watcher
                    if watcher.resumed_from_disk:
                        # sidecar 命中：跨进程复用已解密副本，仅增量刷新变化页
                        logger.info("[SnapshotManager] 复用磁盘快照 %s（增量刷新）→ %s",
                                    src_path.name, watcher.out_path)
                    else:
                        logger.info("[SnapshotManager] 首次全量解密 %s → %s",
                                    src_path.name, watcher.out_path)
                except Exception as exc:
                    logger.warning("[SnapshotManager] 首次解密失败 %s: %s", src_path, exc)
                    return None
            else:
                # 已有快照：增量刷新（mtime 变化才实际操作，stat 短路零开销）
                try:
                    watcher.refresh()
                except Exception as exc:
                    logger.warning("[SnapshotManager] 增量刷新失败 %s: %s", src_path, exc)
            # 陈旧检查对两个分支统一生效：新建分支 sidecar 恢复后的增量
            # 刷新失败同样只保留旧快照（refresh 内部吞错返回 False，构造不
            # 抛），不查会把领先源很久的磁盘旧快照当当前数据交给导入——
            # 水位照常推进，窗口内新消息永久丢失
            if self._is_stale(watcher):
                logger.warning(
                    "[SnapshotManager] 快照陈旧（源领先超过 %ds），丢弃重解: %s",
                    STALE_TOLERANCE_SECONDS, src_path,
                )
                self._drop_watcher(cache_key, watcher)
                return None
            return watcher.out_path

    def _is_stale(self, watcher: EncryptedShardWatcher) -> bool:
        """源库 mtime 领先快照文件超过容差 → 快照长期未跟上源（持续失败）。

        安静账号源不变时快照也不更新，相对判据不会误伤（区别于绝对年龄）。
        """
        try:
            snap_mtime = watcher.out_path.stat().st_mtime
            src_mtime = Path(watcher.src).stat().st_mtime
        except OSError:
            return True
        return (src_mtime - snap_mtime) > STALE_TOLERANCE_SECONDS

    def _drop_watcher(self, cache_key: str, watcher: EncryptedShardWatcher) -> None:
        self._watchers.pop(cache_key, None)
        try:
            watcher.close()
        except Exception:
            pass

    def close_all(self) -> None:
        with self._lock:
            for watcher in self._watchers.values():
                try:
                    watcher.close()
                except Exception:
                    pass
            self._watchers.clear()


def get_snapshot_manager() -> SharedSnapshotManager:
    global _MANAGER
    if _MANAGER is None:
        with _MANAGER_LOCK:
            if _MANAGER is None:
                _MANAGER = SharedSnapshotManager()
    return _MANAGER
