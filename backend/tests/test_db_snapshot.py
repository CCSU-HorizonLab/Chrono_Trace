"""db_snapshot（EncryptedShardWatcher）单测：加密库增量解密视图。

覆盖：初始全量解密可查询、stat 短路、源更新增量刷新、
主库缺帧页占位 + WAL 已提交帧修复、WAL 代际错乱防护、未提交帧不应用、
WAL-only 快路径（主库未变不逐页重读）、reconcile 跳帧重放、并发 refresh 串行化。
"""
from __future__ import annotations

import os
import sqlite3
import sys
import threading
from pathlib import Path

backend_root = Path(__file__).parent.parent
sys.path.insert(0, str(backend_root))
sys.path.insert(0, str(Path(__file__).parent))

import pytest

from app.services.wechat.db_snapshot import EncryptedShardWatcher
from fixtures.wcdb_factory import build_plain_db, build_wal, encrypt_db, encrypt_page, PAGE

KEY_HEX = "1a" * 32

SCHEMA_V1 = """
CREATE TABLE name2id (user_name TEXT PRIMARY KEY, is_session INTEGER DEFAULT 0);
CREATE TABLE [Msg_test] (
    local_id INTEGER PRIMARY KEY, server_id INTEGER, local_type INTEGER,
    sort_seq INTEGER, real_sender_id INTEGER, create_time INTEGER,
    message_content TEXT
);
INSERT INTO name2id(user_name, is_session) VALUES ('lishao378', 0), ('wxid_zhang', 1);
INSERT INTO [Msg_test] VALUES
    (1, 1001, 1, 1, 2, 1700000000, '早'),
    (2, 1002, 1, 2, 1, 1700000060, '嗯呢'),
    (3, 1003, 1, 3, 2, 1700000120, '中午吃啥');
"""

EXTRA_ROW = ("INSERT INTO [Msg_test] VALUES "
             "(4, 1004, 1, 4, 1, 1700000180, '晚上好');")


def _diff_page_no(data_a: bytes, data_b: bytes) -> int:
    """返回 v1→v2 中变化的首个非页1数据页页号（1 起）。"""
    assert len(data_a) == len(data_b), "fixture 布局应保持同页数"
    for off in range(PAGE, len(data_a), PAGE):
        if data_a[off:off + PAGE] != data_b[off:off + PAGE]:
            return off // PAGE + 1
    raise AssertionError("两个 fixture 版本没有数据页差异")


def test_initial_decrypt_produces_queryable_view(tmp_path):
    plain = build_plain_db(tmp_path / "plain.db", SCHEMA_V1)
    src = tmp_path / "message_0.db"
    encrypt_db(plain, src, KEY_HEX)

    watcher = EncryptedShardWatcher(src, KEY_HEX, tmp_path / "cache")
    try:
        rows = watcher.connection.execute(
            "SELECT message_content FROM [Msg_test] ORDER BY sort_seq"
        ).fetchall()
        assert [r[0] for r in rows] == ["早", "嗯呢", "中午吃啥"]
        # 页1 解密产物需补 16B SQLite 头才是合法库
        assert watcher.out_path.read_bytes()[:16] == b"SQLite format 3\x00"
        assert watcher.connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    finally:
        watcher.close()
    # close 只关连接不删 sidecar：重开实例直接复用（resumed_from_disk）
    assert watcher.out_path.exists()
    again = EncryptedShardWatcher(src, KEY_HEX, tmp_path / "cache")
    try:
        assert again.resumed_from_disk is True
        rows = again.connection.execute(
            "SELECT message_content FROM [Msg_test] ORDER BY sort_seq"
        ).fetchall()
        assert [r[0] for r in rows] == ["早", "嗯呢", "中午吃啥"]
    finally:
        again.close()


def test_refresh_short_circuits_when_source_unchanged(tmp_path):
    plain = build_plain_db(tmp_path / "plain.db", SCHEMA_V1)
    src = tmp_path / "message_0.db"
    encrypt_db(plain, src, KEY_HEX)
    watcher = EncryptedShardWatcher(src, KEY_HEX, tmp_path / "cache")
    try:
        assert watcher.refresh() is False  # (mtime,size) 未变 → 零开销短路
    finally:
        watcher.close()


def test_source_update_visible_after_incremental_refresh(tmp_path):
    plain_v1 = build_plain_db(tmp_path / "v1.db", SCHEMA_V1)
    src = tmp_path / "message_0.db"
    salt, _, _ = encrypt_db(plain_v1, src, KEY_HEX)
    watcher = EncryptedShardWatcher(src, KEY_HEX, tmp_path / "cache")
    try:
        plain_v2 = build_plain_db(tmp_path / "v2.db", SCHEMA_V1 + EXTRA_ROW)
        # 同盐重加密（盐随库固定；换盐等于换库）
        encrypt_db(plain_v2, src, KEY_HEX, salt=salt)
        st = src.stat()
        os.utime(src, ns=(st.st_atime_ns, st.st_mtime_ns + 2_000_000_000))

        assert watcher.refresh() is True
        rows = watcher.connection.execute(
            "SELECT message_content FROM [Msg_test] ORDER BY sort_seq"
        ).fetchall()
        assert [r[0] for r in rows] == ["早", "嗯呢", "中午吃啥", "晚上好"]
    finally:
        watcher.close()


def test_wal_committed_frame_repairs_missing_main_page(tmp_path):
    """主库缺帧页（HMAC 必然失败）占位后由 WAL 已提交帧修复——WAL 头/帧头大端格式。"""
    plain_v1 = build_plain_db(tmp_path / "v1.db", SCHEMA_V1)
    plain_v2 = build_plain_db(tmp_path / "v2.db", SCHEMA_V1 + EXTRA_ROW)
    data1 = plain_v1.read_bytes()
    data2 = plain_v2.read_bytes()
    page_no = _diff_page_no(data1, data2)

    src = tmp_path / "message_0.db"
    salt, enc_key, mac_key = encrypt_db(plain_v1, src, KEY_HEX)
    # 模拟 WAL 模式主库尾部缺帧页：该页密文为垃圾 → 解密失败 → 零占位
    with open(src, "r+b") as f:
        f.seek((page_no - 1) * PAGE)
        f.write(os.urandom(PAGE))

    frame = encrypt_page(data2[(page_no - 1) * PAGE:page_no * PAGE],
                         enc_key, mac_key, page_no)
    build_wal(tmp_path / "message_0.db-wal", [(page_no, frame, True)])

    watcher = EncryptedShardWatcher(src, KEY_HEX, tmp_path / "cache")
    try:
        rows = watcher.connection.execute(
            "SELECT message_content FROM [Msg_test] ORDER BY sort_seq"
        ).fetchall()
        assert [r[0] for r in rows] == ["早", "嗯呢", "中午吃啥", "晚上好"]
    finally:
        watcher.close()


def test_wal_frame_generation_mismatch_is_ignored(tmp_path):
    """帧 salt 与 wal 头不一致（上一轮 checkpoint 残留）：整帧不应用，宁少读不错读。"""
    plain_v1 = build_plain_db(tmp_path / "v1.db", SCHEMA_V1)
    plain_v2 = build_plain_db(tmp_path / "v2.db", SCHEMA_V1 + EXTRA_ROW)
    data1 = plain_v1.read_bytes()
    data2 = plain_v2.read_bytes()
    page_no = _diff_page_no(data1, data2)

    src = tmp_path / "message_0.db"
    _, enc_key, mac_key = encrypt_db(plain_v1, src, KEY_HEX)
    with open(src, "r+b") as f:
        f.seek((page_no - 1) * PAGE)
        f.write(os.urandom(PAGE))

    frame = encrypt_page(data2[(page_no - 1) * PAGE:page_no * PAGE],
                         enc_key, mac_key, page_no)
    build_wal(
        tmp_path / "message_0.db-wal", [(page_no, frame, True)],
        salt=(0x11111111, 0x22222222), frame_salt=(0x99999999, 0x88888888),
    )

    watcher = EncryptedShardWatcher(src, KEY_HEX, tmp_path / "cache")
    try:
        # 缺帧页保持零占位：该表数据页损坏，查询应报错而不是给出错的数据
        with pytest.raises(sqlite3.DatabaseError):
            watcher.connection.execute(
                "SELECT message_content FROM [Msg_test] ORDER BY sort_seq"
            ).fetchall()
    finally:
        watcher.close()


def test_wal_uncommitted_frames_are_not_applied(tmp_path):
    """最后一次 commit 帧之后的未提交帧不应用（宁少读不错读）。"""
    plain_v1 = build_plain_db(tmp_path / "v1.db", SCHEMA_V1)
    plain_v2 = build_plain_db(tmp_path / "v2.db", SCHEMA_V1 + EXTRA_ROW)
    data1 = plain_v1.read_bytes()
    data2 = plain_v2.read_bytes()
    page_no = _diff_page_no(data1, data2)

    src = tmp_path / "message_0.db"
    _, enc_key, mac_key = encrypt_db(plain_v1, src, KEY_HEX)
    with open(src, "r+b") as f:
        f.seek((page_no - 1) * PAGE)
        f.write(os.urandom(PAGE))

    frame = encrypt_page(data2[(page_no - 1) * PAGE:page_no * PAGE],
                         enc_key, mac_key, page_no)
    build_wal(tmp_path / "message_0.db-wal", [(page_no, frame, False)])  # 无 commit 帧

    watcher = EncryptedShardWatcher(src, KEY_HEX, tmp_path / "cache")
    try:
        with pytest.raises(sqlite3.DatabaseError):
            watcher.connection.execute(
                "SELECT message_content FROM [Msg_test] ORDER BY sort_seq"
            ).fetchall()
    finally:
        watcher.close()


def test_page1_failure_repaired_by_wal_frame_is_kept(tmp_path):
    """主库页1解密失败但 WAL 已提交帧覆盖修复：产物完好，不得整轮抛弃。

    此前守卫只看 page1_failed 布尔——占位零页已被 WAL 帧换成合法页1的
    可用快照也被 raise 抛掉，保留过旧快照且 state 不更新、永不自愈。
    """
    plain_v1 = build_plain_db(tmp_path / "v1.db", SCHEMA_V1)
    data1 = plain_v1.read_bytes()
    src = tmp_path / "message_0.db"
    _, enc_key, mac_key = encrypt_db(plain_v1, src, KEY_HEX)
    with open(src, "r+b") as f:
        f.seek(16)
        f.write(os.urandom(PAGE - 16))  # 毁页1密文但保留 16B salt（密钥派生源）

    # decrypt_page 对页1帧同样跳 16B 前缀（offset=SALT_SIZE）：帧需带 16B
    # 哑前缀补齐 4096B，_apply_wal 解出 4080B 后再补 16B SQLite 头成整页
    frame = encrypt_page(data1[0:PAGE], enc_key, mac_key, 1, salt=b"\x00" * 16)
    build_wal(tmp_path / "message_0.db-wal", [(1, frame, True)])

    watcher = EncryptedShardWatcher(src, KEY_HEX, tmp_path / "cache")
    try:
        rows = watcher.connection.execute(
            "SELECT message_content FROM [Msg_test] ORDER BY sort_seq"
        ).fetchall()
        assert [r[0] for r in rows] == ["早", "嗯呢", "中午吃啥"]
    finally:
        watcher.close()


def test_page1_failure_without_wal_repair_discards_snapshot(tmp_path):
    """页1解密失败且 WAL 未覆盖：占位零页留在产物里，查询必须报错而非给错数据。"""
    plain_v1 = build_plain_db(tmp_path / "v1.db", SCHEMA_V1)
    src = tmp_path / "message_0.db"
    encrypt_db(plain_v1, src, KEY_HEX)
    with open(src, "r+b") as f:
        f.seek(16)
        f.write(os.urandom(PAGE - 16))  # 保留 salt，仅毁页1密文

    watcher = EncryptedShardWatcher(src, KEY_HEX, tmp_path / "cache")
    try:
        with pytest.raises(sqlite3.DatabaseError):
            watcher.connection.execute(
                "SELECT message_content FROM [Msg_test] ORDER BY sort_seq"
            ).fetchall()
    finally:
        watcher.close()


def _v2_frames(data1: bytes, data2: bytes, enc_key: bytes, mac_key: bytes):
    """构造 v1→v2 的全部差异数据页帧（最后一帧为 commit），与真实 WAL 写入同构。

    跳过页 1（change counter 差异）：WAL 帧里的页 1 不带 salt 前缀，
    且旧 change counter 不影响 immutable 只读——与既有 WAL 用例同口径。
    """
    pages = [p for p in range(2, len(data1) // PAGE + 1)
             if data1[(p - 1) * PAGE:p * PAGE] != data2[(p - 1) * PAGE:p * PAGE]]
    assert pages, "fixture 版本无差异页"
    return [(p, encrypt_page(data2[(p - 1) * PAGE:p * PAGE], enc_key, mac_key, p),
             idx == len(pages) - 1)
            for idx, p in enumerate(pages)]


def _bump_mtime(path: Path) -> None:
    st = path.stat()
    os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns + 2_000_000_000))


def test_wal_only_fast_path_when_main_unchanged(tmp_path):
    """主库 stat 未变、仅 -wal 变化 → 快路径（不逐页重读主库）且新内容可见。"""
    plain_v1 = build_plain_db(tmp_path / "v1.db", SCHEMA_V1)
    plain_v2 = build_plain_db(tmp_path / "v2.db", SCHEMA_V1 + EXTRA_ROW)
    src = tmp_path / "message_0.db"
    _, enc_key, mac_key = encrypt_db(plain_v1, src, KEY_HEX)

    watcher = EncryptedShardWatcher(src, KEY_HEX, tmp_path / "cache")
    try:
        full_calls: list[int] = []
        orig_full = watcher._refresh_full

        def counting_full(state, force):
            full_calls.append(1)
            return orig_full(state, force)

        watcher._refresh_full = counting_full

        frames = _v2_frames(plain_v1.read_bytes(), plain_v2.read_bytes(), enc_key, mac_key)
        build_wal(tmp_path / "message_0.db-wal", frames)

        assert watcher.refresh() is True
        assert full_calls == []  # 快路径生效：全量路径未被触碰
        rows = watcher.connection.execute(
            "SELECT message_content FROM [Msg_test] ORDER BY sort_seq"
        ).fetchall()
        assert [r[0] for r in rows] == ["早", "嗯呢", "中午吃啥", "晚上好"]
        assert watcher.connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert watcher.refresh() is False  # 快路径提交 state 后恢复 stat 短路
        assert watcher._overlay_dirty is False  # 无跳帧不标脏
    finally:
        watcher.close()


def test_reconcile_replays_skipped_wal_frames(tmp_path):
    """撕裂帧被跳过标脏 → stat 不再变化也靠 reconcile 重放自愈；干净后零开销。"""
    plain_v1 = build_plain_db(tmp_path / "v1.db", SCHEMA_V1)
    plain_v2 = build_plain_db(tmp_path / "v2.db", SCHEMA_V1 + EXTRA_ROW)
    data1 = plain_v1.read_bytes()
    data2 = plain_v2.read_bytes()
    src = tmp_path / "message_0.db"
    _, enc_key, mac_key = encrypt_db(plain_v1, src, KEY_HEX)
    valid_frames = _v2_frames(data1, data2, enc_key, mac_key)
    torn_frames = [(p, os.urandom(PAGE), commit) for p, _f, commit in valid_frames]
    wal_path = tmp_path / "message_0.db-wal"

    watcher = EncryptedShardWatcher(src, KEY_HEX, tmp_path / "cache")
    try:
        build_wal(wal_path, torn_frames)
        assert watcher.refresh() is True
        assert watcher._overlay_dirty is True  # 帧解密全失败 → 标脏
        rows = watcher.connection.execute(
            "SELECT count(*) FROM [Msg_test]").fetchone()
        assert rows[0] == 3  # 帧被跳过，内容停留在 v1

        # wal 内容修复（真实场景：微信写入完成后撕裂页补齐）
        build_wal(wal_path, valid_frames)
        _bump_mtime(wal_path)
        assert watcher.refresh(reconcile=True) is True  # 脏 → 重放
        rows = watcher.connection.execute(
            "SELECT message_content FROM [Msg_test] ORDER BY sort_seq"
        ).fetchall()
        assert [r[0] for r in rows][-1] == "晚上好"
        assert watcher._overlay_dirty is False  # 重放无跳帧 → 清脏
        assert watcher.refresh(reconcile=True) is False  # 干净 → stat 短路零开销
    finally:
        watcher.close()


def test_concurrent_refresh_is_serialized_by_lock(tmp_path):
    """两线程并发 refresh（wal 风暴）：实例锁串行化，无撕裂/无异常，快照完好。"""
    plain_v1 = build_plain_db(tmp_path / "v1.db", SCHEMA_V1)
    plain_v2 = build_plain_db(tmp_path / "v2.db", SCHEMA_V1 + EXTRA_ROW)
    data1 = plain_v1.read_bytes()
    data2 = plain_v2.read_bytes()
    src = tmp_path / "message_0.db"
    _, enc_key, mac_key = encrypt_db(plain_v1, src, KEY_HEX)
    valid_frames = _v2_frames(data1, data2, enc_key, mac_key)
    torn_frames = [(p, os.urandom(PAGE), commit) for p, _f, commit in valid_frames]
    wal_path = tmp_path / "message_0.db-wal"

    watcher = EncryptedShardWatcher(src, KEY_HEX, tmp_path / "cache")
    errors: list[Exception] = []

    def storm(seq):
        for frames in seq:
            try:
                build_wal(wal_path, frames)
                watcher.refresh()
            except Exception as exc:  # noqa: BLE001 —— 风暴线程收集一切异常
                errors.append(exc)

    seq_a = [valid_frames if i % 2 else torn_frames for i in range(30)]
    seq_b = [torn_frames if i % 2 else valid_frames for i in range(30)]
    threads = [threading.Thread(target=storm, args=(s,)) for s in (seq_a, seq_b)]
    try:
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert errors == []
        # 风暴后快照仍是完好可查的库（此前的竞态会替换出撕裂文件）
        assert watcher.connection.execute(
            "PRAGMA integrity_check").fetchone()[0] == "ok"
        assert watcher.connection.execute(
            "SELECT count(*) FROM [Msg_test]").fetchone()[0] >= 3
    finally:
        watcher.close()


def test_wrong_key_full_failure_keeps_old_snapshot(tmp_path):
    """密钥错误全页解密失败：refresh 报失败且不落全零快照。

    此前全页失败仍 os.replace 提交零快照并返回成功，state 更新后
    stat 不变永不重试，下游 open 报 "file is not a database"。
    """
    plain = build_plain_db(tmp_path / "plain.db", SCHEMA_V1)
    src = tmp_path / "message_0.db"
    encrypt_db(plain, src, KEY_HEX)

    # 先用正确密钥建立完好的旧快照
    good = EncryptedShardWatcher(src, KEY_HEX, tmp_path / "cache")
    good.refresh(force=True)
    snapshot_before = Path(str(good.out_path)).read_bytes()
    good.close()

    # 换错密钥 + 源库变动（touch mtime 即可触发 stat 变化路径）
    bad = EncryptedShardWatcher(src, "9f" * 32, tmp_path / "cache2")
    try:
        ok = bad.refresh(force=True)
        assert ok is False  # 全页失败 → 判失败，不报成功
        # 错密钥 watcher 不应产出全零快照文件
        assert not bad.out_path.exists()
    finally:
        bad.close()

    # 原快照完好未被破坏（另一 cache 目录中的独立副本）
    again = EncryptedShardWatcher(src, KEY_HEX, tmp_path / "cache")
    try:
        assert Path(str(again.out_path)).read_bytes() == snapshot_before
    finally:
        again.close()


def test_full_refresh_failure_leaves_page_hashes_untouched(tmp_path):
    """全量刷新中途失败：内存页哈希不得被本轮新值污染（W4）。

    此前页循环即时写 _page_hashes：失败轮（页1守卫 raise）丢弃 .tmp 保留
    旧快照，但内存哈希已是新值——下轮「源未变」哈希命中 →
    _read_decrypted_page 从旧快照拷旧明文，错误被永久固化。
    """
    plain_v1 = build_plain_db(tmp_path / "v1.db", SCHEMA_V1)
    src = tmp_path / "message_0.db"
    salt, _, _ = encrypt_db(plain_v1, src, KEY_HEX)
    watcher = EncryptedShardWatcher(src, KEY_HEX, tmp_path / "cache")
    try:
        clean_hashes = dict(watcher._page_hashes)

        # 源更新（同盐重加密）
        plain_v2 = build_plain_db(tmp_path / "v2.db", SCHEMA_V1 + EXTRA_ROW)
        encrypt_db(plain_v2, src, KEY_HEX, salt=salt)
        st = src.stat()
        os.utime(src, ns=(st.st_atime_ns, st.st_mtime_ns + 2_000_000_000))

        # 页1 解密必败 → 全零守卫 raise → 整轮失败
        real_decrypt = watcher._decrypt_raw

        def _fail_page1(raw, page_no):
            if page_no == 1:
                raise RuntimeError("页 1 解密失败（测试注入）")
            return real_decrypt(raw, page_no)

        watcher._decrypt_raw = _fail_page1
        assert watcher.refresh() is False
        assert watcher._page_hashes == clean_hashes, "失败轮不得污染内存页哈希"

        # 解除注入后同源重试：成功且新内容可见（自愈路径）
        watcher._decrypt_raw = real_decrypt
        assert watcher.refresh() is True
        rows = watcher.connection.execute(
            "SELECT message_content FROM [Msg_test] ORDER BY sort_seq"
        ).fetchall()
        assert [r[0] for r in rows] == ["早", "嗯呢", "中午吃啥", "晚上好"]
    finally:
        watcher.close()


def test_wal_fast_path_failure_leaves_page_hashes_untouched(tmp_path, monkeypatch):
    """WAL 快路径中途失败：帧页哈希不得即时入内存（W4 同族）。"""
    plain_v1 = build_plain_db(tmp_path / "v1.db", SCHEMA_V1)
    plain_v2 = build_plain_db(tmp_path / "v2.db", SCHEMA_V1 + EXTRA_ROW)
    data1 = plain_v1.read_bytes()
    data2 = plain_v2.read_bytes()
    page_no = _diff_page_no(data1, data2)

    src = tmp_path / "message_0.db"
    salt, enc_key, mac_key = encrypt_db(plain_v1, src, KEY_HEX)
    watcher = EncryptedShardWatcher(src, KEY_HEX, tmp_path / "cache")
    try:
        clean_hashes = dict(watcher._page_hashes)
        rows_before = [r[0] for r in watcher.connection.execute(
            "SELECT message_content FROM [Msg_test] ORDER BY sort_seq")]

        # 主库不动、仅挂 -wal（快路径条件：主库 stat 未变），帧已提交
        frame = encrypt_page(
            data2[(page_no - 1) * PAGE:page_no * PAGE], enc_key, mac_key, page_no
        )
        build_wal(tmp_path / "message_0.db-wal", [(page_no, frame, True)])

        # 注入快路径收尾 os.replace 失败（帧已应用到 .tmp、pending 哈希已暂存）
        # → 整轮失败。此前帧哈希即时入内存，replace 失败即污染
        real_replace = os.replace

        def _boom_replace(src_p, dst_p, *a, **k):
            if ".tmp." in str(src_p):  # 快照临时名已唯一化（pid+线程 id 后缀）
                raise OSError("replace 模拟故障（测试注入）")
            return real_replace(src_p, dst_p, *a, **k)

        monkeypatch.setattr(os, "replace", _boom_replace)
        assert watcher.refresh() is False
        monkeypatch.undo()
        assert watcher._page_hashes == clean_hashes, "快路径失败不得污染页哈希"
        # 旧快照原封未动
        rows_after = [r[0] for r in watcher.connection.execute(
            "SELECT message_content FROM [Msg_test] ORDER BY sort_seq")]
        assert rows_after == rows_before
    finally:
        watcher.close()


def test_tmp_sibling_unique_across_threads_and_close_globs(tmp_path):
    """W9：临时文件名带 pid+线程 id——跨实例同源并发不再共用固定 .tmp。

    实例锁只防本实例线程；stop 放弃路径的旧 watcher 与新 provider 实例
    并发刷同一分片时会交错写同一固定 .tmp、os.replace 发布撕裂快照。
    """
    plain = build_plain_db(tmp_path / "plain.db", SCHEMA_V1)
    src = tmp_path / "message_0.db"
    encrypt_db(plain, src, KEY_HEX)
    watcher = EncryptedShardWatcher(src, KEY_HEX, tmp_path / "cache")
    try:
        main_path = watcher._tmp_sibling(watcher.out_path)
        assert ".tmp." in main_path.name, "临时名必须唯一化（含 pid+线程 id）"

        other: list = []

        def _in_thread():
            other.append(watcher._tmp_sibling(watcher.out_path))

        t = threading.Thread(target=_in_thread)
        t.start()
        t.join()
        assert other[0] != main_path, "不同线程的临时名必须互不相同"

        # close 的前缀 glob 清理必须覆盖唯一名残留
        stale = tmp_path / "cache" / (watcher.out_path.name + f".tmp.{os.getpid()}.999999")
        stale.write_bytes(b"x")
        watcher.close()
        assert not stale.exists()
    finally:
        watcher.close()


def test_two_instances_refreshing_same_shard_do_not_collide(tmp_path):
    """同源两实例并发强刷：唯一临时名 + 原子 replace，互不撕裂。"""
    plain = build_plain_db(tmp_path / "plain.db", SCHEMA_V1)
    src = tmp_path / "message_0.db"
    encrypt_db(plain, src, KEY_HEX)
    a = EncryptedShardWatcher(src, KEY_HEX, tmp_path / "cache")
    b = EncryptedShardWatcher(src, KEY_HEX, tmp_path / "cache")
    errors: list = []
    try:
        def _force(w):
            try:
                w.refresh(force=True)
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)

        ta = threading.Thread(target=_force, args=(a,))
        tb = threading.Thread(target=_force, args=(b,))
        ta.start()
        tb.start()
        ta.join()
        tb.join()

        assert not errors, f"并发刷新不得抛错: {errors}"
        assert a.connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    finally:
        a.close()
        b.close()
