import sys
from pathlib import Path
from unittest.mock import MagicMock


backend_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(backend_dir))


from app.db.connection import DatabaseConnection
from app.webview.bridge import Bridge


def test_bridge_refresh_wechat_contact_avatars_prefers_saved_selected_paths():
    bridge = Bridge.__new__(Bridge)
    bridge.wechat_service = MagicMock()
    bridge.wechat_service.refresh_contact_avatars.return_value = {"ok": True, "stats": {"scanned": 1}}
    bridge.settings = {
        "wechat_accounts": [
            {
                "wxid": "wxid_selected",
                "label": "wxid_selected",
                "avatar": "",
                "wechat_dir": r"D:\WeChat\xwechat_files",
                "source": "custom",
                "db_key": "",
                "import_completed": False,
                "last_import_total_size": 0,
                "last_import_files": [],
            }
        ],
        "wechat_active_account_wxid": "wxid_selected",
    }

    result = bridge.refresh_wechat_contact_avatars("secret-key")

    assert result == {"ok": True, "stats": {"scanned": 1}}
    bridge.wechat_service.refresh_contact_avatars.assert_called_once_with(
        "secret-key",
        {
            "wechat_dir": r"D:\WeChat\xwechat_files",
            "current_user": "wxid_selected",
            "account_wxid": "wxid_selected",
        },
    )


def test_bridge_get_current_user_profile_prefers_local_contact_avatar(tmp_path):
    DatabaseConnection.close()
    DatabaseConnection._db_path = None

    db_path = tmp_path / "chrono_trace_test.db"
    conn = DatabaseConnection.initialize(str(db_path))
    conn.execute(
        """
        INSERT INTO contacts (account_wxid, username, nickname, avatar_path, is_friend, created_at, updated_at)
        VALUES (?, ?, ?, ?, 1, 1, 1)
        """,
        ("wxid_self", "wxid_self", "时痕", "https://cdn.example/self.jpg"),
    )
    conn.commit()

    bridge = Bridge.__new__(Bridge)
    bridge.wechat_service = MagicMock()
    bridge.settings = {
        "wechat_accounts": [
            {
                "wxid": "wxid_self",
                "label": "wxid_self",
                "avatar": "",
                "wechat_dir": r"D:\WeChat\xwechat_files",
                "source": "custom",
                "db_key": "secret-key",
                "import_completed": False,
                "last_import_total_size": 0,
                "last_import_files": [],
            }
        ],
        "wechat_active_account_wxid": "wxid_self",
    }

    try:
        result = bridge.get_current_user_profile()
    finally:
        DatabaseConnection.close()
        DatabaseConnection._db_path = None

    assert result == {
        "ok": True,
        "profile": {
            "wxid": "wxid_self",
            "name": "时痕",
            "avatar": "https://cdn.example/self.jpg",
        },
    }
    bridge.wechat_service.resolve_wechat_paths.assert_not_called()


def test_bridge_get_current_user_profile_supports_suffixed_wechat_dir_wxid(tmp_path):
    DatabaseConnection.close()
    DatabaseConnection._db_path = None

    db_path = tmp_path / "chrono_trace_test.db"
    conn = DatabaseConnection.initialize(str(db_path))
    conn.execute(
        """
        INSERT INTO contacts (account_wxid, username, nickname, avatar_path, is_friend, created_at, updated_at)
        VALUES (?, ?, ?, ?, 1, 1, 1)
        """,
        ("wxid_selfbase_9cc7", "wxid_selfbase", "时痕", "https://cdn.example/selfbase.jpg"),
    )
    conn.commit()

    bridge = Bridge.__new__(Bridge)
    bridge.wechat_service = MagicMock()
    bridge.settings = {
        "wechat_accounts": [
            {
                "wxid": "wxid_selfbase_9cc7",
                "label": "wxid_selfbase_9cc7",
                "avatar": "",
                "wechat_dir": r"D:\WeChat\xwechat_files",
                "source": "custom",
                "db_key": "secret-key",
                "import_completed": False,
                "last_import_total_size": 0,
                "last_import_files": [],
            }
        ],
        "wechat_active_account_wxid": "wxid_selfbase_9cc7",
    }

    try:
        result = bridge.get_current_user_profile()
    finally:
        DatabaseConnection.close()
        DatabaseConnection._db_path = None

    assert result == {
        "ok": True,
        "profile": {
            "wxid": "wxid_selfbase",
            "name": "时痕",
            "avatar": "https://cdn.example/selfbase.jpg",
        },
    }
    bridge.wechat_service.resolve_wechat_paths.assert_not_called()
