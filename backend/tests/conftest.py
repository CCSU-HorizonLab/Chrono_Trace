"""pytest 共享配置：统一导入根，兼容 `from app...` 与 `from backend.app...` 两种约定。

新测试请统一使用 `from app...`（以 backend/ 为导入根）。
"""
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]   # 仓库根
_BACKEND_ROOT = Path(__file__).resolve().parents[1]  # backend/

for _path in (str(_BACKEND_ROOT), str(_REPO_ROOT)):
    if _path not in sys.path:
        sys.path.insert(0, _path)


@pytest.fixture(autouse=True)
def _reset_rag_caches():
    """RAG 进程级缓存测试隔离：每个用例后清向量缓存与设置文件缓存。

    生产失效由显式钩子（重建/回填/清空/纠错）+ 数据版本戳保证；
    测试中同构不同值的夹具（pickle 浮点定长，长度戳无法区分）需强制清。
    """
    yield
    try:
        from app.services.realtime.rag.retriever import invalidate_vector_cache
        invalidate_vector_cache()
        from app.services.realtime.rag import config as rag_config
        rag_config._settings_file_cache["key"] = None
        rag_config._settings_file_cache["payload"] = None
    except Exception:
        pass
    # 清队列残留：前序用例入队的任务会由活 worker 持 _REBUILD_LOCK 处理，
    # 后续用例的直接 rebuild 调用撞锁只得 pending（rag_v1 顺序失败根因）
    try:
        from app.services.realtime.rag.indexer import RagIndexQueue

        with RagIndexQueue._lock:
            RagIndexQueue._pending.clear()
            RagIndexQueue._pending_order.clear()
            RagIndexQueue._fact_pending.clear()
            RagIndexQueue._fact_order.clear()
    except Exception:
        pass
