import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


backend_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(backend_dir))


from app.db.connection import DatabaseConnection
from app.services.analysis.analysis_service import AnalysisService
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


def test_import_contacts_persists_avatar_without_blank_overwrite(monkeypatch, isolated_db):
    isolated_db.execute(
        """
        INSERT INTO contacts (account_wxid, username, nickname, avatar_path, is_friend, created_at, updated_at)
        VALUES (?, ?, ?, ?, 1, 1, 1)
        """,
        ("wxid_me", "wxid_existing", "旧昵称", "https://old.example/avatar.jpg"),
    )
    isolated_db.commit()

    class FakeContactDB:
        def __init__(self, db_path: str, db_key: str):
            assert db_path == "fake_contact.db"
            assert db_key == "secret-key"

        def get_contacts(self):
            return [
                {
                    "username": "wxid_new",
                    "nickname": "新联系人",
                    "remark": "",
                    "alias": "",
                    "phone": "",
                    "is_friend": True,
                    "avatar_url": "https://cdn.example/new.jpg",
                },
                {
                    "username": "wxid_existing",
                    "nickname": "新昵称",
                    "remark": "",
                    "alias": "",
                    "phone": "",
                    "is_friend": True,
                    "avatar_url": "",
                },
            ]

        def close(self):
            return None

    monkeypatch.setattr("app.services.wechat.ingest_service.ContactDBV4", FakeContactDB)

    service = WeChatIngestService()
    imported = service._import_contacts_v4("fake_contact.db", "secret-key", "wxid_me")

    assert imported == 2

    rows = {
        row["username"]: row
        for row in isolated_db.execute(
            "SELECT username, nickname, avatar_path FROM contacts WHERE account_wxid = ? ORDER BY username",
            ("wxid_me",),
        ).fetchall()
    }

    assert rows["wxid_new"]["avatar_path"] == "https://cdn.example/new.jpg"
    assert rows["wxid_existing"]["nickname"] == "新昵称"
    assert rows["wxid_existing"]["avatar_path"] == "https://old.example/avatar.jpg"


def test_import_contacts_filters_wechat_system_accounts(monkeypatch, isolated_db):
    class FakeContactDB:
        def __init__(self, db_path: str, db_key: str):
            assert db_path == "fake_contact.db"
            assert db_key == "secret-key"

        def get_contacts(self):
            return [
                {
                    "username": "notifymessage",
                    "nickname": "",
                    "remark": "",
                    "alias": "",
                    "phone": "",
                    "is_friend": True,
                    "avatar_url": "",
                },
                {
                    "username": "wxid_friend",
                    "nickname": "真实联系人",
                    "remark": "",
                    "alias": "",
                    "phone": "",
                    "is_friend": True,
                    "avatar_url": "",
                },
            ]

        def close(self):
            return None

    monkeypatch.setattr("app.services.wechat.ingest_service.ContactDBV4", FakeContactDB)

    service = WeChatIngestService()
    imported = service._import_contacts_v4("fake_contact.db", "secret-key", "wxid_me")

    usernames = [
        row["username"]
        for row in isolated_db.execute(
            "SELECT username FROM contacts WHERE account_wxid = ? ORDER BY username",
            ("wxid_me",),
        ).fetchall()
    ]

    assert imported == 1
    assert usernames == ["wxid_friend"]


def test_import_cleanup_soft_deletes_existing_system_accounts(isolated_db):
    isolated_db.execute(
        """
        INSERT INTO contacts (account_wxid, username, nickname, is_friend, is_deleted, created_at, updated_at)
        VALUES (?, ?, ?, 1, 0, 1, 1)
        """,
        ("wxid_me", "notifymessage", "",),
    )
    isolated_db.execute(
        """
        INSERT INTO conversations (account_wxid, username, display_name, platform, created_at, updated_at, message_count, is_deleted)
        VALUES (?, ?, ?, 'wechat', 1, 1, 1108, 0)
        """,
        ("wxid_me", "notifymessage", "notifymessage"),
    )
    isolated_db.commit()

    service = WeChatIngestService()
    cleanup_stats = service._soft_delete_excluded_contacts_and_conversations("wxid_me")

    contact_row = isolated_db.execute(
        "SELECT is_deleted FROM contacts WHERE account_wxid = ? AND username = ?",
        ("wxid_me", "notifymessage"),
    ).fetchone()
    conversation_row = isolated_db.execute(
        "SELECT is_deleted FROM conversations WHERE account_wxid = ? AND username = ?",
        ("wxid_me", "notifymessage"),
    ).fetchone()

    assert cleanup_stats == {"contacts": 1, "conversations": 1}
    assert contact_row["is_deleted"] == 1
    assert conversation_row["is_deleted"] == 1


def test_refresh_contact_avatars_backfills_conversations(monkeypatch, isolated_db):
    isolated_db.execute(
        """
        INSERT INTO contacts (account_wxid, username, nickname, avatar_path, is_friend, created_at, updated_at)
        VALUES (?, ?, ?, ?, 1, 1, 1)
        """,
        ("wxid_me", "wxid_target", "目标联系人", "",),
    )
    isolated_db.execute(
        """
        INSERT INTO conversations (account_wxid, username, display_name, platform, avatar_path, created_at, updated_at, message_count)
        VALUES (?, ?, ?, 'wechat', ?, 1, 1, 10)
        """,
        ("wxid_me", "wxid_target", "目标联系人", ""),
    )
    isolated_db.commit()

    class FakeContactDB:
        def __init__(self, db_path: str, db_key: str):
            assert db_path == "fake_contact.db"
            assert db_key == "secret-key"

        def get_contacts(self):
            return [
                {
                    "username": "wxid_target",
                    "nickname": "目标联系人",
                    "remark": "",
                    "alias": "",
                    "phone": "",
                    "is_friend": True,
                    "avatar_url": "https://cdn.example/target.jpg",
                },
            ]

        def close(self):
            return None

    service = WeChatIngestService()
    monkeypatch.setattr(service, "resolve_wechat_paths", lambda custom_paths=None: {
        "wechat_dir": r"D:\WeChat",
        "current_user": "wxid_me",
        "account_wxid": "wxid_me",
        "databases": {"contact": "fake_contact.db", "message": [], "session": None},
    })
    monkeypatch.setattr("app.services.wechat.ingest_service.ContactDBV4", FakeContactDB)

    result = service.refresh_contact_avatars("secret-key", {
        "wechat_dir": r"D:\WeChat",
        "current_user": "wxid_me",
        "account_wxid": "wxid_me",
    })

    assert result["ok"] is True
    assert result["stats"] == {
        "scanned": 1,
        "contact_updates": 1,
        "conversation_updates": 1,
        "skipped_empty": 0,
    }

    contact_row = isolated_db.execute(
        "SELECT avatar_path FROM contacts WHERE account_wxid = ? AND username = ?",
        ("wxid_me", "wxid_target"),
    ).fetchone()
    conversation_row = isolated_db.execute(
        "SELECT avatar_path FROM conversations WHERE account_wxid = ? AND username = ?",
        ("wxid_me", "wxid_target"),
    ).fetchone()

    assert contact_row["avatar_path"] == "https://cdn.example/target.jpg"
    assert conversation_row["avatar_path"] == "https://cdn.example/target.jpg"


def test_analysis_service_falls_back_to_contact_avatar(isolated_db):
    isolated_db.execute(
        """
        INSERT INTO contacts (account_wxid, username, nickname, avatar_path, is_friend, created_at, updated_at)
        VALUES (?, ?, ?, ?, 1, 1, 1)
        """,
        ("wxid_me", "wxid_avatar", "带头像联系人", "https://cdn.example/fallback.jpg"),
    )
    cursor = isolated_db.execute(
        """
        INSERT INTO conversations (account_wxid, username, display_name, platform, avatar_path, created_at, updated_at, message_count)
        VALUES (?, ?, ?, 'wechat', ?, 1, 1700000000, 5)
        """,
        ("wxid_me", "wxid_avatar", "带头像联系人", None),
    )
    isolated_db.commit()

    service = AnalysisService()
    conversation_list = service.get_conversation_list("wxid_me")
    subject_info = service._get_subject_info(cursor.lastrowid)

    assert conversation_list["ok"] is True
    assert conversation_list["conversations"][0]["avatar"] == "https://cdn.example/fallback.jpg"
    assert subject_info["avatar"] == "https://cdn.example/fallback.jpg"


def test_analysis_service_excludes_wechat_system_conversations(isolated_db):
    isolated_db.execute(
        """
        INSERT INTO conversations (account_wxid, username, display_name, platform, created_at, updated_at, message_count)
        VALUES (?, ?, ?, 'wechat', 1, 1700000000, 1108)
        """,
        ("wxid_me", "notifymessage", "notifymessage"),
    )
    isolated_db.execute(
        """
        INSERT INTO conversations (account_wxid, username, display_name, platform, created_at, updated_at, message_count)
        VALUES (?, ?, ?, 'wechat', 1, 1700000001, 5)
        """,
        ("wxid_me", "exmail_tool", "腾讯企业邮箱"),
    )
    isolated_db.execute(
        """
        INSERT INTO conversations (account_wxid, username, display_name, platform, created_at, updated_at, message_count)
        VALUES (?, ?, ?, 'wechat', 1, 1700000002, 5)
        """,
        ("wxid_me", "wxid_friend", "真实联系人"),
    )
    isolated_db.commit()

    conversation_list = AnalysisService().get_conversation_list("wxid_me")

    assert conversation_list["ok"] is True
    assert [item["username"] for item in conversation_list["conversations"]] == ["wxid_friend"]


def test_bridge_word_counts_handles_zero_ratio(isolated_db):
    isolated_db.execute(
        """
        INSERT INTO word_counts
        (conversation_id, session_id, user_char_count, other_char_count, char_ratio, last_updated)
        VALUES (?, NULL, 0, 0, 0, 1)
        """,
        (42,),
    )
    isolated_db.commit()

    with patch("app.webview.bridge.WeChatIngestService", return_value=MagicMock()), \
            patch("app.services.realtime.floating_window_service.FloatingWindowService", return_value=MagicMock()):
        from app.webview.bridge import Bridge

        result = Bridge().get_word_counts(42)

    assert result["success"] is True
    assert result["data"]["overall"]["char_ratio"] == 0
    assert result["data"]["overall"]["interpretation"] == "无字数数据"
