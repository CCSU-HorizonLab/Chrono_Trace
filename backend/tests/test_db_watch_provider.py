"""db_watch 实时监听 provider 单测（离线：合成加密分片，无真实微信）。

覆盖：初始化密钥校验、跨分片定位 Msg 表、窗口语义（WINDOW/PAGE 翻页）、
sender 归属（目录名后缀剥离）、local_type 词表映射、源库增量刷新可见。
"""
from __future__ import annotations

import hashlib
import os
import sys
from pathlib import Path

backend_root = Path(__file__).parent.parent
sys.path.insert(0, str(backend_root))
sys.path.insert(0, str(Path(__file__).parent))

import pytest

from app.services.realtime.providers import db_watch as dbw
from app.services.realtime.providers.db_watch import DbWatchRealtimeProvider
from fixtures.wcdb_factory import build_plain_db, encrypt_db

KEY_HEX = "2b" * 32
MY_DIR_ACCOUNT = "lishao378_86f8"   # 目录名带后缀
MY_PLAIN_NAME = "lishao378"         # name2id 存无后缀真名

ZHANG = "wxid_zhang"
LI = "wxid_li"


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
