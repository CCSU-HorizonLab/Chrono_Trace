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

    with patch.object(prod_app, "Bridge", return_value=fake_bridge), \
            patch.object(prod_app, "get_dist_index_path", return_value="file:///frontend/webdist/index.html"), \
            patch.object(prod_app.webview, "create_window", return_value=fake_window) as create_window, \
            patch.object(prod_app.webview, "start") as start:
        prod_app.main()

    create_window.assert_called_once()
    start.assert_called_once()

    on_started = start.call_args.kwargs["func"]
    on_started()

    fake_bridge.set_webview_window.assert_called_once_with(fake_window)
