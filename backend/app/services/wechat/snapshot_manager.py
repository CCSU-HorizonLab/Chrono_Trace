"""共享增量解密快照管理器：导入链路复用 watcher 解密副本，免全量重解密。

问题：ContactDBV4 / MessageDBV4 每次构造都把加密库**全量解密到临时文件**
（~19 分片×几十 MB 全页 AES），增量同步也要付全量代价（~45s）。

方案：模块级单例维护 EncryptedShardWatcher 实例——首次调用做全量解密
（与原路径等价），后续调用 watcher.refresh() 仅解密变化页（增量秒级）。
适配器（ContactDBV4 / MessageDBV4）优先从本管理器取解密副本路径。
"""
from __future__ import annotations

import logging
import threading
from pathlib import Path

from .db_snapshot import EncryptedShardWatcher
from ...config import TEMP_DIR_PATH

logger = logging.getLogger(__name__)

_MANAGER: "SharedSnapshotManager | None" = None
_MANAGER_LOCK = threading.Lock()


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
        cache_key = str(src_path.resolve())
        with self._lock:
            watcher = self._watchers.get(cache_key)
            if watcher is None:
                try:
                    watcher = EncryptedShardWatcher(
                        src_path, key_hex, self._cache_dir, raw_keys=raw_keys
                    )
                    self._watchers[cache_key] = watcher
                    logger.info("[SnapshotManager] 首次解密 %s → %s",
                                src_path.name, watcher.out_path)
                except Exception as exc:
                    logger.warning("[SnapshotManager] 首次解密失败 %s: %s", src_path, exc)
                    return None
            else:
                # 已有快照：增量刷新（mtime 变化才实际操作，stat 短路零开销）
                try:
                    watcher.refresh()
                except Exception as exc:
                    logger.warning("[SnapshotManager] 增量刷新失败 %s（用旧快照）: %s", src_path, exc)
            return watcher.out_path

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
