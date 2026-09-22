import sys
from pathlib import Path

import pytest


backend_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(backend_dir))


from app.db.connection import DatabaseConnection
from app.services.realtime.contact_profiler import ContactProfiler
from app.services.realtime.self_profiler import SelfProfiler


@pytest.fixture
def isolated_db(tmp_path):
    DatabaseConnection.close()
    DatabaseConnection._db_path = None

    db_path = tmp_path / "chrono_trace_test.db"
    conn = DatabaseConnection.initialize(str(db_path))
    yield conn

    DatabaseConnection.close()
    DatabaseConnection._db_path = None


@pytest.mark.parametrize("profiler_cls", [ContactProfiler, SelfProfiler])
def test_profiler_skips_excluded_contact_reverse_lookup(isolated_db, profiler_cls):
    isolated_db.execute(
        """
        INSERT INTO contacts (account_wxid, username, nickname, remark, is_friend, created_at, updated_at)
        VALUES (?, ?, ?, ?, 0, 1, 1)
        """,
        ("wxid_me", "exmail_tool", "腾讯企业邮箱", ""),
    )
    isolated_db.execute(
        """
        INSERT INTO conversations
        (account_wxid, username, display_name, remark, nickname, platform, created_at, updated_at, message_count, is_deleted)
        VALUES (?, ?, ?, ?, ?, 'wechat', 1, 1, 2, 0)
        """,
        ("wxid_me", "exmail_tool", "exmail_tool", "", ""),
    )
    isolated_db.commit()

    profiler = profiler_cls()

    result = profiler._find_conversation(isolated_db, "腾讯企业邮箱", "wxid_me")

    assert result is None


@pytest.mark.parametrize("profiler_cls", [ContactProfiler, SelfProfiler])
def test_sampler_falls_back_to_recent_history_when_window_empty(isolated_db, profiler_cls):
    """时间窗内没有任何消息时，必须回退取最近的历史消息供画像分析。"""
    import time as time_mod

    now = int(time_mod.time())
    isolated_db.execute(
        """
        INSERT INTO conversations
        (account_wxid, username, display_name, remark, nickname, platform, created_at, updated_at, message_count, is_deleted)
        VALUES (?, ?, ?, ?, ?, 'wechat', 1, 1, 5, 0)
        """,
        ("wxid_me", "wxid_friend", "老朋友", "", ""),
    )
    conv_id = isolated_db.execute("SELECT id FROM conversations").fetchone()[0]

    def _add_msg(content, ts, is_sender):
        isolated_db.execute(
            """
            INSERT INTO messages
            (conversation_id, talker, is_sender, message_type, content, timestamp, created_at)
            VALUES (?, ?, ?, 1, ?, ?, ?)
            """,
            (conv_id, "wxid_friend", is_sender, content, ts, now),
        )

    # 只在 200 天前有聊天记录（超出 7 天窗口）
    for i in range(3):
        _add_msg(f"旧消息{i}", now - 200 * 86400 + i, i % 2)
    isolated_db.commit()

    profiler = profiler_cls()
    sample = profiler._sample_conversation_turns(isolated_db, conv_id, 7 * 86400)

    assert [m["content"] for m in sample] == ["旧消息0", "旧消息1", "旧消息2"]

    # 窗口内出现新消息后，只采样窗口内消息，不再回退
    _add_msg("新消息", now - 100, 0)
    isolated_db.commit()
    sample = profiler._sample_conversation_turns(isolated_db, conv_id, 7 * 86400)
    assert [m["content"] for m in sample] == ["新消息"]
