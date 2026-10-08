import locale
import os
import sys
from pathlib import Path


APP_NAME = "Chrono Trace"
# 文件系统统一命名（无空格）：打包产物名与用户数据目录一致（spec 的 APP_NAME 同名）。
# 旧版本安装的数据目录带空格，首次启动新版本时整目录改名迁移（见 _resolve_user_data_dir）。
USER_DATA_DIR_NAME = "ChronoTrace"
LEGACY_USER_DATA_DIR_NAME = "Chrono Trace"
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
    if sys.platform != "win32":
        # Linux：XDG 数据目录（打包/frozen 场景；开发模式仍走仓库内 backend/data）
        xdg_data = os.environ.get("XDG_DATA_HOME")
        if xdg_data:
            return Path(xdg_data).expanduser().resolve()
        return (Path.home() / ".local" / "share").resolve()
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

DEV_DATA_DIR_PATH = SOURCE_ROOT_PATH / "backend" / "data"


def _resolve_user_data_dir() -> Path:
    """解析用户数据目录，处理旧版带空格目录名的一次性迁移。

    迁移规则（仅 frozen 生效，开发模式写仓库内 backend/data 无此历史）：
    - 新目录不存在且旧目录存在 → 整目录 rename（db/日志/模型/GPU runtime 一起搬）
    - rename 失败（权限/占用）→ 降级继续用旧目录，数据不丢
    - 两者都存在（罕见：新版曾以空目录启动过）→ 用新目录不动旧目录
    """
    if not IS_FROZEN:
        return DEV_DATA_DIR_PATH
    root = _local_appdata_root()
    data_dir = root / USER_DATA_DIR_NAME
    legacy_dir = root / LEGACY_USER_DATA_DIR_NAME
    if not data_dir.exists() and legacy_dir.exists():
        try:
            legacy_dir.rename(data_dir)
        except OSError:
            return legacy_dir
    return data_dir


USER_DATA_DIR_PATH = _resolve_user_data_dir()
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
