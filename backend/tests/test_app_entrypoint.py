import importlib
import importlib.util
from pathlib import Path
import sys
from unittest.mock import MagicMock, patch


def test_production_entrypoint_injects_webview_window():
    app_path = Path(__file__).resolve().parents[2] / "app.py"
    sys.path.insert(0, str(app_path.parent))
    spec = importlib.util.spec_from_file_location("chrono_trace_prod_app", app_path)
    assert spec and spec.loader
    prod_app = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(prod_app)
    fake_bridge = MagicMock()
    fake_window = object()

    # app.main() 内是函数级导入，补丁须打在源模块上（打在 prod_app 上不存在该属性）
    from backend.app.webview import gui_backend

    with patch.object(prod_app, "Bridge", return_value=fake_bridge), \
            patch.object(prod_app, "get_dist_index_path", return_value="file:///frontend/webdist/index.html"), \
            patch.object(prod_app.webview, "create_window", return_value=fake_window) as create_window, \
            patch.object(prod_app.webview, "start") as start, \
            patch.object(gui_backend, "hard_exit_after_webview") as hard_exit:
        # 真实 hard_exit_after_webview 会 os._exit(0)（QtWebEngine 收尾段错误
        # 兜底），不打补丁会把 pytest 进程整个带走、静默截断后续用例
        prod_app.main()

    create_window.assert_called_once()
    start.assert_called_once()
    hard_exit.assert_called_once()  # 事件循环退出后必须走硬退出兜底

    create_window.assert_called_once()
    start.assert_called_once()

    on_started = start.call_args.kwargs["func"]
    on_started()

    fake_bridge.set_webview_window.assert_called_once_with(fake_window)
