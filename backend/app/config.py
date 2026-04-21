import locale
import os
import sys
from pathlib import Path


APP_NAME = "Chrono Trace"
FRONTEND_BUILD_DIR_NAME = "webdist"
LEGACY_FRONTEND_BUILD_DIR_NAME = "dist"


def _source_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _bundle_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent)).resolve()
    return _source_root()


def _install_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return _source_root()


def _local_appdata_root() -> Path:
    raw = os.environ.get("LOCALAPPDATA")
    if raw:
        return Path(raw).expanduser().resolve()
    return (Path.home() / "AppData" / "Local").resolve()


def _preferred_frontend_dist_dir(frontend_dir: Path) -> Path:
    preferred = frontend_dir / FRONTEND_BUILD_DIR_NAME
    legacy = frontend_dir / LEGACY_FRONTEND_BUILD_DIR_NAME
    if preferred.exists() or not legacy.exists():
        return preferred
    return legacy


def ensure_directory(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


SOURCE_ROOT_PATH = _source_root()
RESOURCE_ROOT_PATH = _bundle_root()
INSTALL_ROOT_PATH = _install_root()
IS_FROZEN = bool(getattr(sys, "frozen", False))

BACKEND_DIR_PATH = RESOURCE_ROOT_PATH / "backend"
BACKEND_APP_DIR_PATH = BACKEND_DIR_PATH / "app"
FRONTEND_DIR_PATH = RESOURCE_ROOT_PATH / "frontend"
FRONTEND_DIST_DIR_PATH = _preferred_frontend_dist_dir(FRONTEND_DIR_PATH)

USER_DATA_DIR_PATH = _local_appdata_root() / APP_NAME
LOG_DIR_PATH = USER_DATA_DIR_PATH / "logs"
MODELS_DIR_PATH = USER_DATA_DIR_PATH / "models"
TEMP_DIR_PATH = USER_DATA_DIR_PATH / "temp"

SETTINGS_PATH = USER_DATA_DIR_PATH / "settings.json"
DB_PATH = USER_DATA_DIR_PATH / "chrono_trace.db"
MAIN_LOG_FILE_PATH = LOG_DIR_PATH / "chrono_trace.log"
SENTIMENT_MODEL_DIR_PATH = MODELS_DIR_PATH / "sentiment_3class"
DB_SCHEMA_PATH = BACKEND_APP_DIR_PATH / "db" / "schema.sql"
DB_MIGRATIONS_DIR_PATH = BACKEND_APP_DIR_PATH / "db" / "migrations"

for _required_dir in (
    USER_DATA_DIR_PATH,
    LOG_DIR_PATH,
    MODELS_DIR_PATH,
    TEMP_DIR_PATH,
):
    ensure_directory(_required_dir)


# Backward-compatible string constants
PROJECT_ROOT = str(SOURCE_ROOT_PATH)
RESOURCE_ROOT = str(RESOURCE_ROOT_PATH)
INSTALL_ROOT = str(INSTALL_ROOT_PATH)
FRONTEND_DIR = str(FRONTEND_DIR_PATH)
DATA_DIR = str(USER_DATA_DIR_PATH)
LOG_DIR = str(LOG_DIR_PATH)
MAIN_LOG_FILE = str(MAIN_LOG_FILE_PATH)

# 默认开发期本地地址（可被环境变量 DEV_URL 覆盖）
DEV_URL_DEFAULT = "http://localhost:5173"


def _get_window_name() -> str:
    """中文系统显示「时痕」，英文系统显示「Chrono Trace」"""
    try:
        lang = locale.getdefaultlocale()[0] or ""
        if lang.startswith("zh"):
            return "时痕"
    except Exception:
        pass
    return APP_NAME


_APP_NAME = _get_window_name()
PROD_WINDOW_TITLE = _APP_NAME
DEV_WINDOW_TITLE = f"{_APP_NAME} (DEV)"


def get_dist_index_path() -> str:
    """返回前端构建产物入口 index.html 路径，没有则返回空字符串。"""
    dist_index = FRONTEND_DIST_DIR_PATH / "index.html"
    return str(dist_index) if dist_index.exists() else ""
