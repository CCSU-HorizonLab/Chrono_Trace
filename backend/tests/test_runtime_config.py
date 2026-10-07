import importlib
import sys
from pathlib import Path

import app.config as config_module


def _reload_config(monkeypatch, tmp_path: Path, *, frozen: bool = False):
    local_appdata = tmp_path / "LocalAppData"
    monkeypatch.setenv("LOCALAPPDATA", str(local_appdata))
    monkeypatch.setattr(sys, "frozen", frozen, raising=False)
    monkeypatch.delattr(sys, "_MEIPASS", raising=False)
    return importlib.reload(config_module)


def test_dev_user_data_paths_use_project_data_directory(monkeypatch, tmp_path):
    config = _reload_config(monkeypatch, tmp_path)

    expected_root = config.SOURCE_ROOT_PATH / "backend" / "data"
    assert Path(config.DATA_DIR) == expected_root
    assert Path(config.SETTINGS_PATH) == expected_root / "settings.json"
    assert Path(config.DB_PATH) == expected_root / "chrono_trace.db"
    assert Path(config.LOG_DIR) == expected_root / "logs"


def test_frozen_user_data_paths_use_production_directory(monkeypatch, tmp_path):
    if sys.platform != "win32":
        # Linux frozen 走 XDG 数据目录（LOCALAPPDATA 不参与）
        xdg_data = tmp_path / "XDGData"
        monkeypatch.setenv("XDG_DATA_HOME", str(xdg_data))
        config = _reload_config(monkeypatch, tmp_path, frozen=True)
        expected_root = xdg_data / "ChronoTrace"
    else:
        config = _reload_config(monkeypatch, tmp_path, frozen=True)
        expected_root = tmp_path / "LocalAppData" / "ChronoTrace"
    assert Path(config.DATA_DIR) == expected_root
    assert Path(config.SETTINGS_PATH) == expected_root / "settings.json"
    assert Path(config.DB_PATH) == expected_root / "chrono_trace.db"


def test_frozen_migrates_legacy_spaced_data_dir(monkeypatch, tmp_path):
    """旧版带空格数据目录在首次启动新版本时整目录迁移到无空格目录。"""
    if sys.platform != "win32":
        xdg_data = tmp_path / "XDGData"
        monkeypatch.setenv("XDG_DATA_HOME", str(xdg_data))
        root = xdg_data
    else:
        monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "LocalAppData"))
        root = tmp_path / "LocalAppData"

    legacy = root / "Chrono Trace"
    legacy.mkdir(parents=True)
    (legacy / "chrono_trace.db").write_text("db")
    (legacy / "logs").mkdir()

    config = _reload_config(monkeypatch, tmp_path, frozen=True)

    new_dir = root / "ChronoTrace"
    assert Path(config.DATA_DIR) == new_dir
    assert (new_dir / "chrono_trace.db").read_text() == "db"  # 数据随目录一起搬
    assert not legacy.exists()  # 旧目录已改名，无残留副本


def test_frozen_both_dirs_exist_prefers_new(monkeypatch, tmp_path):
    """新旧目录都在（新版曾以空目录启动过）时用新目录、不动旧目录。"""
    if sys.platform != "win32":
        xdg_data = tmp_path / "XDGData"
        monkeypatch.setenv("XDG_DATA_HOME", str(xdg_data))
        root = xdg_data
    else:
        monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "LocalAppData"))
        root = tmp_path / "LocalAppData"

    legacy = root / "Chrono Trace"
    legacy.mkdir(parents=True)
    (legacy / "chrono_trace.db").write_text("old")
    new_dir = root / "ChronoTrace"
    new_dir.mkdir(parents=True)

    config = _reload_config(monkeypatch, tmp_path, frozen=True)

    assert Path(config.DATA_DIR) == new_dir
    assert legacy.exists()  # 不做合并，旧目录保留原处


def test_frontend_dist_prefers_webdist_and_falls_back_to_legacy(monkeypatch, tmp_path):
    config = _reload_config(monkeypatch, tmp_path)

    frontend_dir = tmp_path / "frontend"
    legacy_dir = frontend_dir / "dist"
    preferred_dir = frontend_dir / "webdist"
    legacy_dir.mkdir(parents=True)

    assert config._preferred_frontend_dist_dir(frontend_dir) == legacy_dir

    preferred_dir.mkdir(parents=True)
    assert config._preferred_frontend_dist_dir(frontend_dir) == preferred_dir
