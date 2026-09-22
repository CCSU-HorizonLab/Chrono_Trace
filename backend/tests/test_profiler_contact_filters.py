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
def test_sampler_extends_backward_when_span_thin_or_empty(isolated_db, profiler_cls):
    """跨度内没有或缺少消息时，向后顺延取更早历史，不做时间硬截断。"""
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

    # 只在 200 天前有聊天记录（超出 7 天跨度）：顺延后应取到
    for i in range(3):
        _add_msg(f"旧消息{i}", now - 200 * 86400 + i, i % 2)
    isolated_db.commit()

    profiler = profiler_cls()
    sample = profiler._sample_conversation_turns(isolated_db, conv_id, 7 * 86400, 16000)

    assert [m["content"] for m in sample] == ["旧消息0", "旧消息1", "旧消息2"]

    # 跨度内出现新消息但内容仍不足目标量：新旧消息合并采样
    _add_msg("新消息", now - 100, 0)
    isolated_db.commit()
    sample = profiler._sample_conversation_turns(isolated_db, conv_id, 7 * 86400, 16000)
    assert [m["content"] for m in sample] == ["旧消息0", "旧消息1", "旧消息2", "新消息"]


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
    sample = profiler._sample_conversation_turns(isolated_db, conv_id, PROFILE_TIME_WINDOWS['high'], 1)
    assert [m["content"] for m in sample] == _expected(90)

    # 普通(30天)：只保留 30 天内的 4 条
    sample = profiler._sample_conversation_turns(isolated_db, conv_id, PROFILE_TIME_WINDOWS['medium'], 1)
    assert [m["content"] for m in sample] == _expected(30)

    # 简略(7天)：只保留 7 天内的 2 条
    sample = profiler._sample_conversation_turns(isolated_db, conv_id, PROFILE_TIME_WINDOWS['low'], 1)
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

    sample = profiler_cls()._sample_conversation_turns(isolated_db, conv_id, 7 * 86400, 10 ** 9)

    # 10 条 × 100 字符 = 1000 字符 > 350：从最旧的开始丢弃，保留最新 3 条
    assert [m["content"] for m in sample] == ["x" * 99 + str(i) for i in (7, 8, 9)]


@pytest.mark.parametrize("profiler_cls", [ContactProfiler, SelfProfiler])
def test_sampler_extends_backward_to_fill_target(isolated_db, profiler_cls):
    """跨度内内容不足目标量时向后顺延补采，足够时不额外顺延。"""
    import time as time_mod

    now = int(time_mod.time())
    isolated_db.execute(
        """
        INSERT INTO conversations
        (account_wxid, username, display_name, remark, nickname, platform, created_at, updated_at, message_count, is_deleted)
        VALUES (?, ?, ?, ?, ?, 'wechat', 1, 1, 7, 0)
        """,
        ("wxid_me", "wxid_thin", "稀疏好友", "", ""),
    )
    conv_id = isolated_db.execute("SELECT id FROM conversations").fetchone()[0]

    def _add_msg(content, ts, is_sender):
        isolated_db.execute(
            """
            INSERT INTO messages
            (conversation_id, talker, is_sender, message_type, content, timestamp, created_at)
            VALUES (?, ?, ?, 1, ?, ?, ?)
            """,
            (conv_id, "wxid_thin", is_sender, content, ts, now),
        )

    # 跨度内只有 2 条（各 100 字符）；100 天前还有 5 条（各 100 字符）
    for i in range(2):
        _add_msg("近" * 99 + str(i), now - (10 - i) * 60, i % 2)
    for i in range(5):
        _add_msg("远" * 99 + str(i), now - 100 * 86400 + i, i % 2)
    isolated_db.commit()

    profiler = profiler_cls()

    # 目标 400 字符：跨度内 200 字符不足 → 顺延拉回 100 天前的 5 条（500 字符）
    sample = profiler._sample_conversation_turns(isolated_db, conv_id, 7 * 86400, 400)
    assert len(sample) == 7
    assert sample[0]["content"].startswith("远")
    assert sample[-1]["content"].startswith("近")

    # 目标 200 字符：跨度内已满足 → 不顺延，只采跨度内消息
    sample = profiler._sample_conversation_turns(isolated_db, conv_id, 7 * 86400, 200)
    assert [m["content"] for m in sample] == ["近" * 99 + "0", "近" * 99 + "1"]

    # 完全没有消息：返回空列表
    isolated_db.execute(
        """
        INSERT INTO conversations
        (account_wxid, username, display_name, remark, nickname, platform, created_at, updated_at, message_count, is_deleted)
        VALUES (?, ?, ?, ?, ?, 'wechat', 1, 1, 0, 0)
        """,
        ("wxid_me", "wxid_nochat", "无聊天", "", ""),
    )
    empty_conv_id = isolated_db.execute(
        "SELECT id FROM conversations WHERE username = 'wxid_nochat'"
    ).fetchone()[0]
    isolated_db.commit()
    assert profiler._sample_conversation_turns(isolated_db, empty_conv_id, 7 * 86400, 400) == []
