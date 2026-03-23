"""Provider factory for realtime monitoring backends."""

from __future__ import annotations

import json
from pathlib import Path

from .base import UINotAccessibleError, UnsupportedWeChatVersionError
from .detector import detect_running_wechat
from .native_uia import NativeUIARealtimeProvider
from .wxauto_provider import WxautoRealtimeProvider


def _load_listener_backend(default: str = "auto") -> str:
    settings_file = Path(__file__).resolve().parents[4] / "data" / "settings.json"
    try:
        if settings_file.exists():
            with open(settings_file, "r", encoding="utf-8") as handle:
                settings = json.load(handle)
            return str(settings.get("listener_backend", default) or default)
    except Exception:
        pass
    return default


class RealtimeProviderFactory:
    """Create the appropriate provider for the current environment."""

    @classmethod
    def create(cls, backend: str | None = None):
        selected_backend = str(backend or _load_listener_backend()).strip().lower() or "auto"
        version_info = detect_running_wechat()

        if selected_backend == "wxauto":
            provider = WxautoRealtimeProvider()
            provider.initialize()
            return provider

        if selected_backend not in {"auto", "native_uia"}:
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
        try:
            native_provider.initialize()
            return native_provider
        except UINotAccessibleError:
            if selected_backend == "native_uia":
                raise
        except Exception:
            if selected_backend == "native_uia":
                raise

        fallback = WxautoRealtimeProvider()
        fallback.wechat_version = version_info.version
        fallback.listener_profile = version_info.listener_profile or "wxauto4"
        fallback.initialize()
        return fallback
