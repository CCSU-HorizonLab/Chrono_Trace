"""
悬浮窗管理服务
负责 Win32 窗口跟踪和 PyWebView 窗口尺寸/位置管理。
当用户启动监听时，将主窗口变形为右侧悬浮面板，跟随微信窗口移动。
"""

import threading
import time
import logging

logger = logging.getLogger(__name__)

# 悬浮窗默认参数
FLOATING_WIDTH = 520           # 加宽以展示建议内容
FLOATING_MIN_HEIGHT = 700
TRACKING_INTERVAL_MS = 300     # 缩短到 300ms 让跟随更流畅
WECHAT_WINDOW_CLASS = 'WeChatMainWndForPC'
FLOATING_GAP = 6               # 悬浮窗与微信窗口之间的间距（像素）


def _log(msg: str):
    """同时输出到 logger 和 stdout（确保开发模式可见）"""
    logger.debug(f"[FloatingWindow] {msg}")
    logger.info(msg)


class FloatingWindowService:
    """
    管理 PyWebView 窗口在"全屏应用模式"和"悬浮面板模式"之间的切换，
    并在悬浮模式下持续跟踪微信窗口位置。
    """

    def __init__(self):
        self._webview_window = None
        self._is_floating = False
        self._original_rect = None  # (x, y, width, height)
        self._tracking_thread = None
        self._stop_tracking = threading.Event()
        self._wechat_hwnd = None
        self._webview_hwnd = None    # 缓存 PyWebView 的 HWND

    def set_webview_window(self, window):
        """设置 PyWebView 窗口引用"""
        self._webview_window = window
        # 提前缓存 HWND
        self._webview_hwnd = self._get_webview_hwnd()
        _log(f"窗口引用已设置, HWND={self._webview_hwnd}")

    @property
    def is_floating(self) -> bool:
        return self._is_floating

    def enter_floating_mode(self) -> dict:
        """
        进入悬浮窗模式：
        1. 保存当前窗口位置/尺寸
        2. 调整窗口为紧凑尺寸
        3. 设置置顶
        4. 启动微信窗口跟踪线程
        """
        if self._is_floating:
            return {'ok': True, 'message': '已在悬浮模式'}

        if not self._webview_window:
            return {'ok': False, 'error': 'PyWebView 窗口引用未设置'}

        try:
            # 确保有 HWND
            if not self._webview_hwnd:
                self._webview_hwnd = self._get_webview_hwnd()
            _log(f"进入悬浮模式, webview_hwnd={self._webview_hwnd}")

            # 保存原始窗口状态
            self._save_original_rect()

            # 查找微信窗口并定位
            wechat_rect = self._find_wechat_window()

            if wechat_rect:
                # 微信窗口右侧定位，高度对齐微信窗口
                x = wechat_rect[2] + FLOATING_GAP  # right + gap
                y = wechat_rect[1]                   # top 对齐
                height = max(wechat_rect[3] - wechat_rect[1], FLOATING_MIN_HEIGHT)
                _log(f"微信窗口位置: left={wechat_rect[0]}, top={wechat_rect[1]}, "
                     f"right={wechat_rect[2]}, bottom={wechat_rect[3]}")
            else:
                # 未找到微信窗口，居屏幕右侧
                x, y, height = self._fallback_position()
                _log(f"未找到微信窗口，使用回退位置: x={x}, y={y}, h={height}")

            # 使用 Win32 API 直接移动和调整窗口（更可靠）
            moved = self._win32_move_resize(x, y, FLOATING_WIDTH, height)
            if not moved:
                # 回退到 PyWebView API
                _log("Win32 移动失败，回退到 PyWebView API")
                self._webview_window.resize(FLOATING_WIDTH, height)
                self._webview_window.move(x, y)

            # 设置置顶
            self._set_on_top(True)

            self._is_floating = True

            # 启动跟踪线程
            self._start_tracking()

            _log(f'✅ 已进入悬浮模式: x={x}, y={y}, w={FLOATING_WIDTH}, h={height}')
            return {
                'ok': True,
                'message': '已进入悬浮模式',
                'wechat_found': wechat_rect is not None
            }

        except Exception as e:
            _log(f'❌ 进入悬浮模式失败: {e}')
            import traceback
            traceback.print_exc()
            return {'ok': False, 'error': str(e)}

    def exit_floating_mode(self) -> dict:
        """
        退出悬浮窗模式：
        1. 停止跟踪线程
        2. 取消置顶
        3. 恢复原始窗口尺寸
        """
        if not self._is_floating:
            return {'ok': True, 'message': '未在悬浮模式'}

        try:
            # 停止跟踪
            self._stop_tracking_thread()

            # 取消置顶
            self._set_on_top(False)

            # 恢复原始窗口尺寸
            if self._original_rect:
                x, y, w, h = self._original_rect
                moved = self._win32_move_resize(x, y, w, h)
                if not moved:
                    self._webview_window.resize(w, h)
                    self._webview_window.move(x, y)
                _log(f'恢复窗口: x={x}, y={y}, w={w}, h={h}')

            self._is_floating = False
            return {'ok': True, 'message': '已退出悬浮模式'}

        except Exception as e:
            _log(f'❌ 退出悬浮模式失败: {e}')
            import traceback
            traceback.print_exc()
            return {'ok': False, 'error': str(e)}

    def get_status(self) -> dict:
        """获取悬浮窗状态"""
        return {
            'ok': True,
            'is_floating': self._is_floating,
            'wechat_found': self._wechat_hwnd is not None,
            'original_rect': self._original_rect,
        }

    # ==================== Win32 直接操作 ====================

    def _win32_move_resize(self, x: int, y: int, w: int, h: int) -> bool:
        """使用 Win32 API 直接移动和调整窗口大小（比 PyWebView API 更可靠）"""
        try:
            import win32gui
            import win32con

            hwnd = self._webview_hwnd or self._get_webview_hwnd()
            if not hwnd:
                _log("无法获取 HWND，跳过 Win32 移动")
                return False

            # SWP_NOZORDER: 不改变 Z 序（置顶由 _set_on_top 单独处理）
            win32gui.SetWindowPos(
                hwnd, 0, x, y, w, h,
                win32con.SWP_NOZORDER | win32con.SWP_NOACTIVATE
            )
            return True
        except Exception as e:
            _log(f"Win32 移动窗口失败: {e}")
            return False

    # ==================== 内部方法 ====================

    def _save_original_rect(self):
        """保存当前窗口的位置和尺寸"""
        try:
            import win32gui
            hwnd = self._webview_hwnd or self._get_webview_hwnd()
            if hwnd:
                rect = win32gui.GetWindowRect(hwnd)
                self._original_rect = (
                    rect[0],  # x
                    rect[1],  # y
                    rect[2] - rect[0],  # width
                    rect[3] - rect[1],  # height
                )
                _log(f'保存原始窗口: {self._original_rect}')
            else:
                self._original_rect = (100, 100, 1200, 800)
        except Exception as e:
            _log(f'保存窗口位置失败，使用默认值: {e}')
            self._original_rect = (100, 100, 1200, 800)

    def _get_webview_hwnd(self):
        """获取 PyWebView 窗口的 Win32 HWND"""
        try:
            import win32gui

            # 方法1：通过 PyWebView 窗口的精确标题查找
            title = getattr(self._webview_window, 'title', None)
            if title:
                hwnd = win32gui.FindWindow(None, title)
                if hwnd:
                    _log(f"通过精确标题 '{title}' 找到 HWND: {hwnd}")
                    return hwnd

            # 方法2：遍历顶层窗口，用 PyWebView 的窗口类名排除 IDE
            # PyWebView (EdgeChromium) 使用的窗口类通常不是
            # "Chrome_WidgetWin_1"(那是 IDE/浏览器)
            result = []

            def enum_callback(hwnd, _):
                if not win32gui.IsWindowVisible(hwnd):
                    return
                win_title = win32gui.GetWindowText(hwnd)
                cls_name = win32gui.GetClassName(hwnd)

                # 精确匹配 PyWebView 窗口标题（不是子串匹配！）
                # 标题可能是 "时痕 (DEV)" 或 "Chrono Trace (DEV)"
                if win_title and (win_title.startswith('时痕') or win_title.startswith('Chrono Trace')):
                    # 排除明显不是 PyWebView 的窗口类
                    # IDE/编辑器的窗口类通常是 Chrome_WidgetWin_1, Electron 等
                    excluded_classes = {
                        'Chrome_WidgetWin_1',  # VS Code / Cursor / Chrome
                        'Electron',
                        'ConsoleWindowClass',  # 终端
                        'CabinetWClass',       # 文件管理器
                    }
                    if cls_name not in excluded_classes:
                        _log(f"候选窗口: title='{win_title}', class='{cls_name}', hwnd={hwnd}")
                        result.append(hwnd)

            win32gui.EnumWindows(enum_callback, None)
            if result:
                _log(f"通过枚举找到 PyWebView HWND: {result[0]}")
                return result[0]

            _log("⚠ 未找到 PyWebView 窗口 HWND")
            return None

        except Exception as e:
            _log(f'获取 HWND 失败: {e}')
            return None

    def _find_wechat_window(self):
        """查找微信主窗口的 rect (left, top, right, bottom)"""
        try:
            import win32gui

            # 方法1：通过类名查找
            hwnd = win32gui.FindWindow(WECHAT_WINDOW_CLASS, None)
            if hwnd and win32gui.IsWindowVisible(hwnd):
                self._wechat_hwnd = hwnd
                rect = win32gui.GetWindowRect(hwnd)
                _log(f'通过类名找到微信窗口: hwnd={hwnd}, rect={rect}')
                return rect

            # 方法2：通过标题查找（兼容不同版本微信）
            result = []

            def enum_callback(hwnd, _):
                if win32gui.IsWindowVisible(hwnd):
                    win_title = win32gui.GetWindowText(hwnd)
                    cls_name = win32gui.GetClassName(hwnd)
                    if win_title == '微信' or cls_name == WECHAT_WINDOW_CLASS:
                        result.append(hwnd)

            win32gui.EnumWindows(enum_callback, None)
            if result:
                self._wechat_hwnd = result[0]
                rect = win32gui.GetWindowRect(result[0])
                _log(f'通过枚举找到微信窗口: hwnd={result[0]}, rect={rect}')
                return rect

            self._wechat_hwnd = None
            _log('⚠ 未找到微信窗口')
            return None

        except Exception as e:
            _log(f'查找微信窗口失败: {e}')
            self._wechat_hwnd = None
            return None

    def _fallback_position(self):
        """未找到微信窗口时的回退定位（屏幕右侧）"""
        try:
            import win32api
            screen_w = win32api.GetSystemMetrics(0)
            screen_h = win32api.GetSystemMetrics(1)
            x = screen_w - FLOATING_WIDTH - 20
            y = 40
            height = screen_h - 100
            return x, y, height
        except Exception:
            return 800, 40, 700

    def _set_on_top(self, on_top: bool):
        """设置窗口置顶"""
        try:
            import win32gui
            import win32con

            hwnd = self._webview_hwnd or self._get_webview_hwnd()
            if hwnd:
                flag = win32con.HWND_TOPMOST if on_top else win32con.HWND_NOTOPMOST
                win32gui.SetWindowPos(
                    hwnd, flag, 0, 0, 0, 0,
                    win32con.SWP_NOMOVE | win32con.SWP_NOSIZE | win32con.SWP_NOACTIVATE
                )
                _log(f"置顶={'开' if on_top else '关'}")
            else:
                # 回退到 PyWebView API
                self._webview_window.on_top = on_top
        except Exception as e:
            _log(f'设置置顶失败: {e}')
            try:
                self._webview_window.on_top = on_top
            except Exception:
                pass

    def _start_tracking(self):
        """启动微信窗口位置跟踪线程"""
        self._stop_tracking.clear()
        self._tracking_thread = threading.Thread(
            target=self._tracking_loop,
            daemon=True,
            name='FloatingWindowTracker'
        )
        self._tracking_thread.start()
        _log('窗口跟踪线程已启动')

    def _stop_tracking_thread(self):
        """停止跟踪线程"""
        self._stop_tracking.set()
        if self._tracking_thread and self._tracking_thread.is_alive():
            self._tracking_thread.join(timeout=2.0)
        self._tracking_thread = None
        self._wechat_hwnd = None
        _log('窗口跟踪线程已停止')

    def _tracking_loop(self):
        """跟踪循环：每 300ms 检查微信窗口位置，必要时移动悬浮窗"""
        import win32gui
        import win32con

        interval = TRACKING_INTERVAL_MS / 1000.0
        last_rect = None
        miss_count = 0

        _log("跟踪循环开始运行")

        while not self._stop_tracking.is_set():
            try:
                # 重新查找微信窗口（以应对窗口重启等情况）
                if not self._wechat_hwnd or not win32gui.IsWindow(self._wechat_hwnd):
                    hwnd = win32gui.FindWindow(WECHAT_WINDOW_CLASS, None)
                    if not hwnd:
                        # 也通过标题查找
                        def find_wechat(h, _):
                            if win32gui.IsWindowVisible(h):
                                t = win32gui.GetWindowText(h)
                                if t == '微信':
                                    results.append(h)
                        results = []
                        win32gui.EnumWindows(find_wechat, None)
                        hwnd = results[0] if results else None

                    if hwnd and win32gui.IsWindowVisible(hwnd):
                        self._wechat_hwnd = hwnd
                        miss_count = 0
                    else:
                        miss_count += 1
                        if miss_count == 1:
                            _log("跟踪中: 微信窗口暂时不可见")
                        self._stop_tracking.wait(interval)
                        continue

                # 获取微信窗口当前位置
                rect = win32gui.GetWindowRect(self._wechat_hwnd)

                # 仅在位置/尺寸变化时移动悬浮窗
                if rect != last_rect:
                    last_rect = rect
                    x = rect[2] + FLOATING_GAP         # 微信右边缘 + 间距
                    y = rect[1]                         # 与微信顶部对齐
                    wechat_h = rect[3] - rect[1]
                    height = max(wechat_h, FLOATING_MIN_HEIGHT)

                    # 直接用 Win32 API 移动（更快、更可靠）
                    webview_hwnd = self._webview_hwnd or self._get_webview_hwnd()
                    if webview_hwnd:
                        try:
                            win32gui.SetWindowPos(
                                webview_hwnd, win32con.HWND_TOPMOST,
                                x, y, FLOATING_WIDTH, height,
                                win32con.SWP_NOACTIVATE
                            )
                        except Exception as e:
                            _log(f'移动悬浮窗失败: {e}')

            except Exception as e:
                _log(f'跟踪循环异常: {e}')

            self._stop_tracking.wait(interval)

        _log('跟踪循环退出')
