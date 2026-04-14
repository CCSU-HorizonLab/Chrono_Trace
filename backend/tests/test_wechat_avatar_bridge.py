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
        "wechat_data_dir": r"D:\WeChat\xwechat_files",
        "wechat_user_wxid": "wxid_selected",
    }

    result = bridge.refresh_wechat_contact_avatars("secret-key")

    assert result == {"ok": True, "stats": {"scanned": 1}}
    bridge.wechat_service.refresh_contact_avatars.assert_called_once_with(
        "secret-key",
        {
            "wechat_dir": r"D:\WeChat\xwechat_files",
            "current_user": "wxid_selected",
        },
    )


def test_bridge_get_current_user_profile_prefers_local_contact_avatar(tmp_path):
    DatabaseConnection.close()
    DatabaseConnection._db_path = None

    db_path = tmp_path / "chrono_trace_test.db"
    conn = DatabaseConnection.initialize(str(db_path))
    conn.execute(
        """
        INSERT INTO contacts (username, nickname, avatar_path, is_friend, created_at, updated_at)
        VALUES (?, ?, ?, 1, 1, 1)
        """,
        ("wxid_self", "时痕", "https://cdn.example/self.jpg"),
    )
    conn.commit()

    bridge = Bridge.__new__(Bridge)
    bridge.wechat_service = MagicMock()
    bridge.settings = {
        "wechat_user_wxid": "wxid_self",
        "wechat_db_key": "secret-key",
        "wechat_data_dir": r"D:\WeChat\xwechat_files",
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
        INSERT INTO contacts (username, nickname, avatar_path, is_friend, created_at, updated_at)
        VALUES (?, ?, ?, 1, 1, 1)
        """,
        ("wxid_selfbase", "时痕", "https://cdn.example/selfbase.jpg"),
    )
    conn.commit()

    bridge = Bridge.__new__(Bridge)
    bridge.wechat_service = MagicMock()
    bridge.settings = {
        "wechat_user_wxid": "wxid_selfbase_9cc7",
        "wechat_db_key": "secret-key",
        "wechat_data_dir": r"D:\WeChat\xwechat_files",
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
