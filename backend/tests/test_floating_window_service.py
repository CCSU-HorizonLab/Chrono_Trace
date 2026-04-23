import io
import logging
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock


backend_root = Path(__file__).parent.parent
sys.path.insert(0, str(backend_root))


from app.services.realtime import floating_window_service
from app.services.realtime.floating_window_service import FloatingWindowService


class _AsciiStdout(io.StringIO):
    encoding = "gbk"

    def write(self, s):
        str(s).encode(self.encoding)
        return super().write(s)


def test_log_falls_back_when_stdout_cannot_encode_unicode(monkeypatch):
    stream = _AsciiStdout()
    records: list[str] = []

    class _Handler(logging.Handler):
        def emit(self, record):
            records.append(record.getMessage())

    handler = _Handler()
    floating_window_service.logger.addHandler(handler)
    floating_window_service.logger.setLevel(logging.INFO)
    try:
        monkeypatch.setattr(floating_window_service.sys, "stdout", stream)
        floating_window_service._log("✅ 测试")
    finally:
        floating_window_service.logger.removeHandler(handler)

    assert "[FloatingWindow]" in stream.getvalue()
    assert "?" in stream.getvalue()
    assert records[-1] == "✅ 测试"


def test_set_window_decorations_toggles_style_bits(monkeypatch):
    service = FloatingWindowService()
    service._webview_hwnd = 1001

    fake_win32con = types.SimpleNamespace(
        GWL_STYLE=-16,
        GWL_EXSTYLE=-20,
        WS_CAPTION=0x00C00000,
        WS_THICKFRAME=0x00040000,
        WS_MINIMIZEBOX=0x00020000,
        WS_MAXIMIZEBOX=0x00010000,
        WS_SYSMENU=0x00080000,
        WS_EX_DLGMODALFRAME=0x00000001,
        WS_EX_CLIENTEDGE=0x00000200,
        WS_EX_STATICEDGE=0x00020000,
        SWP_FRAMECHANGED=0x0020,
        SWP_NOMOVE=0x0002,
        SWP_NOSIZE=0x0001,
        SWP_NOZORDER=0x0004,
        SWP_NOACTIVATE=0x0010,
    )

    style_state = {
        "style": (
            fake_win32con.WS_CAPTION
            | fake_win32con.WS_THICKFRAME
            | fake_win32con.WS_MINIMIZEBOX
            | fake_win32con.WS_MAXIMIZEBOX
            | fake_win32con.WS_SYSMENU
            | 0x10
        ),
        "ex_style": (
            fake_win32con.WS_EX_DLGMODALFRAME
            | fake_win32con.WS_EX_CLIENTEDGE
            | fake_win32con.WS_EX_STATICEDGE
            | 0x20
        ),
    }
    frame_change_calls = []

    def get_window_long(_hwnd, index):
        if index == fake_win32con.GWL_STYLE:
            return style_state["style"]
        if index == fake_win32con.GWL_EXSTYLE:
            return style_state["ex_style"]
        raise AssertionError(f"unexpected index: {index}")

    def set_window_long(_hwnd, index, value):
        if index == fake_win32con.GWL_STYLE:
            style_state["style"] = value
        elif index == fake_win32con.GWL_EXSTYLE:
            style_state["ex_style"] = value
        else:
            raise AssertionError(f"unexpected index: {index}")

    def set_window_pos(hwnd, insert_after, x, y, w, h, flags):
        frame_change_calls.append((hwnd, insert_after, x, y, w, h, flags))

    fake_win32gui = types.SimpleNamespace(
        GetWindowLong=get_window_long,
        SetWindowLong=set_window_long,
        SetWindowPos=set_window_pos,
    )

    monkeypatch.setitem(sys.modules, "win32gui", fake_win32gui)
    monkeypatch.setitem(sys.modules, "win32con", fake_win32con)

    original_style = style_state["style"]
    original_ex_style = style_state["ex_style"]

    assert service._set_window_decorations(False) is True
    assert style_state["style"] & fake_win32con.WS_CAPTION == 0
    assert style_state["style"] & fake_win32con.WS_THICKFRAME == 0
    assert style_state["style"] & fake_win32con.WS_MINIMIZEBOX == 0
    assert style_state["style"] & fake_win32con.WS_MAXIMIZEBOX == 0
    assert style_state["style"] & fake_win32con.WS_SYSMENU == 0
    assert style_state["ex_style"] & fake_win32con.WS_EX_CLIENTEDGE == 0
    assert len(frame_change_calls) == 1

    assert service._set_window_decorations(True) is True
    assert style_state["style"] == original_style
    assert style_state["ex_style"] == original_ex_style
    assert len(frame_change_calls) == 2


def test_enter_and_exit_floating_mode_toggle_window_decorations():
    service = FloatingWindowService()
    service._webview_window = MagicMock()
    service._webview_hwnd = 1001

    service._save_original_rect = MagicMock(side_effect=lambda: setattr(service, "_original_rect", (10, 20, 30, 40)))
    service._find_wechat_window = MagicMock(return_value=None)
    service._fallback_position = MagicMock(return_value=(100, 200, 700))
    service._win32_move_resize = MagicMock(return_value=True)
    service._set_on_top = MagicMock()
    service._start_tracking = MagicMock()
    service._stop_tracking_thread = MagicMock()
    service._restore_physical_rect = MagicMock(return_value=True)

    decoration_events = []

    def toggle(decorated: bool):
        decoration_events.append(decorated)
        return True

    service._set_window_decorations = MagicMock(side_effect=toggle)

    enter_result = service.enter_floating_mode()
    assert enter_result["ok"] is True
    assert decoration_events == [False]

    exit_result = service.exit_floating_mode()
    assert exit_result["ok"] is True
    assert decoration_events == [False, True]
