"""停止竞态下缓冲迁移不整批误标已处理（审查确认缺陷）。

缺陷链路：stop_monitoring 在轮询线程 5s 内未结束时继续收尾——
_migrate_buffer_to_messages 读取 buffer 快照迁移后按 batch_id 整批
UPDATE is_processed=1，读取快照之后轮询线程竞态写入的新行一并被标，
从此无人迁移（静默丢消息）。

修复口径：mark_as_processed 支持按行 id 精确标记，迁移路径只标实际
读取到的行；stop 侧线程未死时跳过迁移（消息留缓冲不丢）。
"""

import sys
import time
from pathlib import Path

import pytest

backend_root = Path(__file__).parent.parent
sys.path.insert(0, str(backend_root))

from app.db.connection import DatabaseConnection, get_db
from app.services.realtime.backfill_store import BackfillStoreMixin
from app.services.realtime.message_buffer import MessageBuffer


@pytest.fixture
def test_db(tmp_path):
    DatabaseConnection.close()
    DatabaseConnection._db_path = None
    conn = DatabaseConnection.initialize(str(tmp_path / "chrono_stop_race.db"))
    yield conn
    DatabaseConnection.close()
    DatabaseConnection._db_path = None


class _Host(BackfillStoreMixin):
    """迁移逻辑的最小宿主：绕过完整 monitor service 的重依赖。"""

    def __init__(self):
        self.message_buffer = MessageBuffer()
        self.current_account_wxid = "acct"

    def _get_talker_key(self, talker_username, talker_display_name):
        return talker_username

    def _get_or_create_conversation_id(self, talker_username, talker_display_name):
        row = get_db().execute(
            "SELECT id FROM conversations WHERE username = ? AND platform = 'wechat'",
            (talker_username,),
        ).fetchone()
        if row:
            return row[0]
        now = int(time.time())
        cur = get_db().execute(
            "INSERT INTO conversations (account_wxid, username, display_name,"
            " platform, created_at, updated_at) VALUES (?, ?, ?, 'wechat', ?, ?)",
            ("acct", talker_username, talker_display_name, now, now),
        )
        get_db().commit()
        return cur.lastrowid


def _buffer_msg(n, ts):
    return {
        "message_hash": f"hash_{n}",
        "runtime_id": f"rt_{n}",
        "sender_attr": "friend",
        "content": f"消息{n}",
        "message_type": "text",
        "timestamp": ts,
        "visible_index": n,
    }


def _unprocessed_ids(batch_id):
    return {
        row[0]
        for row in get_db().execute(
            "SELECT id FROM realtime_message_buffer"
            " WHERE batch_id = ? AND is_processed = 0",
            (batch_id,),
        )
    }


def test_mark_as_processed_with_row_ids_is_precise(test_db):
    """row_ids 给定时只标指定行：整批 UPDATE 误标竞态新行的问题根除。"""
    buffer = MessageBuffer()
    buffer.save_message("b1", "acct", "wxid_a", "对方", _buffer_msg(1, 1_700_000_100))
    buffer.save_message("b1", "acct", "wxid_a", "对方", _buffer_msg(2, 1_700_000_200))
    first_two = _unprocessed_ids("b1")
    assert len(first_two) == 2

    # 竞态模拟：迁移只读到前两行，第三行在读取后写入
    marked = buffer.mark_as_processed("b1", "acct", row_ids=sorted(first_two))
    assert marked == 2
    buffer.save_message("b1", "acct", "wxid_a", "对方", _buffer_msg(3, 1_700_000_300))

    remaining = _unprocessed_ids("b1")
    assert len(remaining) == 1  # 竞态新行未被误标


def test_mark_as_processed_empty_row_ids_noop(test_db):
    """空 row_ids：无操作（不得退化成整批标记）。"""
    buffer = MessageBuffer()
    buffer.save_message("b1", "acct", "wxid_a", "对方", _buffer_msg(1, 1_700_000_100))
    assert buffer.mark_as_processed("b1", "acct", row_ids=[]) == 0
    assert len(_unprocessed_ids("b1")) == 1


def test_migration_leaves_post_snapshot_rows_unprocessed(test_db):
    """迁移读取快照后写入的行保持未处理，待后续补全。"""
    host = _Host()
    host.message_buffer.save_message("b9", "acct", "wxid_a", "对方", _buffer_msg(1, 1_700_000_100))
    host.message_buffer.save_message("b9", "acct", "wxid_a", "对方", _buffer_msg(2, 1_700_000_200))

    migrated = host._migrate_buffer_to_messages("b9", "wxid_a", "对方")
    assert migrated == 2
    assert _unprocessed_ids("b9") == set()

    # 竞态行在迁移完成后到达（线程未死时的最后写入）
    host.message_buffer.save_message("b9", "acct", "wxid_a", "对方", _buffer_msg(3, 1_700_000_300))
    assert len(_unprocessed_ids("b9")) == 1

    # 再次迁移可补全该行（未标已处理 = 仍可被消费）
    assert host._migrate_buffer_to_messages("b9", "wxid_a", "对方") == 1
    assert _unprocessed_ids("b9") == set()


def test_poll_abort_finalize_migrates_buffer(test_db):
    """轮询 10 连败失效收尾：缓冲消息迁移进历史表、状态清理、可重入 stop 拒绝。"""
    from app.services.realtime.monitor_service import RealtimeMonitorService

    # 进程级单例——丢弃其他测试残留其上的 Fake 状态（如 FakeMessageBuffer）
    RealtimeMonitorService._instance = None
    service = RealtimeMonitorService()
    service.current_batch_id = "b_abort"
    service.current_talker = "wxid_b"
    service.current_display_name = "对方B"
    service.current_account_wxid = "acct"
    service.message_buffer = MessageBuffer()  # 确保真实缓冲（tmp 库连接）
    service.message_buffer.save_message(
        "b_abort", "acct", "wxid_b", "对方B", _buffer_msg(1, 1_700_000_100)
    )
    service.message_buffer.save_message(
        "b_abort", "acct", "wxid_b", "对方B", _buffer_msg(2, 1_700_000_200)
    )

    service._finalize_session_in_thread({})

    # 缓冲消息已迁移入历史表（不再是孤儿行）
    row = get_db().execute(
        "SELECT COUNT(*) FROM messages WHERE talker = 'wxid_b' AND source = 'realtime'"
    ).fetchone()
    assert row[0] == 2
    assert _unprocessed_ids("b_abort") == set()
    # 会话状态已清理：后续 stop_monitoring 走「没有监听任务」而非二次收尾
    assert service.current_batch_id is None
    assert service.current_talker is None
    assert service.current_display_name is None
