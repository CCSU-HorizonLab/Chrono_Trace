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
