"""悬浮窗的微信窗口定位器（Linux）。

X11 + python-xlib：经 EWMH `_NET_CLIENT_LIST` 枚举客户端窗口，按
`_NET_WM_PID`（匹配微信主进程）或 `WM_CLASS` 含 wechat 定位微信主窗，
`_NET_WORKAREA` 提供工作区用于位置钳制。Wayland / 无 X 时返回 NullTracker
（悬浮窗退化为固定右侧档位，不跟随）。

坐标统一为屏幕绝对坐标（px），与 win32 路径的物理像素口径一致。
"""
from __future__ import annotations

import logging
import os
from typing import Optional, Protocol

logger = logging.getLogger(__name__)


class WechatWindowTracker(Protocol):
    def find(self) -> Optional[tuple[int, int, int, int]]:
        """返回微信窗口 (x, y, width, height)，未找到返回 None。"""

    @property
    def workarea(self) -> Optional[tuple[int, int, int, int]]:
        """返回当前工作区 (x, y, width, height)。"""


class NullTracker:
    """Wayland / 无 X11：无法定位微信窗口，悬浮窗使用固定档位。"""

    def find(self) -> Optional[tuple[int, int, int, int]]:
        return None

    @property
    def workarea(self) -> Optional[tuple[int, int, int, int]]:
        return None


class XlibTracker:
    """X11 下经 EWMH 属性定位微信主窗口。"""

    def __init__(self):
        from Xlib import X, display, Xatom  # noqa: F401

        self._X = X
        self._display = display.Display()
        self._screen = self._display.screen()
        self._root = self._screen.root

    # ---------- 内部 ----------

    def _atom(self, name: str):
        return self._display.intern_atom(name)

    def _wechat_pids(self) -> set[int]:
        try:
            from ...wechat.key_capture_linux import find_linux_wechat_pids

            return set(find_linux_wechat_pids())
        except Exception:
            return set()

    def _abs_geometry(self, window) -> Optional[tuple[int, int, int, int]]:
        """累加父链偏移得到屏幕绝对坐标（geometry 相对父窗口）。"""
        x = y = 0
        cur = window
        for _ in range(16):  # 防环
            try:
                geom = cur.get_geometry()
            except Exception:
                return None
            x += geom.x + getattr(geom, "border_width", 0)
            y += geom.y + getattr(geom, "border_width", 0)
            try:
                parent = cur.query_tree().parent
            except Exception:
                return None
            if parent is None or parent.id == self._root.id:
                return (x, y, geom.width, geom.height)
            cur = parent
        return None

    # ---------- 对外 ----------

    def find(self) -> Optional[tuple[int, int, int, int]]:
        try:
            prop = self._root.get_full_property(
                self._atom("_NET_CLIENT_LIST"), self._X.AnyPropertyType
            )
            if not prop or not prop.value:
                return None
            wechat_pids = self._wechat_pids()
            best: Optional[tuple[int, int, int, int]] = None
            for wid in prop.value:
                try:
                    window = self._display.create_resource_object("window", wid)
                except Exception:
                    continue
                # 优先 PID 匹配微信主进程；其次 WM_CLASS 含 wechat
                matched = False
                if wechat_pids:
                    try:
                        pid_prop = window.get_full_property(
                            self._atom("_NET_WM_PID"), self._X.AnyPropertyType
                        )
                        if pid_prop and pid_prop.value and int(pid_prop.value[0]) in wechat_pids:
                            matched = True
                    except Exception:
                        pass
                if not matched:
                    try:
                        wm_class = window.get_wm_class()
                        if wm_class and any("wechat" in str(part).lower() for part in wm_class):
                            matched = True
                    except Exception:
                        pass
                if not matched:
                    continue
                geom = self._abs_geometry(window)
                if geom is None:
                    continue
                # 取面积最大的匹配窗口（主窗；工具窗/看图窗可能更小）
                if best is None or geom[2] * geom[3] > best[2] * best[3]:
                    best = geom
            return best
        except Exception as exc:
            logger.debug("[悬浮窗跟踪] X11 定位失败: %s", exc)
            return None

    @property
    def workarea(self) -> Optional[tuple[int, int, int, int]]:
        try:
            prop = self._root.get_full_property(
                self._atom("_NET_WORKAREA"), self._X.AnyPropertyType
            )
            if prop and len(prop.value) >= 4:
                return tuple(int(v) for v in prop.value[:4])
        except Exception:
            pass
        return None


def create_tracker():
    """按显示服务器选择 tracker：X11 优先，Wayland/无显示降级 NullTracker。"""
    if os.environ.get("XDG_SESSION_TYPE", "").lower() == "wayland" and not os.environ.get("DISPLAY"):
        return NullTracker()
    try:
        return XlibTracker()
    except Exception as exc:
        logger.info("[悬浮窗跟踪] X11 不可用（%s），悬浮窗将使用固定档位", exc)
        return NullTracker()
