import os
import sys
from pathlib import Path
from unittest.mock import MagicMock


backend_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(backend_dir))


from app.services.wechat.ingest_service import WeChatIngestService
from app.services.wechat.path_finder import WeChatPathFinder
from app.webview.bridge import Bridge


class _FakeWinreg:
    """跨平台注册表桩：Linux 上 path_finder.winreg 为 None，
    测试通过替换整个模块属性注入（两平台行为一致）。"""

    HKEY_CURRENT_USER = 1
    HKEY_LOCAL_MACHINE = 2

    def __init__(self, value):
        self._value = value

    def OpenKey(self, *_args, **_kwargs):
        return object()

    def QueryValueEx(self, *_args, **_kwargs):
        return (self._value, 1)

    def CloseKey(self, *_args, **_kwargs):
        return None


def _install_fake_winreg(monkeypatch, value):
    monkeypatch.setattr(
        "app.services.wechat.path_finder.winreg",
        _FakeWinreg(str(value)),
    )


def test_find_wechat_data_path_expands_registry_base_dir(monkeypatch, tmp_path):
    registry_root = tmp_path / "Documents"
    detected_dir = registry_root / "xwechat_files"
    (detected_dir / "wxid_test").mkdir(parents=True)

    _install_fake_winreg(monkeypatch, registry_root)

    assert WeChatPathFinder.find_wechat_data_path() == str(detected_dir)


def test_find_wechat_data_path_discovers_nested_dir_from_registry_root(monkeypatch, tmp_path):
    registry_root = tmp_path / "CustomRoot"
    detected_dir = registry_root / "ChatBackup" / "Profiles" / "xwechat_files"
    (detected_dir / "wxid_nested" / "db_storage" / "message").mkdir(parents=True)

    _install_fake_winreg(monkeypatch, registry_root)

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


def test_find_all_user_wxids_discovers_custom_named_accounts(tmp_path):
    """设置过自定义微信号的账号目录不以 wxid_ 开头，也应按结构特征被扫到。"""
    wechat_root = tmp_path / "xwechat_files"
    default_user = wechat_root / "wxid_default"
    custom_user = wechat_root / "custom_wxid_account"

    for user in (default_user, custom_user):
        message_dir = user / "db_storage" / "message"
        message_dir.mkdir(parents=True)
        (message_dir / "message_0.db").write_text("", encoding="utf-8")

    wxids = WeChatPathFinder.find_all_user_wxids(str(wechat_root))

    assert "custom_wxid_account" in wxids
    assert "wxid_default" in wxids

    databases = WeChatPathFinder.find_databases("custom_wxid_account", str(wechat_root))
    assert databases["message"] == [str(custom_user / "db_storage" / "message" / "message_0.db")]


def test_find_wechat_data_path_detects_root_with_custom_named_accounts(monkeypatch, tmp_path):
    documents_root = tmp_path / "Documents"
    detected_dir = documents_root / "xwechat_files"
    (detected_dir / "custom_account" / "db_storage" / "message").mkdir(parents=True)

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

    assert WeChatPathFinder.find_wechat_data_path() == str(detected_dir)
    assert WeChatPathFinder.find_current_user_wxid(str(detected_dir)) == "custom_account"


def test_bridge_scan_wechat_directory_accepts_custom_named_account_dir(tmp_path):
    user_dir = tmp_path / "xwechat_files" / "custom_account"
    message_db = user_dir / "db_storage" / "message" / "message_0.db"
    message_db.parent.mkdir(parents=True)
    message_db.write_text("", encoding="utf-8")

    bridge = Bridge.__new__(Bridge)
    bridge._settings_lock = __import__('threading').RLock()
    bridge.settings = {"wechat_accounts": []}

    result = bridge.scan_wechat_directory(str(user_dir))

    assert result["ok"] is True
    assert result["wxids"] == ["custom_account"]
    assert result["databases"]["custom_account"]["msg_dbs"] == [str(message_db)]


def test_bridge_verify_wechat_key_prefers_saved_selected_paths():
    bridge = Bridge.__new__(Bridge)
    bridge._settings_lock = __import__('threading').RLock()
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
    bridge._settings_lock = __import__('threading').RLock()
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
        raw_keys=None,
    )


# ==================== Linux 平台路径发现（阶段一移植） ====================


def test_read_xdg_user_dir_parses_user_dirs_file(monkeypatch, tmp_path):
    config_dir = tmp_path / ".config"
    config_dir.mkdir()
    (config_dir / "user-dirs.dirs").write_text(
        '# 注释\nXDG_DOCUMENTS_DIR="$HOME/文档"\nXDG_DOWNLOAD_DIR="$HOME/Downloads"\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("HOME", str(tmp_path))

    assert WeChatPathFinder._read_xdg_user_dir("XDG_DOCUMENTS_DIR") == tmp_path / "文档"
    assert WeChatPathFinder._read_xdg_user_dir("XDG_DOWNLOAD_DIR") == tmp_path / "Downloads"
    assert WeChatPathFinder._read_xdg_user_dir("XDG_MISSING_DIR") is None


def test_find_wechat_data_path_discovers_linux_xdg_documents(monkeypatch, tmp_path):
    detected_dir = tmp_path / "文档" / "xwechat_files"
    (detected_dir / "lishao378_86f8" / "db_storage" / "message").mkdir(parents=True)
    (detected_dir / "lishao378_86f8" / "db_storage" / "message" / "message_0.db").write_text("", encoding="utf-8")

    config_dir = tmp_path / ".config"
    config_dir.mkdir()
    (config_dir / "user-dirs.dirs").write_text(
        'XDG_DOCUMENTS_DIR="$HOME/文档"\n',
        encoding="utf-8",
    )
    # 屏蔽宿主机环境干扰
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("USERPROFILE", raising=False)
    monkeypatch.delenv("OneDrive", raising=False)
    monkeypatch.delenv("OneDriveConsumer", raising=False)
    monkeypatch.delenv("OneDriveCommercial", raising=False)
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)

    assert WeChatPathFinder.find_wechat_data_path() == str(detected_dir)
    assert WeChatPathFinder.find_all_user_wxids(str(detected_dir)) == ["lishao378_86f8"]


def _shield_auto_candidates(monkeypatch, tmp_path, documents_root):
    """屏蔽宿主机环境，让自动扫描只看到 documents_root。"""
    _install_fake_winreg(monkeypatch, tmp_path / "RegistryMissing")
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


def _make_v39_user_dir(base: Path, name: str = "wxid_old") -> Path:
    user_dir = base / name
    msg_dir = user_dir / "Msg"
    multi_dir = msg_dir / "Multi"
    multi_dir.mkdir(parents=True)
    (msg_dir / "MicroMsg.db").write_text("", encoding="utf-8")
    (multi_dir / "MSG0.db").write_text("", encoding="utf-8")
    (multi_dir / "MSG1.db").write_text("", encoding="utf-8")
    return user_dir


def test_find_legacy_v3_info_detects_wechat_39_structure(monkeypatch, tmp_path):
    documents_root = tmp_path / "Documents"
    v3_root = documents_root / "WeChat Files"
    _make_v39_user_dir(v3_root)

    _shield_auto_candidates(monkeypatch, tmp_path, documents_root)

    assert WeChatPathFinder.find_legacy_v3_info() == {
        "wechat_dir": str(v3_root),
        "users": ["wxid_old"],
    }


def test_find_legacy_v3_info_returns_none_when_only_v4(monkeypatch, tmp_path):
    documents_root = tmp_path / "Documents"
    v4_root = documents_root / "xwechat_files"
    user_dir = v4_root / "wxid_new"
    (user_dir / "db_storage" / "message").mkdir(parents=True)
    (user_dir / "db_storage" / "message" / "message_0.db").write_text("", encoding="utf-8")

    _shield_auto_candidates(monkeypatch, tmp_path, documents_root)

    assert WeChatPathFinder.find_legacy_v3_info() is None


def test_find_legacy_v3_info_ignores_dir_without_db_evidence(tmp_path):
    decoy = tmp_path / "wxid_decoy"
    (decoy / "Msg").mkdir(parents=True)  # 只有 Msg 目录、无任何库文件

    assert WeChatPathFinder._inspect_legacy_v3_root(tmp_path) is None


def test_get_wechat_paths_reports_legacy_v3_when_only_v39_present(monkeypatch, tmp_path):
    documents_root = tmp_path / "Documents"
    v3_root = documents_root / "WeChat Files"
    _make_v39_user_dir(v3_root)

    _shield_auto_candidates(monkeypatch, tmp_path, documents_root)

    result = WeChatIngestService().get_wechat_paths()

    assert result["ok"] is False
    assert result["code"] == "legacy_wechat_v3"
    assert result["v3"]["wechat_dir"] == str(v3_root)
    assert result["v3"]["users"] == ["wxid_old"]


def test_bridge_scan_wechat_directory_reports_legacy_v3(tmp_path):
    v3_root = tmp_path / "WeChat Files"
    _make_v39_user_dir(v3_root)

    bridge = Bridge.__new__(Bridge)
    bridge._settings_lock = __import__('threading').RLock()
    bridge.settings = {"wechat_accounts": []}

    result = bridge.scan_wechat_directory(str(v3_root))

    assert result["ok"] is False
    assert result["code"] == "legacy_wechat_v3"
    assert result["v3"]["users"] == ["wxid_old"]


def test_bridge_scan_wechat_directory_reports_legacy_v3_for_account_dir(tmp_path):
    v3_root = tmp_path / "WeChat Files"
    user_dir = _make_v39_user_dir(v3_root)

    bridge = Bridge.__new__(Bridge)
    bridge._settings_lock = __import__('threading').RLock()
    bridge.settings = {"wechat_accounts": []}

    result = bridge.scan_wechat_directory(str(user_dir))

    assert result["ok"] is False
    assert result["code"] == "legacy_wechat_v3"
    assert result["v3"]["wechat_dir"] == str(v3_root)
    assert result["v3"]["users"] == ["wxid_old"]


def test_detect_wechat_version_recognizes_v3_structure(tmp_path):
    from app.services.wechat.db.detector import detect_wechat_version

    user_dir = _make_v39_user_dir(tmp_path)
    assert detect_wechat_version(str(user_dir)) == "v3"

    v4_dir = tmp_path / "wxid_new"
    (v4_dir / "db_storage").mkdir(parents=True)
    assert detect_wechat_version(str(v4_dir)) == "v4"

    assert detect_wechat_version(str(tmp_path / "not_exists")) == "unknown"
