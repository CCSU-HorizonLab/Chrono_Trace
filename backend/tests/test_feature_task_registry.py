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


def test_device_mode_failure_lands_terminal_status():
    """设备模式初始化抛错必须落 failed 终态，不得让占位任务永久 in_progress。

    _apply_analysis_device_mode 此前在 try 外执行：抛错时占位任务
    （bridge/reanalyze 的 register_task）永远停留 in_progress——该会话
    所有提取请求被守卫永久拒绝，只能重启解锁。
    """
    import pytest

    service = _service()
    service._extract_cancel_event = None

    def _boom():
        raise RuntimeError("DML session 创建失败")

    service._apply_analysis_device_mode = _boom
    service.register_task("extract_7_100_abc")

    with pytest.raises(RuntimeError):
        service.extract_features(7, task_id="extract_7_100_abc")

    assert service._task_status["extract_7_100_abc"]["status"] == "failed"


def test_bridge_extract_features_pre_registers_task():
    """主路径入口（start_feature_extraction）也必须在启动线程前占位。

    与 reanalyze 同款 W5 窗口：线程启动到 extract_features 内部注册之间
    find_running_task 仍得 None，双击入口两条管线交错删写。
    """
    from app.webview.bridge import Bridge

    registered: list[str] = []

    class _FakeService:
        config = None

        def validate(self):
            return None

        def find_running_task(self, conversation_id):
            return None

        def register_task(self, task_id, message=""):
            registered.append(task_id)

        def extract_features(self, conversation_id, cancel_event=None, task_id=None):
            return {}

    bridge = object.__new__(Bridge)
    bridge._analysis_cancel_events = {}
    bridge._get_feature_service = lambda: _FakeService()
    bridge._build_feature_config = lambda config=None: _FakeService()

    result = bridge.extract_features(7)

    assert result["success"] is True
    assert registered, "线程启动前必须完成预注册"
    assert registered[0] == result["data"]["task_id"]
