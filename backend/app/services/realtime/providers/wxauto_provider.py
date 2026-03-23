"""wxauto4 compatibility provider used as a temporary fallback."""

from __future__ import annotations

import logging
import multiprocessing
import queue
import time

from .base import ProviderInitError, RealtimeProvider
from .models import RealtimeMessage

logger = logging.getLogger(__name__)


def _chatwith_worker(target_name: str, result_queue):
    """Run wxauto4.ChatWith in a separate process so timeouts stay killable."""
    started_at = time.time()
    try:
        from wxauto4 import WeChat

        wx = WeChat(start_listener=False)
        wx.ChatWith(target_name)
        result_queue.put(
            {
                "ok": True,
                "error": "",
                "elapsed": time.time() - started_at,
            }
        )
    except Exception as exc:
        result_queue.put(
            {
                "ok": False,
                "error": str(exc),
                "elapsed": time.time() - started_at,
            }
        )


class WxautoRealtimeProvider(RealtimeProvider):
    """Adapter that normalizes wxauto4 into the provider interface."""

    backend_name = "wxauto"

    def __init__(self):
        super().__init__()
        self.wx = None
        self.listener_profile = "wxauto4"

    def initialize(self) -> None:
        try:
            from wxauto4 import WeChat
        except Exception as exc:
            raise ProviderInitError(f"wxauto4 unavailable: {exc}") from exc

        self.close()
        self.wx = WeChat(start_listener=False)
        self.account_name = getattr(self.wx, "nickname", "") or ""

    def activate_main_window(self) -> bool:
        return bool(self.get_hwnd())

    def open_chat(self, display_name: str) -> bool:
        if self.wx is None:
            self.initialize()

        self.current_display_name = display_name
        ctx = multiprocessing.get_context("spawn")
        result_queue = ctx.Queue()
        chat_process = ctx.Process(
            target=_chatwith_worker,
            args=(display_name, result_queue),
            daemon=True,
        )
        chat_process.start()
        chat_process.join(timeout=15)
        if chat_process.is_alive():
            chat_process.terminate()
            chat_process.join(timeout=2)
            raise ProviderInitError(f"ChatWith timeout for '{display_name}'")
        try:
            result = result_queue.get_nowait()
        except queue.Empty as exc:
            raise ProviderInitError("wxauto4 ChatWith returned no result") from exc
        if not result.get("ok"):
            raise ProviderInitError(
                f"wxauto4 ChatWith failed for '{display_name}': {result.get('error', '')}"
            )
        return True

    def list_visible_messages(self) -> list[RealtimeMessage]:
        if self.wx is None:
            return []
        messages = []
        for index, msg in enumerate(self.wx.GetAllMessage() or []):
            sender_attr = "self" if getattr(msg, "is_self", False) else "friend"
            is_system = bool(getattr(msg, "is_system", False))
            if is_system:
                sender_attr = "system"
            messages.append(
                RealtimeMessage(
                    runtime_id=str(getattr(msg, "id", "") or ""),
                    sender_attr=sender_attr,
                    content=str(getattr(msg, "content", "") or ""),
                    message_type=str(getattr(msg, "type", "text") or "text"),
                    timestamp_label=str(
                        getattr(msg, "time", None) or getattr(msg, "CreateTime", "") or ""
                    ),
                    timestamp=0,
                    message_hash=str(getattr(msg, "hash", "") or ""),
                    is_system=is_system,
                    visible_index=index,
                )
            )
        return messages

    def scroll_up(self, wheel_times: int = 2) -> bool:
        if not self.wx or not hasattr(self.wx, "ChatBox"):
            return False
        try:
            msgbox = self.wx.ChatBox.msgbox
            msgbox.MiddleClick()
            msgbox.WheelUp(wheelTimes=wheel_times)
            time.sleep(0.8)
            return True
        except Exception as exc:
            logger.debug("wxauto scroll up failed: %s", exc)
            return False

    def scroll_down(self, wheel_times: int = 4) -> bool:
        if not self.wx or not hasattr(self.wx, "ChatBox"):
            return False
        try:
            msgbox = self.wx.ChatBox.msgbox
            msgbox.MiddleClick()
            msgbox.WheelDown(wheelTimes=wheel_times)
            time.sleep(0.5)
            return True
        except Exception as exc:
            logger.debug("wxauto scroll down failed: %s", exc)
            return False

    def get_hwnd(self) -> int:
        if self.wx and hasattr(self.wx, "_api") and hasattr(self.wx._api, "HWND"):
            return int(self.wx._api.HWND or 0)
        return 0

    def close(self) -> None:
        if self.wx is not None:
            try:
                stop_listening = getattr(self.wx, "StopListening", None)
                if callable(stop_listening):
                    stop_listening()
            except Exception:
                pass
        self.wx = None
