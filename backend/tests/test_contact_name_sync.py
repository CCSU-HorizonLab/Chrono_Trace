import sys
from pathlib import Path
from unittest.mock import patch

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


def test_upsert_contacts_syncs_conversation_display_name(monkeypatch, isolated_db):
    """联系人备注名/昵称变更后，conversations 冗余字段应同步更新。"""
    # 预置旧数据：联系人旧备注为"旧备注"，会话 display_name 也是"旧备注"
    isolated_db.execute(
        """
        INSERT INTO contacts (account_wxid, username, nickname, remark, is_friend, created_at, updated_at)
        VALUES (?, ?, ?, ?, 1, 1, 1)
        """,
        ("wxid_me", "wxid_friend", "旧昵称", "旧备注"),
    )
    isolated_db.execute(
        """
        INSERT INTO conversations (account_wxid, username, display_name, remark, nickname, platform, created_at, updated_at, message_count)
        VALUES (?, ?, ?, ?, ?, 'wechat', 1, 1, 10)
        """,
        ("wxid_me", "wxid_friend", "旧备注", "旧备注", "旧昵称"),
    )
    isolated_db.commit()

    class FakeContactDB:
        def __init__(self, db_path: str, db_key: str):
            pass

        def get_contacts(self):
            return [
                {
                    "username": "wxid_friend",
                    "nickname": "新昵称",
                    "remark": "新备注",
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

    assert imported == 1

    conv_row = isolated_db.execute(
        "SELECT display_name, remark, nickname FROM conversations WHERE account_wxid = ? AND username = ?",
        ("wxid_me", "wxid_friend"),
    ).fetchone()

    assert conv_row["display_name"] == "新备注"
    assert conv_row["remark"] == "新备注"
    assert conv_row["nickname"] == "新昵称"


def test_upsert_contacts_fallback_to_nickname_when_remark_empty(monkeypatch, isolated_db):
    """备注为空时，conversations.display_name 应回退到昵称。"""
    isolated_db.execute(
        """
        INSERT INTO contacts (account_wxid, username, nickname, remark, is_friend, created_at, updated_at)
        VALUES (?, ?, ?, ?, 1, 1, 1)
        """,
        ("wxid_me", "wxid_friend", "旧昵称", "旧备注"),
    )
    isolated_db.execute(
        """
        INSERT INTO conversations (account_wxid, username, display_name, remark, nickname, platform, created_at, updated_at, message_count)
        VALUES (?, ?, ?, ?, ?, 'wechat', 1, 1, 10)
        """,
        ("wxid_me", "wxid_friend", "旧备注", "旧备注", "旧昵称"),
    )
    isolated_db.commit()

    class FakeContactDB:
        def __init__(self, db_path: str, db_key: str):
            pass

        def get_contacts(self):
            return [
                {
                    "username": "wxid_friend",
                    "nickname": "只有昵称",
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
    service._import_contacts_v4("fake_contact.db", "secret-key", "wxid_me")

    conv_row = isolated_db.execute(
        "SELECT display_name, remark, nickname FROM conversations WHERE account_wxid = ? AND username = ?",
        ("wxid_me", "wxid_friend"),
    ).fetchone()

    assert conv_row["display_name"] == "只有昵称"
    assert conv_row["remark"] == ""
    assert conv_row["nickname"] == "只有昵称"


def test_upsert_contacts_fallback_to_username_when_both_empty(monkeypatch, isolated_db):
    """备注和昵称均为空时，conversations.display_name 应回退到 username。"""
    isolated_db.execute(
        """
        INSERT INTO contacts (account_wxid, username, nickname, remark, is_friend, created_at, updated_at)
        VALUES (?, ?, ?, ?, 1, 1, 1)
        """,
        ("wxid_me", "wxid_friend", "旧昵称", "旧备注"),
    )
    isolated_db.execute(
        """
        INSERT INTO conversations (account_wxid, username, display_name, remark, nickname, platform, created_at, updated_at, message_count)
        VALUES (?, ?, ?, ?, ?, 'wechat', 1, 1, 10)
        """,
        ("wxid_me", "wxid_friend", "旧备注", "旧备注", "旧昵称"),
    )
    isolated_db.commit()

    class FakeContactDB:
        def __init__(self, db_path: str, db_key: str):
            pass

        def get_contacts(self):
            return [
                {
                    "username": "wxid_friend",
                    "nickname": "",
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
    service._import_contacts_v4("fake_contact.db", "secret-key", "wxid_me")

    conv_row = isolated_db.execute(
        "SELECT display_name, remark, nickname FROM conversations WHERE account_wxid = ? AND username = ?",
        ("wxid_me", "wxid_friend"),
    ).fetchone()

    assert conv_row["display_name"] == "wxid_friend"
    assert conv_row["remark"] == ""
    assert conv_row["nickname"] == ""


def test_upsert_contacts_does_not_affect_other_accounts(monkeypatch, isolated_db):
    """多账户隔离：更新 A 账户联系人不应影响 B 账户的会话名称。"""
    isolated_db.execute(
        """
        INSERT INTO contacts (account_wxid, username, nickname, remark, is_friend, created_at, updated_at)
        VALUES (?, ?, ?, ?, 1, 1, 1)
        """,
        ("wxid_a", "wxid_friend", "A的备注", "A的备注"),
    )
    isolated_db.execute(
        """
        INSERT INTO conversations (account_wxid, username, display_name, remark, nickname, platform, created_at, updated_at, message_count)
        VALUES (?, ?, ?, ?, ?, 'wechat', 1, 1, 10)
        """,
        ("wxid_a", "wxid_friend", "A的备注", "A的备注", "A的备注"),
    )
    isolated_db.execute(
        """
        INSERT INTO conversations (account_wxid, username, display_name, remark, nickname, platform, created_at, updated_at, message_count)
        VALUES (?, ?, ?, ?, ?, 'wechat', 1, 1, 10)
        """,
        ("wxid_b", "wxid_friend", "B的旧备注", "B的旧备注", "B的旧昵称"),
    )
    isolated_db.commit()

    class FakeContactDB:
        def __init__(self, db_path: str, db_key: str):
            pass

        def get_contacts(self):
            return [
                {
                    "username": "wxid_friend",
                    "nickname": "A新昵称",
                    "remark": "A新备注",
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
    service._import_contacts_v4("fake_contact.db", "secret-key", "wxid_a")

    b_conv = isolated_db.execute(
        "SELECT display_name, remark, nickname FROM conversations WHERE account_wxid = ? AND username = ?",
        ("wxid_b", "wxid_friend"),
    ).fetchone()

    assert b_conv["display_name"] == "B的旧备注"
    assert b_conv["remark"] == "B的旧备注"
    assert b_conv["nickname"] == "B的旧昵称"
