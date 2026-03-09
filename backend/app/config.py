import os
import locale

# 项目根目录（本文件位于 backend/app/config.py，向上两层即为项目根）
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))

# 前端目录
FRONTEND_DIR = os.path.join(PROJECT_ROOT, 'frontend')

# 数据目录
DATA_DIR = os.path.join(PROJECT_ROOT, 'backend', 'data')

# 日志目录
LOG_DIR = os.path.join(DATA_DIR, 'logs')

# 确保日志目录存在
if not os.path.exists(LOG_DIR):
    os.makedirs(LOG_DIR, exist_ok=True)

# 主日志文件路径
MAIN_LOG_FILE = os.path.join(LOG_DIR, 'chrono_trace.log')

# 默认开发期本地地址（可被环境变量 DEV_URL 覆盖）
DEV_URL_DEFAULT = 'http://localhost:5173'

# 窗口标题（根据系统语言自动选择）
def _get_window_name() -> str:
    """中文系统显示「时痕」，英文系统显示「Chrono Trace」"""
    try:
        lang = locale.getdefaultlocale()[0] or ''
        if lang.startswith('zh'):
            return '时痕'
    except Exception:
        pass
    return 'Chrono Trace'

_APP_NAME = _get_window_name()
PROD_WINDOW_TITLE = _APP_NAME
DEV_WINDOW_TITLE = f'{_APP_NAME} (DEV)'


def get_dist_index_path() -> str:
    """
    返回打包后的入口 index.html 路径，没有则返回空字符串。
    """
    dist_index = os.path.join(FRONTEND_DIR, 'dist', 'index.html')
    return dist_index if os.path.exists(dist_index) else ''
