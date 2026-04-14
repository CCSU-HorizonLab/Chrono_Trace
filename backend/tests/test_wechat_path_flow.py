import os
import sys
from pathlib import Path
from unittest.mock import MagicMock


backend_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(backend_dir))


from app.services.wechat.ingest_service import WeChatIngestService
from app.services.wechat.path_finder import WeChatPathFinder
from app.webview.bridge import Bridge


def test_find_wechat_data_path_expands_registry_base_dir(monkeypatch, tmp_path):
    registry_root = tmp_path / "Documents"
    detected_dir = registry_root / "xwechat_files"
    (detected_dir / "wxid_test").mkdir(parents=True)

    monkeypatch.setattr("app.services.wechat.path_finder.winreg.OpenKey", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(
        "app.services.wechat.path_finder.winreg.QueryValueEx",
        lambda *_args, **_kwargs: (str(registry_root), 1),
    )
    monkeypatch.setattr("app.services.wechat.path_finder.winreg.CloseKey", lambda *_args, **_kwargs: None)

    assert WeChatPathFinder.find_wechat_data_path() == str(detected_dir)


def test_find_wechat_data_path_discovers_nested_dir_from_registry_root(monkeypatch, tmp_path):
    registry_root = tmp_path / "CustomRoot"
    detected_dir = registry_root / "ChatBackup" / "Profiles" / "xwechat_files"
    (detected_dir / "wxid_nested" / "db_storage" / "message").mkdir(parents=True)

    monkeypatch.setattr("app.services.wechat.path_finder.winreg.OpenKey", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(
        "app.services.wechat.path_finder.winreg.QueryValueEx",
        lambda *_args, **_kwargs: (str(registry_root), 1),
    )
    monkeypatch.setattr("app.services.wechat.path_finder.winreg.CloseKey", lambda *_args, **_kwargs: None)

    assert WeChatPathFinder.find_wechat_data_path() == str(detected_dir)


def test_find_current_user_wxid_prefers_account_with_real_databases(tmp_path):
    wechat_root = tmp_path / "xwechat_files"
    empty_user = wechat_root / "wxid_newer_empty"
    real_user = wechat_root / "wxid_real"

    empty_user.mkdir(parents=True)
    (real_user / "db_storage" / "message").mkdir(parents=True)
    (real_user / "db_storage" / "message" / "message_0.db").write_text("", encoding="utf-8")

    os.utime(empty_user, (2_000_000_000, 2_000_000_000))
    os.utime(real_user / "db_storage", (1_000_000_000, 1_000_000_000))

    assert WeChatPathFinder.find_current_user_wxid(str(wechat_root)) == "wxid_real"


def test_find_wechat_data_path_ignores_export_style_wxid_folders(monkeypatch, tmp_path):
    documents_root = tmp_path / "Documents"
    export_root = documents_root / "EchoTrace"
    official_root = tmp_path / "xwechat_files"

    (export_root / "wxid_export_only").mkdir(parents=True)
    (official_root / "wxid_real" / "db_storage" / "message").mkdir(parents=True)
    (official_root / "wxid_real" / "db_storage" / "message" / "message_0.db").write_text("", encoding="utf-8")

    monkeypatch.setattr("app.services.wechat.path_finder.Path.home", lambda: tmp_path)
    monkeypatch.setattr(
        "app.services.wechat.path_finder.WeChatPathFinder._get_documents_paths",
        classmethod(lambda cls: [documents_root]),
    )
    monkeypatch.setattr(
        "app.services.wechat.path_finder.WeChatPathFinder.find_wechat_install_path",
        classmethod(lambda cls: None),
    )
    monkeypatch.delenv("USERPROFILE", raising=False)
    monkeypatch.delenv("OneDrive", raising=False)
    monkeypatch.delenv("OneDriveConsumer", raising=False)
    monkeypatch.delenv("OneDriveCommercial", raising=False)
    monkeypatch.setattr(
        "app.services.wechat.path_finder.WeChatPathFinder._query_registry_value",
        staticmethod(lambda *args, **kwargs: None),
    )

    assert WeChatPathFinder.find_wechat_data_path() == str(official_root)



def test_find_databases_accepts_direct_wxid_dir(tmp_path):
    user_dir = tmp_path / "xwechat_files" / "wxid_direct"
    contact_db = user_dir / "db_storage" / "contact" / "contact.db"
    message_db = user_dir / "db_storage" / "message" / "message_0.db"
    session_db = user_dir / "db_storage" / "session" / "session.db"

    contact_db.parent.mkdir(parents=True)
    message_db.parent.mkdir(parents=True)
    session_db.parent.mkdir(parents=True)
    contact_db.write_text("", encoding="utf-8")
    message_db.write_text("", encoding="utf-8")
    session_db.write_text("", encoding="utf-8")

    databases = WeChatPathFinder.find_databases("wxid_direct", str(user_dir))

    assert databases["contact"] == str(contact_db)
    assert databases["message"] == [str(message_db)]
    assert databases["session"] == str(session_db)


def test_bridge_verify_wechat_key_prefers_saved_selected_paths():
    bridge = Bridge.__new__(Bridge)
    bridge.wechat_service = MagicMock()
    bridge.wechat_service.verify_key.return_value = {"ok": True}
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

    result = bridge.verify_wechat_key("secret-key")

    assert result == {"ok": True}
    bridge.wechat_service.verify_key.assert_called_once_with(
        "secret-key",
        {
            "wechat_dir": r"D:\WeChat\xwechat_files",
            "current_user": "wxid_selected",
            "account_wxid": "wxid_selected",
        },
    )


def test_ingest_service_verify_key_uses_custom_paths(monkeypatch):
    service = WeChatIngestService()
    custom_paths = {
        "wechat_dir": r"D:\WeChat\xwechat_files",
        "current_user": "wxid_manual",
    }
    resolved_paths = {
        "wechat_dir": custom_paths["wechat_dir"],
        "current_user": custom_paths["current_user"],
        "databases": {
            "message": [r"D:\WeChat\xwechat_files\wxid_manual\db_storage\message\message_0.db"],
            "contact": None,
            "session": None,
        },
    }
    captured = {}

    def fake_resolve(paths):
        captured["custom_paths"] = paths
        return resolved_paths

    monkeypatch.setattr(service, "resolve_wechat_paths", fake_resolve)
    monkeypatch.setattr(
        "app.services.wechat.ingest_service.WeChatDBDecryptor.verify_key",
        lambda db_path, key_hex: db_path == resolved_paths["databases"]["message"][0] and key_hex == "valid-key",
    )

    result = service.verify_key("valid-key", custom_paths)

    assert result == {"ok": True}
    assert captured["custom_paths"] == custom_paths


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
