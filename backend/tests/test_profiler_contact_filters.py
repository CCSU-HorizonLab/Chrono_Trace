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


@pytest.mark.parametrize("profiler_cls", [ContactProfiler, SelfProfiler])
def test_sampler_buckets_take_full_history_without_token_budget(isolated_db, profiler_cls):
    """分桶采样：桶内消息全量保留，档位只决定回看跨度包含到哪一层。"""
    import time as time_mod

    from app.services.realtime.self_profiler import PROFILE_TIME_WINDOWS

    now = int(time_mod.time())
    isolated_db.execute(
        """
        INSERT INTO conversations
        (account_wxid, username, display_name, remark, nickname, platform, created_at, updated_at, message_count, is_deleted)
        VALUES (?, ?, ?, ?, ?, 'wechat', 1, 1, 9, 0)
        """,
        ("wxid_me", "wxid_bucket", "分桶好友", "", ""),
    )
    conv_id = isolated_db.execute("SELECT id FROM conversations").fetchone()[0]

    ages_days = (1, 2, 10, 20, 40, 50, 80, 85, 200)  # 200 天前超出所有跨度
    for i, age in enumerate(ages_days):
        isolated_db.execute(
            """
            INSERT INTO messages
            (conversation_id, talker, is_sender, message_type, content, timestamp, created_at)
            VALUES (?, ?, ?, 1, ?, ?, ?)
            """,
            (conv_id, "wxid_bucket", i % 2, f"消息{age}天前", now - age * 86400, now),
        )
    isolated_db.commit()

    profiler = profiler_cls()

    def _expected(max_age_days):
        in_span = sorted((a for a in ages_days if a <= max_age_days), reverse=True)
        return [f"消息{a}天前" for a in in_span]

    # 精细(90天)：90 天内 8 条全保留（200 天前的超出跨度），时间正序
    sample = profiler._sample_conversation_turns(isolated_db, conv_id, PROFILE_TIME_WINDOWS['high'])
    assert [m["content"] for m in sample] == _expected(90)

    # 普通(30天)：只保留 30 天内的 4 条
    sample = profiler._sample_conversation_turns(isolated_db, conv_id, PROFILE_TIME_WINDOWS['medium'])
    assert [m["content"] for m in sample] == _expected(30)

    # 简略(7天)：只保留 7 天内的 2 条
    sample = profiler._sample_conversation_turns(isolated_db, conv_id, PROFILE_TIME_WINDOWS['low'])
    assert [m["content"] for m in sample] == _expected(7)


@pytest.mark.parametrize("profiler_cls", [ContactProfiler, SelfProfiler])
def test_sampler_trims_oldest_first_when_exceeding_char_cap(isolated_db, monkeypatch, profiler_cls):
    """只有聊天量极大时才按字符收敛，且从最旧消息开始，正常规模不触发。"""
    import time as time_mod

    from app.services.realtime import contact_profiler as contact_mod
    from app.services.realtime import self_profiler as self_mod

    now = int(time_mod.time())
    isolated_db.execute(
        """
        INSERT INTO conversations
        (account_wxid, username, display_name, remark, nickname, platform, created_at, updated_at, message_count, is_deleted)
        VALUES (?, ?, ?, ?, ?, 'wechat', 1, 1, 10, 0)
        """,
        ("wxid_me", "wxid_flood", "刷屏好友", "", ""),
    )
    conv_id = isolated_db.execute("SELECT id FROM conversations").fetchone()[0]

    for i in range(10):
        isolated_db.execute(
            """
            INSERT INTO messages
            (conversation_id, talker, is_sender, message_type, content, timestamp, created_at)
            VALUES (?, ?, ?, 1, ?, ?, ?)
            """,
            (conv_id, "wxid_flood", i % 2, "x" * 99 + str(i), now - (10 - i) * 60, now),
        )
    isolated_db.commit()

    module = self_mod if profiler_cls is SelfProfiler else contact_mod
    monkeypatch.setattr(module, "MAX_SAMPLE_CHARS", 350)

    sample = profiler_cls()._sample_conversation_turns(isolated_db, conv_id, 7 * 86400)

    # 10 条 × 100 字符 = 1000 字符 > 350：从最旧的开始丢弃，保留最新 3 条
    assert [m["content"] for m in sample] == ["x" * 99 + str(i) for i in (7, 8, 9)]
