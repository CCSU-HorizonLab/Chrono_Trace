"""主窗口无框 chrome：拖拽 / 边缘缩放 / 最大化 / 最小化的平台实现。

配合 create_window(frameless=True) 使用，前端自绘标题栏（App.vue 顶栏）经
Bridge 调入。平台分派收敛点（同 floating_tracker 模式），业务侧勿再写
sys.platform 分支：

- Linux（Qt）：QWindow.startSystemMove/startSystemResize，WM 接管拖拽，
  X11 / Wayland 通用；经跨线程 signal（队列连接）投递到 GUI 线程执行
  （pywebview 桥调用在独立线程，不能直接动窗口）。
- Windows（EdgeChromium/WinForms）：WM_NCLBUTTONDOWN + HTCAPTION/HT*
  原生标题栏语义（与悬浮窗 floating_window_service.start_drag 同链路）；
  边缘缩放经 _win_start_size_loop 临时补 WS_THICKFRAME——无框窗无此样式，
  系统 SC_SIZE 循环会静默不动作（HTCAPTION 拖动不受此限制）。

最大化/最小化走 pywebview Window 公开 API（window.maximize/restore/minimize），
两平台一致；toggle 前先查实际状态（Qt windowState / Win32 IsZoomed），系统级
最大化（Win+Up、WM 快捷键）不经前端也能自愈。
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


def _gui_call(fn, timeout: float = 2.0):
    """投递到 GUI 线程执行并同步等回返回值（超时返回 None）。"""
    import threading

    box = {}
    done = threading.Event()

    def _wrap():
        box['r'] = fn()
        done.set()

    _gui_dispatch(_wrap)
    done.wait(timeout)
    return box.get('r')


def _qt_view(window):
    """取 pywebview Qt 后端的 BrowserView（QMainWindow），失败返回 None。"""
    try:
        from webview.platforms.qt import BrowserView

        return BrowserView.instances.get(window.uid)
    except Exception:
        return None


def _win_hwnd(window):
    """枚举本进程的顶层窗口按标题取 HWND（多实例下 FindWindow 会命中别的实例）。"""
    try:
        import os

        import win32gui
        import win32process

        title = getattr(window, 'title', None)
        if not title:
            return 0
        found = []

        def _cb(hwnd, _):
            if win32gui.GetWindowText(hwnd) == title:
                # GetWindowThreadProcessId 在 win32process（win32gui 无此属性，
                # 误用会被 except 吞成句柄 0，拖动/缩放/最大化整体静默失效）
                _tid, pid = win32process.GetWindowThreadProcessId(hwnd)
                if pid == os.getpid():
                    found.append(hwnd)
            return True

        win32gui.EnumWindows(_cb, None)
        if not found:
            logger.warning(
                '[WindowChrome] 未找到标题为 %r 的本进程窗口，拖动/缩放/最大化不可用', title
            )
        return found[0] if found else 0
    except Exception:
        logger.warning('[WindowChrome] 枚举窗口句柄失败', exc_info=True)
        return 0


def start_drag(window) -> dict:
    """启动窗口拖动：Linux 走系统原生循环；Windows 由前端驱动逐帧调 move_to。

    Windows 主窗口是 WinForms 无框窗，实测 DefWndProc 的 NC 模态循环
    （HTCAPTION 移动 / HT* 缩放）在其上均不动作——此前「页面拖动能移窗」
    实为 pywebview easy_drag（页面级 JS 移窗）在干活，easy_drag 关闭后即
    现形。悬浮窗不受影响（服务自建纯 win32 窗口，NC 循环正常）。改为
    返回当前矩形与 DPI 缩放，前端 mousemove 逐帧调 move_to。
    """
    if window is None:
        return {'ok': False, 'error': '窗口未就绪'}
    try:
        import sys

        if sys.platform == 'win32':
            import win32gui

            hwnd = _win_hwnd(window)
            if not hwnd:
                return {'ok': False, 'error': '无法获取窗口句柄'}
            l, t, r, b = win32gui.GetWindowRect(hwnd)
            return {
                'ok': True,
                'native': False,          # 前端据此后接 mousemove 手动移窗
                'rect': [l, t, r, b],     # 物理像素，屏幕坐标
                'scale': _win_dpi_scale(hwnd),
            }

        view = _qt_view(window)
        if view is None:
            return {'ok': False, 'error': 'Qt 视图未就绪'}

        def _do_move(v=view):
            handle = v.windowHandle()
            if handle is not None:
                handle.startSystemMove()

        _gui_dispatch(_do_move)
        return {'ok': True, 'native': True}
    except Exception as e:
        logger.warning('[WindowChrome] 启动拖动失败: %s', e)
        return {'ok': False, 'error': str(e)}


def move_to(window, x: int, y: int) -> dict:
    """Windows 手动移窗落点（物理像素屏幕坐标）。"""
    if window is None:
        return {'ok': False, 'error': '窗口未就绪'}
    try:
        import sys

        if sys.platform != 'win32':
            return {'ok': False, 'error': '仅 Windows 使用手动移窗'}

        import win32con
        import win32gui

        hwnd = _win_hwnd(window)
        if not hwnd:
            return {'ok': False, 'error': '无法获取窗口句柄'}
        win32gui.SetWindowPos(
            hwnd, 0, int(x), int(y), 0, 0,
            win32con.SWP_NOSIZE | win32con.SWP_NOZORDER | win32con.SWP_NOACTIVATE,
        )
        return {'ok': True}
    except Exception as e:
        logger.warning('[WindowChrome] 手动移窗失败: %s', e)
        return {'ok': False, 'error': str(e)}


def _win_dpi_scale(hwnd: int) -> float:
    """窗口 DPI 缩放（物理/逻辑像素比）；取不到按 100%。"""
    import ctypes

    try:
        dpi = ctypes.windll.user32.GetDpiForWindow(hwnd)
        if dpi > 0:
            return dpi / 96.0
    except Exception:
        pass
    return 1.0


def start_resize(window, edge: str) -> dict:
    """启动边缘缩放：Linux 走系统原生循环；Windows 由前端驱动逐帧调 resize_to。

    Windows 不再用 WM_NCLBUTTONDOWN+HT* 的 NC 缩放循环——在 WinForms 无框
    窗上不可靠（实测：常驻 WS_THICKFRAME 后循环可用，但客户区四边内缩
    ~7px 破坏全出血 UI；临时补样式再还原则循环运行却不动尺寸）。改为
    返回当前矩形与 DPI 缩放，前端在 mousemove 里按锚定对边算目标矩形、
    逐帧调 resize_to——与 easy_drag 移动窗体同款链路，已验证可用。

    edge: n/s/e/w（可组合，如 ne）。
    """
    if window is None:
        return {'ok': False, 'error': '窗口未就绪'}
    edge = ''.join(sorted(str(edge or '').lower()))
    if not edge or not set(edge) <= set('nswe'):
        return {'ok': False, 'error': f'非法边缘: {edge}'}
    try:
        import sys

        if sys.platform == 'win32':
            import win32gui

            hwnd = _win_hwnd(window)
            if not hwnd:
                return {'ok': False, 'error': '无法获取窗口句柄'}
            l, t, r, b = win32gui.GetWindowRect(hwnd)
            return {
                'ok': True,
                'native': False,          # 前端据此后接 mousemove 手动缩放
                'rect': [l, t, r, b],     # 物理像素，屏幕坐标
                'scale': _win_dpi_scale(hwnd),
            }

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
        return {'ok': True, 'native': True}
    except Exception as e:
        logger.warning('[WindowChrome] 启动缩放失败: %s', e)
        return {'ok': False, 'error': str(e)}


def resize_to(window, x: int, y: int, width: int, height: int, anchor: str = 'nw') -> dict:
    """Windows 手动缩放落点：按锚定角钳制最小尺寸后 SetWindowPos。

    anchor 为保持不动的角（nw/ne/sw/se）——缩到最小尺寸时由后端按锚点
    回推 x/y，前端无需感知钳制。参数均为物理像素屏幕坐标。
    """
    if window is None:
        return {'ok': False, 'error': '窗口未就绪'}
    try:
        import sys

        if sys.platform != 'win32':
            return {'ok': False, 'error': '仅 Windows 使用手动缩放'}

        import win32con
        import win32gui

        anchor = ''.join(sorted(str(anchor or 'nw').lower()))
        if not anchor or not set(anchor) <= set('nswe'):
            anchor = 'nw'

        hwnd = _win_hwnd(window)
        if not hwnd:
            return {'ok': False, 'error': '无法获取窗口句柄'}
        scale = _win_dpi_scale(hwnd)
        l, t, r, b = win32gui.GetWindowRect(hwnd)

        min_w, min_h = getattr(window, 'min_size', None) or (200, 200)
        width = max(int(width), int(min_w * scale))
        height = max(int(height), int(min_h * scale))
        x, y = int(x), int(y)
        # 锚定角回推：拖 w/n 边时对面对角不动
        if 'e' in anchor:
            x = r - width
        if 's' in anchor:
            y = b - height

        win32gui.SetWindowPos(
            hwnd, 0, x, y, width, height,
            win32con.SWP_NOZORDER | win32con.SWP_NOACTIVATE,
        )
        return {'ok': True}
    except Exception as e:
        logger.warning('[WindowChrome] 手动缩放失败: %s', e)
        return {'ok': False, 'error': str(e)}


def toggle_maximized(window) -> dict:
    """查询实际最大化状态并取反（自愈系统级最大化：Win+Up / WM 快捷键不经过前端）。"""
    if window is None:
        return {'ok': False, 'error': '窗口未就绪'}
    try:
        import sys

        current = False
        if sys.platform == 'win32':
            import ctypes

            hwnd = _win_hwnd(window)
            if not hwnd:
                return {'ok': False, 'error': '无法获取窗口句柄'}
            # IsZoomed 不在 pywin32 导出面（实测 312 无此属性），走 ctypes 直调
            current = bool(ctypes.windll.user32.IsZoomed(hwnd))
        else:
            view = _qt_view(window)
            if view is None:
                return {'ok': False, 'error': 'Qt 视图未就绪'}
            from qtpy.QtCore import Qt

            def _peek(v=view):
                return bool(v.windowState() & Qt.WindowState.WindowMaximized)

            current = bool(_gui_call(_peek))

        target = not current
        if target:
            window.maximize()
        else:
            window.restore()
        return {'ok': True, 'maximized': target}
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
