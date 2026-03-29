"""Base classes and exceptions for realtime listener providers."""

from __future__ import annotations

from abc import ABC, abstractmethod


class ProviderError(RuntimeError):
    """Base provider error."""


class ProviderInitError(ProviderError):
    """Raised when the provider cannot initialize."""


class UINotAccessibleError(ProviderError):
    """Raised when WeChat UI cannot be inspected reliably."""


class UnsupportedWeChatVersionError(ProviderError):
    """Raised when the current WeChat version is outside the supported matrix."""


class RealtimeProvider(ABC):
    """Abstract provider used by RealtimeMonitorService."""

    backend_name = "unknown"

    def __init__(self):
        self.listener_profile = ""
        self.wechat_version = ""
        self.account_name = ""
        self.current_display_name = ""

    @abstractmethod
    def initialize(self) -> None:
        """Prepare the provider for use."""

    @abstractmethod
    def activate_main_window(self) -> bool:
        """Bring the WeChat window to the foreground."""

    @abstractmethod
    def open_chat(self, display_name: str, expected_display_name: str | None = None) -> bool:
        """Switch to a target chat."""

    @abstractmethod
    def list_visible_messages(self) -> list:
        """Return visible messages in the active chat."""

    @abstractmethod
    def scroll_up(self, wheel_times: int = 2) -> bool:
        """Scroll the active chat upward."""

    @abstractmethod
    def scroll_down(self, wheel_times: int = 4) -> bool:
        """Scroll the active chat downward."""

    @abstractmethod
    def close(self) -> None:
        """Release provider resources."""

    def get_hwnd(self) -> int:
        """Best-effort hwnd for diagnostics/foreground control."""
        return 0
