"""SharedSnapshotManager 内存缓存安全测试（W4）。

两个审查确认缺陷：
1. 内存 watcher 缓存键只有源路径——换账号/密钥重捕获后同路径拿到旧
   watcher，旧密钥解新数据全 HMAC 失败（磁盘 sidecar 有 key_fp 校验，
   内存没有）
2. refresh 失败后无界返回旧快照——源已领先快照很久时，导入在旧数据上
   照常推进水位，窗口内新消息永久丢失
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

backend_root = Path(__file__).parent.parent
sys.path.insert(0, str(backend_root))
sys.path.insert(0, str(Path(__file__).parent))

from app.services.wechat.snapshot_manager import SharedSnapshotManager, _key_identity


class FakeWatcher:
    """免解密的 watcher 替身：记录 refresh/close 调用。"""

    def __init__(self, src: Path, out_path: Path):
        self.src = src
        self.out_path = out_path
        self.refresh_calls = 0
        self.closed = False
        self.resumed_from_disk = False

    def refresh(self, force=False, reconcile=False) -> bool:
        self.refresh_calls += 1
        return True

    def close(self):
        self.closed = True


def _manager_with_watcher(tmp_path: Path, key_hex: str) -> tuple[SharedSnapshotManager, FakeWatcher]:
    """造一个含单 FakeWatcher 的 manager（绕过真实解密）。"""
    mgr = SharedSnapshotManager()
    src = tmp_path / "message_0.db"
    out = tmp_path / "out.dec.db"
    out.write_bytes(b"snapshot")
    watcher = FakeWatcher(src, out)
    # 源文件必须存在且安静（mtime 旧于快照），否则 _is_stale 会判陈旧误伤
    import os
    src.write_bytes(b"encrypted-src")
    quiet = time.time() - 7200
    os.utime(src, (quiet, quiet))
    from app.services.wechat.snapshot_manager import _key_identity
    mgr._watchers[f"{src.resolve()}|{_key_identity(key_hex, None)}"] = watcher
    return mgr, watcher


class TestCacheKeyFingerprint:

    def test_different_key_gets_fresh_watcher(self, tmp_path, monkeypatch):
        """同路径不同密钥：不得复用旧 watcher（旧密钥解新数据必败）。"""
        mgr, watcher = _manager_with_watcher(tmp_path, "aa" * 32)
        made = []

        def _fake_watcher_factory(src, key_hex, cache_dir, raw_keys=None):
            w = FakeWatcher(Path(src), tmp_path / "out2.dec.db")
            (tmp_path / "out2.dec.db").write_bytes(b"snapshot2")
            made.append((key_hex, w))
            return w

        monkeypatch.setattr(
            "app.services.wechat.db_snapshot.EncryptedShardWatcher", _fake_watcher_factory
        )
        # snapshot_manager 用的是 from .db_snapshot import EncryptedShardWatcher
        import app.services.wechat.snapshot_manager as sm
        monkeypatch.setattr(sm, "EncryptedShardWatcher", _fake_watcher_factory)

        path2 = mgr.get_decrypted_path(tmp_path / "message_0.db", "bb" * 32)
        assert path2 is not None
        assert len(made) == 1, "不同密钥必须新建 watcher"
        assert made[0][0] == "bb" * 32

    def test_same_key_reuses_watcher(self, tmp_path, monkeypatch):
        """同路径同密钥：复用缓存 watcher（增量刷新快路径语义不变）。"""
        mgr, watcher = _manager_with_watcher(tmp_path, "aa" * 32)

        def _should_not_build(*a, **k):
            raise AssertionError("同密钥不应新建 watcher")

        import app.services.wechat.snapshot_manager as sm
        monkeypatch.setattr(sm, "EncryptedShardWatcher", _should_not_build)

        path = mgr.get_decrypted_path(tmp_path / "message_0.db", "aa" * 32)
        assert path == watcher.out_path
        assert watcher.refresh_calls == 1

    def test_key_identity_distinguishes_raw_keys(self):
        """raw_keys 不同 → 身份不同（Windows 只读扫描产物更新场景）。"""
        assert _key_identity("k", {"aa": "01"}) != _key_identity("k", {"aa": "02"})
        assert _key_identity("k", None) != _key_identity("k", {"aa": "01"})
        assert _key_identity("k1", None) != _key_identity("k2", None)
        assert _key_identity(" k ", None) == _key_identity("k", None)


class TestStaleSnapshotGuard:

    def _set_mtimes(self, watcher: FakeWatcher, src_delta: float, snap_delta: float):
        now = time.time()
        Path(watcher.src).write_bytes(b"src")
        import os
        os.utime(watcher.src, (now - src_delta, now - src_delta))
        os.utime(watcher.out_path, (now - snap_delta, now - snap_delta))

    def test_stale_snapshot_dropped_and_returns_none(self, tmp_path):
        """源领先快照超过容差：丢弃 watcher、返回 None（走全量兜底）。"""
        import app.services.wechat.snapshot_manager as sm
        tolerance = sm.STALE_TOLERANCE_SECONDS
        mgr, watcher = _manager_with_watcher(tmp_path, "aa" * 32)
        # 源比快照新 10×容差
        self._set_mtimes(watcher, src_delta=tolerance * 10, snap_delta=tolerance * 20)

        assert mgr.get_decrypted_path(
            tmp_path / "message_0.db", "aa" * 32) is None
        assert watcher.closed, "陈旧 watcher 必须 close"
        assert not mgr._watchers, "缓存必须清空待重建"

    def test_fresh_snapshot_still_served(self, tmp_path):
        """源与快照时间接近（含安静账号源更旧）：正常返回快照。"""
        mgr, watcher = _manager_with_watcher(tmp_path, "aa" * 32)
        # 快照比源还新（正常：刚刷新完）→ 不陈旧
        self._set_mtimes(watcher, src_delta=3600, snap_delta=10)
        assert mgr.get_decrypted_path(
            tmp_path / "message_0.db", "aa" * 32) == watcher.out_path
        assert not watcher.closed

    def test_new_branch_stale_sidecar_rejected(self, tmp_path, monkeypatch):
        """新建分支同样拒陈旧：sidecar 恢复后增量失败只保留旧快照。

        EncryptedShardWatcher.__init__ 的 refresh 吞错不抛——构造"成功"
        但磁盘快照可能已领先源很久，不查会把旧快照当当前数据发出。
        """
        import app.services.wechat.snapshot_manager as sm
        import os
        tolerance = sm.STALE_TOLERANCE_SECONDS

        src = tmp_path / "message_0.db"
        src.write_bytes(b"encrypted-src")
        out = tmp_path / "old.dec.db"
        out.write_bytes(b"old-snapshot")

        class _StaleSidecarWatcher(FakeWatcher):
            def __init__(self, src_p, key_hex, cache_dir, raw_keys=None):
                super().__init__(Path(src_p), out)
                self.resumed_from_disk = True  # sidecar 命中路径

        # 源比磁盘旧快照新 10×容差（上次会话崩溃后源持续被写）
        now = time.time()
        os.utime(src, (now - tolerance * 10, now - tolerance * 10))
        os.utime(out, (now - tolerance * 20, now - tolerance * 20))

        monkeypatch.setattr(sm, "EncryptedShardWatcher", _StaleSidecarWatcher)
        mgr = SharedSnapshotManager()
        assert mgr.get_decrypted_path(src, "aa" * 32) is None
        assert not mgr._watchers, "陈旧 sidecar watcher 不得入缓存"
