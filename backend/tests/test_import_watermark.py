"""导入时间水位测试——增量读取窗口、水位推进、批量写入等价性。

FakeMsgDB mock 掉 MessageDBV4（免解密），断言 get_messages 收到的
time_range 起点即水位-24h；批量写入路径与旧逐条语义等价（messages
表内容 / inserted / skipped / touched）。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

backend_root = Path(__file__).parent.parent
sys.path.insert(0, str(backend_root))

from app.db.connection import DatabaseConnection, get_db
from app.services.wechat import ingest_service
from app.services.wechat.ingest_service import WeChatIngestService


@pytest.fixture
def test_db(tmp_path):
    DatabaseConnection.close()
    DatabaseConnection._db_path = None
    conn = DatabaseConnection.initialize(str(tmp_path / "chrono_watermark.db"))
    yield conn
    DatabaseConnection.close()
    DatabaseConnection._db_path = None


def _msg(talker, local_id, content, ts, is_sender=0, message_type=1):
    return {
        "talker": talker, "local_id": local_id, "sender": talker,
        "is_sender": is_sender, "message_type": message_type,
        "content": content, "timestamp": ts,
    }


class FakeMsgDB:
    """记录 get_messages 调用参数的假消息库（类级记录，跨实例可查）。"""

    calls: list[tuple[str, tuple | None]] = []
    data: dict[str, list[dict]] = {}

    def __init__(self, paths, key, my_wxid=None, raw_keys=None):
        pass

    def get_all_conversation_usernames(self):
        return list(FakeMsgDB.data.keys())

    def get_messages(self, username, time_range=None, limit=None):
        FakeMsgDB.calls.append((username, time_range))
        rows = FakeMsgDB.data.get(username, [])
        if time_range:
            start, end = time_range
            rows = [m for m in rows if start <= m["timestamp"] <= end]
        return list(rows)

    def close(self):
        pass


@pytest.fixture
def fake_msg_db(monkeypatch):
    FakeMsgDB.calls = []
    FakeMsgDB.data = {}
    monkeypatch.setattr(ingest_service, "MessageDBV4", FakeMsgDB)
    return FakeMsgDB


class TestWatermarkReadWindow:

    def test_no_watermark_reads_full(self, test_db, fake_msg_db):
        """首导（水位 0）：time_range=None 全量读取。"""
        fake_msg_db.data = {"wxid_a": [_msg("wxid_a", 1, "旧", 1_000), _msg("wxid_a", 2, "新", 2_000)]}
        service = WeChatIngestService()
        stats = service._import_messages_v4(
            [], "key", "me", "acct", 0, raw_keys=None, watermark_ts=0)
        assert stats["total"] == 2
        assert fake_msg_db.calls[0][1] is None, "无水位应全量读取"

    def test_watermark_reads_window(self, test_db, fake_msg_db):
        """有水位：读取窗口起点 = 水位-24h，窗内消息导入，窗外跳过。"""
        WM = 2_000_000
        fake_msg_db.data = {
            "wxid_a": [
                _msg("wxid_a", 1, "远古", WM - 200_000),   # 窗外 → 不读
                _msg("wxid_a", 2, "安全窗内旧消息", WM - 100),  # 窗内重扫 → OR IGNORE 语义（首导仍插入）
                _msg("wxid_a", 3, "新消息", WM + 500),
            ]
        }
        service = WeChatIngestService()
        stats = service._import_messages_v4(
            [], "key", "me", "acct", 0, raw_keys=None, watermark_ts=WM)

        username, time_range = fake_msg_db.calls[0]
        assert time_range is not None
        assert time_range[0] == WM - 86400, "窗口起点应为水位-24h"
        assert stats["total"] == 2, "窗外消息不应被读取/插入"
        assert stats["watermark_ts"] == WM + 500, "水位应推进到本次最大"

    def test_zero_new_messages_keep_watermark(self, test_db, fake_msg_db):
        """窗口内零消息：水位维持原值不回退。"""
        WM = 5_000_000
        fake_msg_db.data = {"wxid_a": [_msg("wxid_a", 1, "远古", 100)]}
        service = WeChatIngestService()
        stats = service._import_messages_v4(
            [], "key", "me", "acct", 0, raw_keys=None, watermark_ts=WM)
        assert stats["total"] == 0
        assert stats["watermark_ts"] == WM

    def test_incremental_second_import_dedupes(self, test_db, fake_msg_db):
        """二次导入：窗口重扫的旧消息被判重集合跳过，只有新消息插入。"""
        fake_msg_db.data = {"wxid_a": [_msg("wxid_a", 1, "消息一", 1_000)]}
        service = WeChatIngestService()
        first = service._import_messages_v4([], "key", "me", "acct", 0, watermark_ts=0)
        assert first["total"] == 1

        # 新消息到达（时间在安全窗内）
        fake_msg_db.data["wxid_a"].append(_msg("wxid_a", 2, "消息二", 1_500))
        second = service._import_messages_v4(
            [], "key", "me", "acct", 0, watermark_ts=first["watermark_ts"])
        assert second["total"] == 1, "只应插入新消息"
        assert second["skipped"] >= 1, "窗口内旧消息应被跳过"
        total = get_db().execute("SELECT COUNT(*) FROM messages").fetchone()[0]
        assert total == 2


class TestBatchInsertEquivalence:

    def test_batch_semantics_match_legacy(self, test_db):
        """批量路径与旧逐条语义一致：inserted/skipped/touched/messages 内容。"""
        service = WeChatIngestService()
        batch = [
            _msg("wxid_a", 1, "消息一", 1_700_000_100),
            _msg("wxid_a", 1, "消息一重复", 1_700_000_100),  # 同批重复 key
            _msg("wxid_a", 2, "消息二", 1_700_000_200, is_sender=1),
            _msg("wxid_b", 1, "另一会话", 1_700_000_300),
            _msg("weixin", 9, "系统消息", 1_700_000_400),     # 排除账号
        ]
        cache, touched = {}, {}
        result = service._insert_message_batch(batch, "acct", cache, touched)
        # 5 条中：排除 1、同批重复 1 → 插入 3、跳过 2
        assert result == {"inserted": 3, "skipped": 2}

        conv_a = get_db().execute(
            "SELECT id FROM conversations WHERE username='wxid_a'").fetchone()[0]
        conv_b = get_db().execute(
            "SELECT id FROM conversations WHERE username='wxid_b'").fetchone()[0]
        assert set(touched) == {conv_a, conv_b}
        assert touched[conv_a] == 1_700_000_200
        assert touched[conv_b] == 1_700_000_300

        # 同批重复 key：首条插入，第二条被 OR IGNORE（内容是首条版本）
        contents = [r[0] for r in get_db().execute(
            "SELECT content FROM messages WHERE conversation_id=? ORDER BY id", (conv_a,))]
        assert contents == ["消息一", "消息二"]

        # 重放：全跳过（排除 1 + 已存在 4——含同批重复那条），touched 空
        result2 = service._insert_message_batch(batch, "acct", {}, {})
        assert result2 == {"inserted": 0, "skipped": 5}
        assert get_db().execute("SELECT COUNT(*) FROM messages").fetchone()[0] == 3

    def test_null_local_id_rows_always_insert(self, test_db):
        """local_id NULL（实时行语义）：不受判重集合约束，可重复插入。"""
        service = WeChatIngestService()
        batch = [_msg("wxid_a", None, "实时行", 100), _msg("wxid_a", None, "实时行", 100)]
        result = service._insert_message_batch(batch, "acct", {}, {})
        assert result["inserted"] == 2
        assert get_db().execute("SELECT COUNT(*) FROM messages").fetchone()[0] == 2


class TestWatermarkSettings:

    def test_account_settings_roundtrip(self):
        """import_watermark_ts 白名单往返 + 只增不减 + clear 重置。"""
        from app.services.wechat.account_settings import (
            update_wechat_account_import_state, get_wechat_account,
        )

        settings = {"wechat_accounts": []}
        update_wechat_account_import_state(
            settings, "wxid_x", import_watermark_ts=1000, import_completed=True)
        assert get_wechat_account(settings, "wxid_x")["import_watermark_ts"] == 1000

        # 只增不减
        update_wechat_account_import_state(settings, "wxid_x", import_watermark_ts=500)
        assert get_wechat_account(settings, "wxid_x")["import_watermark_ts"] == 1000

        # None 不变
        update_wechat_account_import_state(settings, "wxid_x", import_completed=True)
        assert get_wechat_account(settings, "wxid_x")["import_watermark_ts"] == 1000

        # clear 重置（force_full 语义）
        update_wechat_account_import_state(settings, "wxid_x", clear_import_state=True)
        assert get_wechat_account(settings, "wxid_x")["import_watermark_ts"] == 0

    def test_force_full_ignores_watermark(self, test_db, fake_msg_db, monkeypatch):
        """options.force_full → 忽略水位全量读取。"""
        # 照 test_wechat_import_stats 的全链路 mock（免路径/联系人/记录）
        monkeypatch.setattr(service_module := __import__(
            "app.services.wechat.ingest_service", fromlist=["WeChatIngestService"]
        ).WeChatIngestService, "resolve_wechat_paths",
            staticmethod(lambda *a, **k: {
                "wechat_dir": "/tmp", "current_user": "me", "account_wxid": "me",
                "databases": {"message": ["/fake/message.db"], "contact": [], "session": []},
            }))
        monkeypatch.setattr(service_module, "_import_contacts_v4",
            lambda self, *a, **k: {"contacts": 0, "inserted": 0})
        monkeypatch.setattr(service_module, "_create_import_record", lambda self, *a, **k: 1)
        monkeypatch.setattr(service_module, "_update_import_record", lambda self, *a, **k: None)
        monkeypatch.setattr(service_module, "_sync_conversation_avatar_metadata",
            lambda self, *a, **k: None)
        monkeypatch.setattr(service_module, "_soft_delete_excluded_contacts_and_conversations",
            lambda self, *a, **k: {"contacts": 0, "conversations": 0})
        monkeypatch.setattr(service_module, "_collect_import_totals",
            lambda self, *a, **k: {"contacts": 0, "messages": 1, "conversations": 1})

        fake_msg_db.data = {"wxid_a": [_msg("wxid_a", 1, "m", 9_000)]}
        service = service_module()
        stats = service.import_wechat_data("key", {
            "import_watermark_ts": 5_000, "force_full": True,
        })
        assert stats["ok"] is True
        assert fake_msg_db.calls[0][1] is None, "force_full 应全量读取"
        assert stats["stats"]["import_watermark_ts"] == 9_000
