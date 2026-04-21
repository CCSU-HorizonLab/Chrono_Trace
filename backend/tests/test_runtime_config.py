import importlib
import sys
from pathlib import Path

import backend.app.config as config_module


def _reload_config(monkeypatch, tmp_path: Path):
    local_appdata = tmp_path / "LocalAppData"
    monkeypatch.setenv("LOCALAPPDATA", str(local_appdata))
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    monkeypatch.delattr(sys, "_MEIPASS", raising=False)
    return importlib.reload(config_module)


def test_user_data_paths_use_localappdata(monkeypatch, tmp_path):
    config = _reload_config(monkeypatch, tmp_path)

    expected_root = tmp_path / "LocalAppData" / "Chrono Trace"
    assert Path(config.DATA_DIR) == expected_root
    assert Path(config.SETTINGS_PATH) == expected_root / "settings.json"
    assert Path(config.DB_PATH) == expected_root / "chrono_trace.db"
    assert Path(config.LOG_DIR) == expected_root / "logs"


def test_frontend_dist_prefers_webdist_and_falls_back_to_legacy(monkeypatch, tmp_path):
    config = _reload_config(monkeypatch, tmp_path)

    frontend_dir = tmp_path / "frontend"
    legacy_dir = frontend_dir / "dist"
    preferred_dir = frontend_dir / "webdist"
    legacy_dir.mkdir(parents=True)

    assert config._preferred_frontend_dist_dir(frontend_dir) == legacy_dir

    preferred_dir.mkdir(parents=True)
    assert config._preferred_frontend_dist_dir(frontend_dir) == preferred_dir
