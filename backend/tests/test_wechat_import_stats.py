import sys
from pathlib import Path

import pytest


backend_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(backend_dir))


from app.db.connection import DatabaseConnection
from app.services.wechat.ingest_service import WeChatIngestService


@pytest.fixture
def isolated_db(tmp_path):
    DatabaseConnection.close()
    DatabaseConnection._db_path = None

    db_path = tmp_path / "chrono_trace_test.db"
    conn = DatabaseConnection.initialize(str(db_path))
    yield conn

    DatabaseConnection.close()
    DatabaseConnection._db_path = None


def test_collect_import_totals_excludes_deleted_rows(isolated_db):
    isolated_db.execute(
        """
        INSERT INTO contacts (account_wxid, username, nickname, is_friend, is_deleted, created_at, updated_at)
        VALUES (?, ?, ?, 1, 0, 1, 1), (?, ?, ?, 1, 1, 1, 1)
        """,
        ("wxid_me", "wxid_visible", "可见联系人", "wxid_me", "wxid_deleted", "已删除联系人"),
    )
    visible_conv = isolated_db.execute(
        """
        INSERT INTO conversations (account_wxid, username, display_name, platform, created_at, updated_at, message_count, is_deleted)
        VALUES (?, ?, ?, 'wechat', 1, 10, 1, 0)
        """,
        ("wxid_me", "wxid_visible", "可见会话"),
    ).lastrowid
    deleted_conv = isolated_db.execute(
        """
        INSERT INTO conversations (account_wxid, username, display_name, platform, created_at, updated_at, message_count, is_deleted)
        VALUES (?, ?, ?, 'wechat', 1, 10, 1, 1)
        """,
        ("wxid_me", "wxid_deleted", "已删除会话"),
    ).lastrowid
    isolated_db.execute(
        """
        INSERT INTO messages (conversation_id, local_id, talker, sender, is_sender, message_type, content, timestamp, source, created_at)
        VALUES (?, 1, ?, ?, 0, 1, ?, 10, 'long', 10),
               (?, 2, ?, ?, 0, 1, ?, 10, 'long', 10)
        """,
        (
            visible_conv,
            "wxid_visible",
            "wxid_visible",
            "hello",
            deleted_conv,
            "wxid_deleted",
            "wxid_deleted",
            "hidden",
        ),
    )
    isolated_db.commit()

    stats = WeChatIngestService()._collect_import_totals("wxid_me")

    assert stats == {
        "contacts": 1,
        "conversations": 1,
        "messages": 1,
    }


def test_import_wechat_data_reports_current_totals_and_incremental_counts(monkeypatch, isolated_db):
    isolated_db.execute(
        """
        INSERT INTO contacts (account_wxid, username, nickname, is_friend, created_at, updated_at)
        VALUES (?, ?, ?, 1, 1, 1)
        """,
        ("wxid_me", "wxid_existing", "老联系人"),
    )
    conversation_id = isolated_db.execute(
        """
        INSERT INTO conversations (account_wxid, username, display_name, platform, created_at, updated_at, message_count)
        VALUES (?, ?, ?, 'wechat', 1, 10, 1)
        """,
        ("wxid_me", "wxid_existing", "老联系人"),
    ).lastrowid
    isolated_db.execute(
        """
        INSERT INTO messages (conversation_id, local_id, talker, sender, is_sender, message_type, content, timestamp, source, created_at)
        VALUES (?, 1, ?, ?, 0, 1, ?, 10, 'long', 10)
        """,
        (conversation_id, "wxid_existing", "wxid_existing", "old"),
    )
    isolated_db.commit()

    service = WeChatIngestService()
    monkeypatch.setattr(service, "resolve_wechat_paths", lambda custom_paths=None: {
        "current_user": "wxid_me",
        "account_wxid": "wxid_me",
        "databases": {"contact": "fake_contact.db", "message": ["msg.db"]},
    })
    monkeypatch.setattr(service, "_create_import_record", lambda account_wxid: 1)
    monkeypatch.setattr(service, "_update_import_record", lambda *args, **kwargs: None)
    monkeypatch.setattr(service, "_import_contacts_v4", lambda *args, **kwargs: 0)
    monkeypatch.setattr(service, "_import_messages_v4", lambda *args, **kwargs: {
        "total": 0,
        "conversations": 1,
        "skipped": 99,
    })
    monkeypatch.setattr(service, "_sync_conversation_avatar_metadata", lambda account_wxid: 0)
    monkeypatch.setattr(service, "_soft_delete_excluded_contacts_and_conversations", lambda account_wxid: {
        "contacts": 0,
        "conversations": 0,
    })

    result = service.import_wechat_data("secret-key")

    assert result["ok"] is True
    assert result["stats"] == {
        "contacts": 1,
        "messages": 1,
        "conversations": 1,
        "inserted_contacts": 0,
        "inserted_messages": 0,
        "skipped": 99,
    }
