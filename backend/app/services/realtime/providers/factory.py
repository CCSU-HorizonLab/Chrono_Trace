"""Provider factory for realtime monitoring backends."""

from __future__ import annotations

import sys

from .base import ProviderInitError, UnsupportedWeChatVersionError
from .detector import detect_running_wechat
from .native_uia import NativeUIARealtimeProvider
from ...wechat.account_settings import load_settings_from_file

# Linux 默认走 db_watch（加密库文件直读），Windows 默认 native_uia
DEFAULT_LISTENER_BACKEND = "db_watch" if sys.platform != "win32" else "native_uia"


def normalize_listener_backend(value: str | None, default: str = DEFAULT_LISTENER_BACKEND) -> str:
    """Collapse legacy backend names onto supported providers."""
    raw_value = str(value or default).strip().lower()
    if raw_value in {"", "auto", "wxauto", "native_uia"}:
        return "native_uia"
    if raw_value == "db_watch":
        return "db_watch"
    return raw_value


def _load_listener_backend(default: str = DEFAULT_LISTENER_BACKEND) -> str:
    try:
        settings = load_settings_from_file()
        return normalize_listener_backend(settings.get("listener_backend"), default=default)
    except Exception:
        pass
    return normalize_listener_backend(default, default=default)


class RealtimeProviderFactory:
    """Create the appropriate provider for the current environment."""

    @classmethod
    def create(cls, backend: str | None = None):
        selected_backend = normalize_listener_backend(backend or _load_listener_backend())

        if selected_backend == "db_watch":
            from .db_watch import DbWatchRealtimeProvider

            provider = DbWatchRealtimeProvider()
            provider.initialize()
            return provider

        version_info = detect_running_wechat()

        if selected_backend != "native_uia":
            raise UnsupportedWeChatVersionError(f"Unknown listener backend: {selected_backend}")

        if version_info.listener_profile not in {"wechat_405", "wechat_41x"}:
            raise UnsupportedWeChatVersionError(
                f"unsupported_wechat_version: {version_info.version or 'unknown'}"
            )

        native_provider = NativeUIARealtimeProvider(
            listener_profile=version_info.listener_profile,
            wechat_version=version_info.version,
            hwnd=version_info.hwnd,
        )
        native_provider.initialize()
        return native_provider
