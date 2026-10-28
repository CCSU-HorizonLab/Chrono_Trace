"""批次三确定性断裂修复测试（W5）。

三处：
1. inotify 事件 len 字段偏移（buf[12:16]，此前误读 buf[16:20]）
2. db_watch _resolve_username 必须按当前账号过滤（同名联系人跨账号）
3. run_backfill 不再调用已删除的 UI 自动化方法（此前入口必 AttributeError）
"""
from __future__ import annotations

import struct
import sys
import time
from pathlib import Path

import pytest

backend_root = Path(__file__).parent.parent
sys.path.insert(0, str(backend_root))

from app.db.connection import DatabaseConnection, get_db
from app.services.realtime.providers.db_watch import (
    DbWatchRealtimeProvider,
    _drain_inotify_events,
)


def _event(name: bytes = b"", wd: int = 1, mask: int = 2) -> bytes:
    """构造一个 struct inotify_event（小端，name 按 8 字节对齐）。"""
    padded = name + b"\x00" * ((-len(name)) % 8)
    return struct.pack("<iIII", wd, mask, 0, len(padded)) + padded


class TestInotifyEventDrain:

    def test_named_events_fully_consumed(self):
        """带 name 的事件按真实 len 消化——锁死偏移 12 的修复。

        旧代码读 buf[16:20]（name 前 4 字节当长度）：name='msg.db-wal'
        时算出 event_len 为随机值，buf 永不消化、事件流错位。
        """
        stream = _event(b"msg.db-wal") + _event(b"a") + _event(b"")
        assert _drain_inotify_events(stream) == b""

    def test_incomplete_tail_kept(self):
        """不完整的尾事件保留待下轮拼接。"""
        full = _event(b"msg.db-wal")
        head = full[:24]  # 头 + 半截 name
        assert _drain_inotify_events(head) == head

    def test_multiple_reads_concatenate(self):
        """跨 read 分片到达的事件流同样正确消化。"""
        buf = _event(b"x")
        rest = _drain_inotify_events(buf + _event(b"longer-name")[:10])
        assert rest == _event(b"longer-name")[:10]


class TestResolveUsernameAccountFilter:

    @pytest.fixture
    def test_db(self, tmp_path):
        DatabaseConnection.close()
        DatabaseConnection._db_path = None
        conn = DatabaseConnection.initialize(str(tmp_path / "chrono_resolve.db"))
        now = int(time.time())
        # 双账号同名联系人：账号 A 备注命中，账号 B 昵称命中
        for acct, username, remark, nickname in [
            ("acct_a", "wxid_correct", "阿澄", ""),
            ("acct_b", "wxid_wrong", "", "阿澄"),
        ]:
            conn.execute(
                "INSERT INTO contacts (account_wxid, username, remark, nickname,"
                " created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                (acct, username, remark, nickname, now, now),
            )
        conn.commit()
        yield conn
        DatabaseConnection.close()
        DatabaseConnection._db_path = None

    def test_filters_by_current_account(self, test_db):
        """当前账号 A：解析到本账号的 wxid_correct，不会错绑账号 B 的人。"""
        provider = DbWatchRealtimeProvider()
        provider.account_name = "acct_a"
        assert provider._resolve_username("阿澄") == "wxid_correct"

        provider.account_name = "acct_b"
        assert provider._resolve_username("阿澄") == "wxid_wrong"

    def test_falls_back_to_display_name_when_no_row(self, test_db):
        """无命中：按原样返回名字（现网兜底语义不变）。"""
        provider = DbWatchRealtimeProvider()
        provider.account_name = "acct_none"
        assert provider._resolve_username("不存在的人") == "不存在的人"


class TestRunBackfillNoDeletedMethodCall:

    def test_uses_existing_create_wechat_instance(self, tmp_path, monkeypatch):
        """run_backfill 不再调已删的 _create_wechat_instance_with_recovery。

        旧行为：入口第一步 AttributeError（方法在 UI 自动化下线时被删）。
        新行为：wx 未初始化时走 _create_wechat_instance，初始化失败返回
        结构化错误而非异常。
        """
        from app.services.realtime.monitor_service import RealtimeMonitorService

        RealtimeMonitorService._instance = None
        service = RealtimeMonitorService()
        service.is_monitoring = False
        calls = {"create": 0}

        monkeypatch.setattr(
            service, "get_resume_probe",
            lambda **k: {"has_checkpoint": True, "should_offer_resume": True},
        )

        def _fake_create():
            calls["create"] += 1
            service.wx = object()  # 假装后端就绪

        monkeypatch.setattr(service, "_create_wechat_instance", _fake_create)
        monkeypatch.setattr(
            service, "_build_chatwith_candidates", lambda: ["阿澄"]
        )
        monkeypatch.setattr(
            service, "_try_chat_with",
            lambda name: False,  # 切换失败 → 提前 return（不触深层链路）
        )
        service._chat_error = "定位失败(测试)"

        service.wx = None
        result = service.run_backfill("阿澄", talker_username="wxid_a")

        assert calls["create"] == 1, "必须经 _create_wechat_instance 初始化后端"
        assert result["success"] is False
        assert "切换聊天失败" in result["message"]

    def test_init_failure_returns_structured_error(self, tmp_path, monkeypatch):
        """后端初始化失败：返回结构化错误 dict，不抛 AttributeError。"""
        from app.services.realtime.monitor_service import RealtimeMonitorService

        RealtimeMonitorService._instance = None
        service = RealtimeMonitorService()
        service.is_monitoring = False
        service.wx = None

        monkeypatch.setattr(
            service, "get_resume_probe",
            lambda **k: {"has_checkpoint": True, "should_offer_resume": True},
        )

        def _boom():
            raise RuntimeError("后端不可用")

        monkeypatch.setattr(service, "_create_wechat_instance", _boom)

        result = service.run_backfill("阿澄", talker_username="wxid_a")
        assert result["success"] is False
        assert "监听后端初始化失败" in result["message"]
