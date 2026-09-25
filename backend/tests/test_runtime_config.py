import importlib
import sys
from pathlib import Path

import backend.app.config as config_module


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
        expected_root = xdg_data / "Chrono Trace"
    else:
        config = _reload_config(monkeypatch, tmp_path, frozen=True)
        expected_root = tmp_path / "LocalAppData" / "Chrono Trace"
    assert Path(config.DATA_DIR) == expected_root
    assert Path(config.SETTINGS_PATH) == expected_root / "settings.json"
    assert Path(config.DB_PATH) == expected_root / "chrono_trace.db"


def test_frontend_dist_prefers_webdist_and_falls_back_to_legacy(monkeypatch, tmp_path):
    config = _reload_config(monkeypatch, tmp_path)

    frontend_dir = tmp_path / "frontend"
    legacy_dir = frontend_dir / "dist"
    preferred_dir = frontend_dir / "webdist"
    legacy_dir.mkdir(parents=True)

    assert config._preferred_frontend_dist_dir(frontend_dir) == legacy_dir

    preferred_dir.mkdir(parents=True)
    assert config._preferred_frontend_dist_dir(frontend_dir) == preferred_dir
