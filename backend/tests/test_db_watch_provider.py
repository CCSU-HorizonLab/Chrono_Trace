"""db_watch 实时监听 provider 单测（离线：合成加密分片，无真实微信）。

覆盖：初始化密钥校验、跨分片定位 Msg 表、窗口语义（WINDOW/PAGE 翻页）、
sender 归属（目录名后缀剥离）、local_type 词表映射、源库增量刷新可见、
消息模型哈希与兼容属性。
"""
from __future__ import annotations

import hashlib
import os
import time
import sys
from pathlib import Path

backend_root = Path(__file__).parent.parent
sys.path.insert(0, str(backend_root))
sys.path.insert(0, str(Path(__file__).parent))

import pytest

from app.services.realtime.providers import db_watch as dbw
from app.services.realtime.providers.db_watch import DbWatchRealtimeProvider
from app.services.realtime.providers.models import (
    RealtimeMessage,
    build_message_hash,
)
from fixtures.wcdb_factory import build_plain_db, encrypt_db

KEY_HEX = "2b" * 32
MY_DIR_ACCOUNT = "lishao378_86f8"   # 目录名带后缀
MY_PLAIN_NAME = "lishao378"         # name2id 存无后缀真名

ZHANG = "wxid_zhang"
LI = "wxid_li"


def test_build_message_hash_is_stable():
    first = build_message_hash(
        "wechat_41x",
        "friend",
        "text",
        "  hello   world ",
        123,
        "abc",
    )
    second = build_message_hash(
        "wechat_41x",
        "friend",
        "text",
        "hello world",
        123,
        "abc",
    )
    third = build_message_hash(
        "wechat_41x",
        "friend",
        "text",
        "hello world",
        124,
        "abc",
    )

    assert first == second
    assert first != third


def test_realtime_message_exposes_compatibility_properties():
    msg = RealtimeMessage(
        runtime_id="r1",
        sender_attr="self",
        content="hi",
        message_type="text",
        timestamp_label="12:34",
        timestamp=1234,
        message_hash="hash1",
    )

    assert msg.id == "r1"
    assert msg.hash == "hash1"
    assert msg.type == "text"
    assert msg.time == "12:34"
    assert msg.CreateTime == "12:34"
    assert msg.is_self is True


def _msg_table(username: str) -> str:
    return "Msg_" + hashlib.md5(username.encode("utf-8")).hexdigest()


def _shard_script(table_username: str, rows_sql: str, with_name2id: bool = True) -> str:
    name2id = (
        f"INSERT INTO name2id(user_name, is_session) VALUES "
        f"('{MY_PLAIN_NAME}', 0), ('{ZHANG}', 1), ('{LI}', 1);"
        if with_name2id else ""
    )
    return f"""
CREATE TABLE name2id (user_name TEXT PRIMARY KEY, is_session INTEGER DEFAULT 0);
CREATE TABLE [{_msg_table(table_username)}] (
    local_id INTEGER PRIMARY KEY, server_id INTEGER, local_type INTEGER,
    sort_seq INTEGER, real_sender_id INTEGER, create_time INTEGER,
    message_content TEXT
);
{name2id}
{rows_sql}
"""


def _zhang_rows() -> str:
    values = []
    for i in range(1, 61):  # 60 条文本：1/2 本人，其余对方
        sender = 1 if i % 2 == 0 else 2
        values.append(f"({i}, 9000{i}, 1, {i}, {sender}, 1700000000 + {i * 60}, 'msg-{i:02d}')")
    # 特殊类型追加在最新端（窗口默认取最新 WINDOW 条）
    values.append("(61, 9061, 3, 61, 2, 1700040, 'img-sentinel')")       # 图片
    values.append("(62, 9062, 34, 62, 1, 1700060, 'voice-sentinel')")    # 语音
    values.append("(63, 9063, 10000, 63, 0, 1700080, '<sysmsg>拍了拍你</sysmsg>')")  # 系统
    return "INSERT INTO [" + _msg_table(ZHANG) + "] VALUES " + ",".join(values) + ";"


@pytest.fixture
def provider_env(tmp_path, monkeypatch):
    """构造双分片加密库 + 打桩账号配置，返回 (provider, shard1_plain_rebuilder)。"""
    shard1_plain = tmp_path / "p0.db"
    shard2_plain = tmp_path / "p1.db"
    build_plain_db(shard1_plain, _shard_script(ZHANG, _zhang_rows()))
    build_plain_db(shard2_plain, _shard_script(
        LI,
        "INSERT INTO [" + _msg_table(LI) + "] VALUES (1, 7001, 1, 1, 2, 1700000100, 'li-hello');",
    ))

    shard1 = tmp_path / "message_0.db"
    shard2 = tmp_path / "message_1.db"
    salt1, _, _ = encrypt_db(shard1_plain, shard1, KEY_HEX)
    encrypt_db(shard2_plain, shard2, KEY_HEX)

    monkeypatch.setattr(dbw, "load_settings_from_file", lambda: {})
    monkeypatch.setattr(
        dbw, "get_active_wechat_account",
        lambda _settings: {"db_key": KEY_HEX, "wechat_dir": str(tmp_path),
                           "wxid": MY_DIR_ACCOUNT},
    )

    class _FakeFinder:
        @staticmethod
        def find_databases(_wxid, _wechat_dir):
            return {"message": [str(shard1), str(shard2)]}

    monkeypatch.setattr(dbw, "WeChatPathFinder", _FakeFinder)
    monkeypatch.setattr(dbw, "TEMP_DIR_PATH", str(tmp_path / "cache"))
    # 联系人解析不落真实开发库：强制走「原名即 username」回退分支
    def _no_db():
        raise RuntimeError("tests: no app db")
    monkeypatch.setattr("app.db.connection.get_db", _no_db)

    provider = DbWatchRealtimeProvider()
    provider.initialize()
    yield provider, {
        "tmp_path": tmp_path, "shard1": shard1, "salt1": salt1,
        "shard1_plain": shard1_plain,
    }
    provider.close()


def test_initialize_rejects_wrong_key(tmp_path, monkeypatch):
    shard_plain = tmp_path / "p.db"
    build_plain_db(shard_plain, _shard_script(ZHANG, _zhang_rows()))
    shard = tmp_path / "message_0.db"
    encrypt_db(shard_plain, shard, KEY_HEX)

    monkeypatch.setattr(dbw, "load_settings_from_file", lambda: {})
    monkeypatch.setattr(
        dbw, "get_active_wechat_account",
        lambda _s: {"db_key": "ff" * 32, "wechat_dir": str(tmp_path), "wxid": MY_DIR_ACCOUNT},
    )

    class _FakeFinder:
        @staticmethod
        def find_databases(_wxid, _wechat_dir):
            return {"message": [str(shard)]}

    monkeypatch.setattr(dbw, "WeChatPathFinder", _FakeFinder)
    monkeypatch.setattr(dbw, "TEMP_DIR_PATH", str(tmp_path / "cache"))

    from app.services.realtime.providers.base import ProviderInitError
    with pytest.raises(ProviderInitError):
        DbWatchRealtimeProvider().initialize()


def test_open_chat_unknown_contact_returns_false(provider_env):
    provider, _ = provider_env
    assert provider.open_chat("wxid_nobody") is False
    assert provider.list_visible_messages() == []


def test_open_chat_locates_table_in_second_shard(provider_env):
    provider, _ = provider_env
    assert provider.open_chat(LI) is True
    msgs = provider.list_visible_messages()
    assert len(msgs) == 1
    assert msgs[0].content == "li-hello"


def test_window_semantics_and_ordering(provider_env):
    provider, _ = provider_env
    assert provider.open_chat(ZHANG) is True

    msgs = provider.list_visible_messages()
    assert len(msgs) == provider.WINDOW  # 63 条 → 取最新 50
    seqs = [m.metadata["sort_seq"] for m in msgs]
    assert seqs == sorted(seqs)          # oldest → newest
    assert seqs[-1] == 63
    assert seqs[0] == 63 - provider.WINDOW + 1

    # 翻页：向上扩展窗口，向下收回
    provider.scroll_up(1)                # +200 → 覆盖全部 63 条
    assert len(provider.list_visible_messages()) == 63
    provider.scroll_down(1)              # max(0, 250-200)=50
    assert len(provider.list_visible_messages()) == 50


def test_sender_attribution_via_suffix_stripped_name2id(provider_env):
    provider, _ = provider_env
    assert provider.open_chat(ZHANG) is True
    provider.scroll_up(1)
    msgs = provider.list_visible_messages()

    # 目录账号 lishao378_86f8 → name2id 真名 lishao378（rowid=1）
    by_seq = {m.metadata["sort_seq"]: m for m in msgs}
    assert by_seq[2].sender_attr == "self"     # real_sender_id=1 → 本人
    assert by_seq[1].sender_attr == "friend"   # real_sender_id=2 → 对方
    self_count = sum(1 for m in msgs if m.sender_attr == "self")
    assert self_count == 30 + 1                # 60 条文本中偶数序号 + 1 条语音


def test_local_type_mapping_and_placeholders(provider_env):
    provider, _ = provider_env
    assert provider.open_chat(ZHANG) is True
    msgs = provider.list_visible_messages()
    by_type = {m.metadata["local_type"]: m for m in msgs}

    assert by_type[3].message_type == "image"
    assert by_type[3].content == "[图片]"
    assert by_type[34].message_type == "voice"
    assert by_type[34].content == "[语音]"
    assert by_type[10000].message_type == "system"
    assert by_type[10000].content == "拍了拍你"
    assert by_type[10000].is_system is True
    assert by_type[1].message_type == "text"
    assert by_type[1].content.startswith("msg-")


def test_text_channel_binary_content_placeholderized(provider_env):
    """文本通道统一走 content_codec 归一（回归：此前只查 zstd magic，
    protobuf 类二进制 errors='replace' 强解后的 FFFD 汤直进显示管线）"""
    provider, _ = provider_env
    base = {"local_type": 1, "real_sender_id": 2, "create_time": 1700000000,
            "local_id": 1, "server_id": 1}

    zstd_msg = provider._to_message(0, {**base, "message_content": b"\x28\xb5\x2f\xfd" + b"\x00" * 20}, 0)
    assert zstd_msg.content == "[压缩消息]"

    binary_msg = provider._to_message(0, {**base, "message_content": bytes(range(0x80, 0x90)) * 8}, 0)
    assert binary_msg.content == "[压缩消息]"  # 非 zstd 二进制同走占位符

    soup_msg = provider._to_message(0, {**base, "message_content": "��(2/�" + "x" * 30}, 0)
    assert soup_msg.content == "[压缩消息]"  # 强解汤文本拦截

    text_msg = provider._to_message(0, {**base, "message_content": "正常消息"}, 0)
    assert text_msg.content == "正常消息"


def test_new_message_visible_after_source_update(provider_env):
    provider, env = provider_env
    assert provider.open_chat(ZHANG) is True

    # 源库追加一条新消息（同盐重加密 + mtime 前移，模拟微信落盘）
    plain_v2 = env["tmp_path"] / "p0_v2.db"
    build_plain_db(
        plain_v2,
        _shard_script(ZHANG, _zhang_rows() + _extra_insert(64)),
    )
    encrypt_db(plain_v2, env["shard1"], KEY_HEX, salt=env["salt1"])
    st = env["shard1"].stat()
    os.utime(env["shard1"], ns=(st.st_atime_ns, st.st_mtime_ns + 2_000_000_000))

    msgs = provider.list_visible_messages()
    assert msgs[-1].content == "live-new"
    assert msgs[-1].sender_attr == "self"


def _extra_insert(local_id: int) -> str:
    return ("INSERT INTO [" + _msg_table(ZHANG) + "] VALUES "
            f"({local_id}, 9999, 1, {local_id}, 1, 1700100, 'live-new');")


def test_list_visible_messages_refreshes_only_target_shards(provider_env, monkeypatch):
    """每轮（含 reconcile 周期）只刷目标表所在分片：fts/media 等非目标
    分片监听期间无人查询，不挡查询与消息上屏；其新鲜度由 open_chat
    定位前的全分片刷统一追上。"""
    provider, _ = provider_env
    assert provider.open_chat(ZHANG) is True  # 目标表在分片 0

    calls: list[int] = []
    for i, w in enumerate(provider._watchers):
        monkeypatch.setattr(w, "refresh", lambda *a, _i=i, **k: (calls.append(_i), False)[1])

    provider._last_reconcile = time.monotonic()  # 压住 reconcile 周期
    provider.list_visible_messages()
    assert calls == [0], "非目标分片不应在每轮被同步刷新"

    # reconcile 周期到达时也只重放目标分片（无变化则被短路缓存接住）
    calls.clear()
    provider._last_reconcile = 0.0
    provider.list_visible_messages()
    assert calls == [0], "reconcile 周期同样只刷目标分片"


def test_inotify_adopts_lazily_created_wal(tmp_path):
    """懒创建的 -wal：目录 IN_CREATE 事件触发后转挂文件级监听。

    此前 _start_inotify 只对启动时已存在的文件注册——-wal 由 SQLite
    首写懒创建，监听启动时缺失即永无通知，毫秒级响应退化为 10s
    reconcile 兜底。
    """
    import threading
    import types

    provider = DbWatchRealtimeProvider.__new__(DbWatchRealtimeProvider)
    provider._wakeup_event = threading.Event()
    provider._inotify_fd = -1
    provider._inotify_thread = None
    provider._pending_wal_checks = []
    provider._libc = None
    provider._last_nochange_result = None
    db_path = tmp_path / "Msg_0.db"
    db_path.write_bytes(b"placeholder")
    provider._watchers = [types.SimpleNamespace(src=db_path)]

    provider._start_inotify()
    try:
        if provider._inotify_fd < 0:
            pytest.skip("本环境 inotify 不可用（容器限制），跳过")
        assert len(provider._pending_wal_checks) == 1  # -wal 缺失 → 目录监视

        # 模拟 SQLite 首写创建 -wal → 目录事件 → 线程转挂
        (tmp_path / "Msg_0.db-wal").write_bytes(b"w" * 64)
        deadline = time.time() + 3.0
        while provider._pending_wal_checks and time.time() < deadline:
            time.sleep(0.05)
        assert provider._pending_wal_checks == []
    finally:
        provider._stop_inotify()
