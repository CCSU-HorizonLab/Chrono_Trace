"""主窗口无框 chrome：拖拽 / 边缘缩放 / 最大化 / 最小化的平台实现。

配合 create_window(frameless=True) 使用，前端自绘标题栏（App.vue 顶栏）经
Bridge 调入。平台分派收敛点（同 floating_tracker 模式），业务侧勿再写
sys.platform 分支：

- Linux（Qt）：QWindow.startSystemMove/startSystemResize，WM 接管拖拽，
  X11 / Wayland 通用；经跨线程 signal（队列连接）投递到 GUI 线程执行
  （pywebview 桥调用在独立线程，不能直接动窗口）。
- Windows（EdgeChromium/WinForms）：WM_NCLBUTTONDOWN + HTCAPTION/HT*
  原生标题栏语义（与悬浮窗 floating_window_service.start_drag 同链路）。

最大化/最小化走 pywebview Window 公开 API（window.maximize/restore/minimize），
两平台一致，最大化状态由前端自持（后端无状态）。
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# GUI 线程投递器单例（桥调用线程 → GUI 线程；signal 跨线程自动队列连接）
_state: dict = {}


def _gui_dispatch(fn) -> None:
    """把 callable 投递到 GUI 线程执行。

    pywebview 的 js_api 调用跑在独立线程（util.js_bridge_call），
    Qt 窗口操作必须回到 GUI 线程；Dispatcher 亲和 QApplication 线程，
    桥线程 emit 后经队列连接在 GUI 线程执行。
    """
    from qtpy.QtCore import QCoreApplication, QObject, Signal

    d = _state.get('dispatcher')
    if d is None:
        class _Dispatcher(QObject):
            call = Signal(object)

            def run(self, fn):
                fn()

        d = _Dispatcher()
        app = QCoreApplication.instance()
        if app is not None:
            d.moveToThread(app.thread())
        d.call.connect(d.run)
        _state['dispatcher'] = d
    d.call.emit(fn)


def _qt_view(window):
    """取 pywebview Qt 后端的 BrowserView（QMainWindow），失败返回 None。"""
    try:
        from webview.platforms.qt import BrowserView

        return BrowserView.instances.get(window.uid)
    except Exception:
        return None


def _win_hwnd(window):
    """按窗口标题找 Win32 HWND（与悬浮窗 _get_webview_hwnd 同法）。"""
    try:
        import win32gui

        title = getattr(window, 'title', None)
        return win32gui.FindWindow(None, title) if title else 0
    except Exception:
        return 0


def start_drag(window) -> dict:
    """从当前鼠标按下位置启动系统级窗口拖动。"""
    if window is None:
        return {'ok': False, 'error': '窗口未就绪'}
    try:
        import sys

        if sys.platform == 'win32':
            import win32con
            import win32gui

            hwnd = _win_hwnd(window)
            if not hwnd:
                return {'ok': False, 'error': '无法获取窗口句柄'}
            win32gui.ReleaseCapture()
            win32gui.SendMessage(hwnd, win32con.WM_NCLBUTTONDOWN, win32con.HTCAPTION, 0)
            return {'ok': True}

        view = _qt_view(window)
        if view is None:
            return {'ok': False, 'error': 'Qt 视图未就绪'}

        def _do_move(v=view):
            handle = v.windowHandle()
            if handle is not None:
                handle.startSystemMove()

        _gui_dispatch(_do_move)
        return {'ok': True}
    except Exception as e:
        logger.warning('[WindowChrome] 启动拖动失败: %s', e)
        return {'ok': False, 'error': str(e)}


def start_resize(window, edge: str) -> dict:
    """从当前鼠标按下位置启动系统级边缘缩放。edge: n/s/e/w（可组合，如 ne）。"""
    if window is None:
        return {'ok': False, 'error': '窗口未就绪'}
    edge = ''.join(sorted(str(edge or '').lower()))
    if not edge or not set(edge) <= set('nswe'):
        return {'ok': False, 'error': f'非法边缘: {edge}'}
    try:
        import sys

        if sys.platform == 'win32':
            import win32con
            import win32gui

            hit = {'n': win32con.HTTOP, 's': win32con.HTBOTTOM,
                   'e': win32con.HTRIGHT, 'w': win32con.HTLEFT,
                   'ns': win32con.HTTOP, 'se': win32con.HTBOTTOMRIGHT,
                   'sw': win32con.HTBOTTOMLEFT, 'ne': win32con.HTTOPRIGHT,
                   'nw': win32con.HTTOPLEFT}.get(edge)
            if hit is None:
                return {'ok': False, 'error': f'非法边缘: {edge}'}
            hwnd = _win_hwnd(window)
            if not hwnd:
                return {'ok': False, 'error': '无法获取窗口句柄'}
            win32gui.ReleaseCapture()
            win32gui.SendMessage(hwnd, win32con.WM_NCLBUTTONDOWN, hit, 0)
            return {'ok': True}

        view = _qt_view(window)
        if view is None:
            return {'ok': False, 'error': 'Qt 视图未就绪'}
        from qtpy.QtCore import Qt

        flags = {
            'n': Qt.Edge.TopEdge, 's': Qt.Edge.BottomEdge,
            'e': Qt.Edge.RightEdge, 'w': Qt.Edge.LeftEdge,
        }
        edges = Qt.Edge(0)
        for ch in edge:
            edges |= flags[ch]

        def _do_resize(v=view, e=edges):
            handle = v.windowHandle()
            if handle is not None:
                handle.startSystemResize(e)

        _gui_dispatch(_do_resize)
        return {'ok': True}
    except Exception as e:
        logger.warning('[WindowChrome] 启动缩放失败: %s', e)
        return {'ok': False, 'error': str(e)}


def set_maximized(window, maximized: bool) -> dict:
    """切换最大化/还原（状态由前端自持，此处只执行动作）。"""
    if window is None:
        return {'ok': False, 'error': '窗口未就绪'}
    try:
        if maximized:
            window.maximize()
        else:
            window.restore()
        return {'ok': True, 'maximized': bool(maximized)}
    except Exception as e:
        logger.warning('[WindowChrome] 切换最大化失败: %s', e)
        return {'ok': False, 'error': str(e)}


def minimize(window) -> dict:
    """最小化到任务栏。"""
    if window is None:
        return {'ok': False, 'error': '窗口未就绪'}
    try:
        window.minimize()
        return {'ok': True}
    except Exception as e:
        logger.warning('[WindowChrome] 最小化失败: %s', e)
        return {'ok': False, 'error': str(e)}
