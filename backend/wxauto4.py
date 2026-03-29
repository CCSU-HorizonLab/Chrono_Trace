"""Project-local wxauto4 compatibility shim backed by realtime providers."""

from __future__ import annotations

from types import SimpleNamespace

try:
    from backend.app.services.realtime.providers.factory import RealtimeProviderFactory
except ModuleNotFoundError:  # pragma: no cover - compatibility with backend-only test path
    from app.services.realtime.providers.factory import RealtimeProviderFactory


class _ProviderMsgBox:
    def __init__(self, provider):
        self._provider = provider

    def MiddleClick(self):
        return True

    def WheelUp(self, wheelTimes: int = 2):
        return self._provider.scroll_up(wheel_times=wheelTimes)

    def WheelDown(self, wheelTimes: int = 4):
        return self._provider.scroll_down(wheel_times=wheelTimes)


class _ProviderChatBox:
    def __init__(self, provider):
        self.msgbox = _ProviderMsgBox(provider)


class WeChat:
    """Compatibility wrapper exposing the subset monitor_service relies on."""

    def __init__(self, start_listener: bool = False, backend: str | None = None):
        self._provider = RealtimeProviderFactory.create(backend=backend)
        self.start_listener = bool(start_listener)
        self._sync_metadata()

    def _sync_metadata(self):
        self.nickname = getattr(self._provider, "account_name", "") or ""
        self.backend_name = getattr(self._provider, "backend_name", "")
        self.listener_profile = getattr(self._provider, "listener_profile", "")
        self.wechat_version = getattr(self._provider, "wechat_version", "")
        self._api = SimpleNamespace(HWND=self._provider.get_hwnd())
        self.ChatBox = _ProviderChatBox(self._provider)

    def ChatWith(self, target_name: str, expected_display_name: str | None = None):
        result = self._provider.open_chat(
            target_name,
            expected_display_name=expected_display_name,
        )
        self._sync_metadata()
        return result

    def GetAllMessage(self):
        return self._provider.list_visible_messages()

    def StopListening(self):
        self._provider.close()

    def close(self):
        self._provider.close()
