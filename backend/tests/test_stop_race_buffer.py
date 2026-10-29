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

    # 收尾必须读冻结的 session_state（W5）：收尾期间新会话可能已接管字段
    session_state = {
        "session_token": 1,
        "batch_id": "b_abort",
        "account_wxid": "acct",
        "talker_username": "wxid_b",
        "display_name": "对方B",
    }
    service._finalize_session_in_thread(session_state)

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


def test_poll_abort_finalize_uses_frozen_state_not_live_fields(test_db):
    """收尾读冻结 session_state：self.current_* 已被新会话改写时不得错拿（W5）。

    此前读实时 self.current_*——旧会话失效收尾撞上新会话已启动的窗口时，
    会把新会话的批次迁移/清掉。
    """
    from app.services.realtime.monitor_service import RealtimeMonitorService

    RealtimeMonitorService._instance = None
    service = RealtimeMonitorService()
    service.current_account_wxid = "acct"
    service.message_buffer = MessageBuffer()
    service.message_buffer.save_message(
        "b_old", "acct", "wxid_old", "旧对象", _buffer_msg(1, 1_700_000_100)
    )

    # 新会话已接管单例字段（R2 场景：回溯/旧轮询线程仍在收尾）
    service.current_batch_id = "b_new"
    service.current_talker = "wxid_new"
    service.current_display_name = "新对象"

    service._finalize_session_in_thread({
        "session_token": 1,
        "batch_id": "b_old",
        "account_wxid": "acct",
        "talker_username": "wxid_old",
        "display_name": "旧对象",
    })

    # 旧批次被迁移（冻结值），新会话字段不被清理
    row = get_db().execute(
        "SELECT COUNT(*) FROM messages WHERE talker = 'wxid_old' AND source = 'realtime'"
    ).fetchone()
    assert row[0] == 1
    assert service.current_batch_id == "b_new", "新会话字段不得被旧收尾清掉"
    assert service.current_talker == "wxid_new"
    assert service.current_display_name == "新对象"


def test_fallback_decrypt_writes_into_private_dir(tmp_path, monkeypatch):
    """回退全量解密的明文库必须落在 0700 私有目录（不再 /tmp 0644 共享）。"""
    import os
    import stat
    import tempfile as _tf
    import sys as _sys
    _sys.path.insert(0, str(Path(__file__).parent))

    created_dirs = []
    real_mkdtemp = _tf.mkdtemp

    def _spy_mkdtemp(*a, **k):
        d = real_mkdtemp(*a, **k)
        created_dirs.append(d)
        return d

    monkeypatch.setattr("tempfile.mkdtemp", _spy_mkdtemp)

    import app.services.wechat.db.v4.contact as contact_mod

    # 快照分支短路排除：强制走「共享快照不可用 → 回退全量解密」路径
    import app.services.wechat.snapshot_manager as snap_mod
    monkeypatch.setattr(
        snap_mod, "get_snapshot_manager",
        lambda: (_ for _ in ()).throw(RuntimeError("测试禁用快照")),
    )

    class _FakeDecryptor:
        def set_raw_key_map(self, *_a):
            pass

        def verify_key_from_file(self, *_a):
            return True

        def decrypt_database(self, src, dst, key):
            Path(dst).write_bytes(b"decrypted")

    import app.services.wechat.db_decryptor_v2 as dec_mod
    monkeypatch.setattr(dec_mod, "WeChatDBDecryptorV2", _FakeDecryptor)
    # contact 模块函数内 import ... from ...db_decryptor_v2 → 打到源模块属性

    db = contact_mod.ContactDBV4(str(tmp_path / "contact.db"), db_key="ab" * 32)
    try:
        assert created_dirs, "必须经 mkdtemp 建私有目录"
        mode = stat.S_IMODE(os.stat(created_dirs[0]).st_mode)
        assert mode == 0o700
        assert str(db.temp_db_path).startswith(created_dirs[0])
        assert not str(db.temp_db_path).startswith(_tf.gettempdir() + "/tmp")
    finally:
        db.close()
    assert not os.path.exists(created_dirs[0]), "close 后私有目录应清理"


def test_stop_join_window_does_not_clobber_newly_started_session(test_db):
    """stop 的 join 等待窗口内新会话已启动：收尾必须只用冻结快照（W5）。

    旧实现置 is_monitoring=False 后读实时 self.current_* 收尾：迁移/清掉
    的是新会话批次，且 _reset_wechat_instance 置 wx=None 令新轮询线程立即
    退出而 is_monitoring 永久卡 True，之后所有 start 被拒直到重启。
    """
    import threading

    from app.services.realtime.monitor_service import RealtimeMonitorService

    RealtimeMonitorService._instance = None
    service = RealtimeMonitorService()
    service.current_batch_id = "b_old"
    service.current_talker = "wxid_old"
    service.current_display_name = "旧对象"
    service.current_account_wxid = "acct"
    service.is_monitoring = True
    service.message_buffer = MessageBuffer()
    service.message_buffer.save_message(
        "b_old", "acct", "wxid_old", "旧对象", _buffer_msg(1, 1_700_000_100)
    )

    calls = {"migrate": [], "checkpoint": [], "reset": 0}
    service._migrate_buffer_to_messages = lambda *a, **k: (calls["migrate"].append((a, k)), 0)[1]
    service._save_monitor_checkpoint = lambda *a, **k: calls["checkpoint"].append((a, k))
    service._reset_wechat_instance = lambda: calls.__setitem__("reset", calls["reset"] + 1)
    service._log_runtime_event = lambda *a, **k: None
    service.emotion_tracker = None

    stop_signal = threading.Event()

    def _poll_then_takeover():
        # stop 先冻结快照再 set stop_event——事件序保证接管发生在快照之后；
        # 再等 is_monitoring 被 stop 置 False 后才接管，令终态确定
        stop_signal.wait(timeout=5)
        deadline = time.time() + 5
        while service.is_monitoring and time.time() < deadline:
            time.sleep(0.002)
        service.current_batch_id = "b_new"
        service.current_talker = "wxid_new"
        service.current_display_name = "新对象"
        service._stop_event = threading.Event()  # 新会话自己的 stop_event
        service.is_monitoring = True

    service._stop_event = stop_signal
    service.polling_thread = threading.Thread(target=_poll_then_takeover)
    service.polling_thread.start()

    result = service.stop_monitoring()

    assert result["success"] is True
    assert result["batch_id"] == "b_old", "返回的必须是冻结批次"
    # 迁移/checkpoint 只处理冻结批次与冻结账号
    assert calls["migrate"][0][0][0] == "b_old"
    assert calls["migrate"][0][1]["account_wxid"] == "acct"
    assert calls["checkpoint"][0][0][0] == "b_old"
    assert calls["checkpoint"][0][1]["account_wxid"] == "acct"
    # 新会话状态完好：字段未被清、标志未被复原、wx 实例未被重置
    assert service.current_batch_id == "b_new"
    assert service.current_talker == "wxid_new"
    assert service.current_display_name == "新对象"
    assert service.is_monitoring is True
    assert calls["reset"] == 0, "新会话接管后不得 _reset_wechat_instance"


def test_finalize_passes_frozen_account_to_migration(test_db):
    """切号后旧会话失效收尾：迁移/checkpoint 必须用冻结账号查批次（W5）。

    实时 self.current_account_wxid 已是新账号——按实时账号查旧账号批次得
    0 行，旧账号的实时消息将永久滞留缓冲表无人消费。
    """
    from app.services.realtime.monitor_service import RealtimeMonitorService

    RealtimeMonitorService._instance = None
    service = RealtimeMonitorService()
    service.current_account_wxid = "acct_new"  # 收尾期间用户已切号开新监听
    service.message_buffer = MessageBuffer()
    service.message_buffer.save_message(
        "b_old", "acct_old", "wxid_old", "旧对象", _buffer_msg(1, 1_700_000_100)
    )

    service._finalize_session_in_thread({
        "session_token": 1,
        "batch_id": "b_old",
        "account_wxid": "acct_old",
        "talker_username": "wxid_old",
        "display_name": "旧对象",
    })

    row = get_db().execute(
        "SELECT COUNT(*) FROM messages WHERE talker = 'wxid_old' AND source = 'realtime'"
    ).fetchone()
    assert row[0] == 1, "冻结账号的批次必须被迁移（实时账号口径会查空批次）"


def test_visible_index_zero_preserved_through_prepare(test_db):
    """W10：visible_index 是 0 起始枚举，合法值 0 不得被 `or` 兜底压成 -1。

    同秒组里 index=0 是最旧一条：压成 -1 后被所有消费方排到最后，
    组内顺序漂移。
    """
    from types import SimpleNamespace

    from app.services.realtime.monitor_service import RealtimeMonitorService

    RealtimeMonitorService._instance = None
    service = RealtimeMonitorService()

    msg_zero = SimpleNamespace(
        is_self=True, is_system=False, content="你好", type="text",
        id="rt_1", visible_index=0, timestamp=1_700_000_100, time=None,
    )
    assert service._prepare_visible_messages([msg_zero])[0]["visible_index"] == 0

    msg_missing = SimpleNamespace(
        is_self=False, is_system=False, content="早", type="text",
        id="rt_2", visible_index=None, timestamp=1_700_000_200, time=None,
    )
    assert service._prepare_visible_messages([msg_missing])[0]["visible_index"] == -1


def test_buffer_persists_visible_index_zero(test_db):
    """W10：暂存表落库——0 存 0（不被 `or -1` 吞），缺失存 -1。"""
    buffer = MessageBuffer()
    assert buffer.save_message("b_vi", "acct", "wxid_a", "对方", _buffer_msg(0, 1_700_000_100)) > 0
    no_index = {k: v for k, v in _buffer_msg(1, 1_700_000_200).items() if k != "visible_index"}
    assert buffer.save_message("b_vi", "acct", "wxid_a", "对方", no_index) > 0

    by_runtime = {
        m["runtime_id"]: m["visible_index"]
        for m in buffer.get_batch_messages("b_vi", account_wxid="acct")
    }
    assert by_runtime["rt_0"] == 0
    assert by_runtime["rt_1"] == -1
