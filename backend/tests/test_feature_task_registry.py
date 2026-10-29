"""特征提取任务注册表：reanalyze 的删除窗口必须被并发守卫看见（第三轮抽查 W5）。

reanalyze 异步线程先删旧数据、任务要到 extract_features 内部才注册
_task_status——删除阶段 find_running_task 得 None，两道互斥门禁都放行，
同会话可并发第二条管线交错删写。register_task 让入口在启动线程前占位。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.analysis.feature_extraction_service import FeatureExtractionService


def _service() -> FeatureExtractionService:
    service = FeatureExtractionService.__new__(FeatureExtractionService)
    service._task_status = {}
    return service


def test_register_task_makes_running_guard_visible_immediately():
    service = _service()

    service.register_task("extract_7_100_abc")

    assert service.find_running_task(7) == "extract_7_100_abc"


def test_register_task_placeholder_superseded_by_extract_features():
    """extract_features 进场后覆盖占位（同 task_id 重注册），终态不再拦截。"""
    service = _service()
    service.register_task("extract_7_100_abc")
    service._task_status["extract_7_100_abc"] = {"status": "failed"}

    assert service.find_running_task(7) is None
    assert service.find_running_task(9) is None
