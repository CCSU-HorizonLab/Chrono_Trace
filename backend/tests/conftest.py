"""pytest 共享配置：统一导入根，兼容 `from app...` 与 `from backend.app...` 两种约定。

新测试请统一使用 `from app...`（以 backend/ 为导入根）。
"""
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]   # 仓库根
_BACKEND_ROOT = Path(__file__).resolve().parents[1]  # backend/

for _path in (str(_BACKEND_ROOT), str(_REPO_ROOT)):
    if _path not in sys.path:
        sys.path.insert(0, _path)
