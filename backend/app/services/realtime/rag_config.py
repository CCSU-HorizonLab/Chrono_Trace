"""Configuration helpers for realtime suggestion RAG."""

from __future__ import annotations

import ipaddress
from typing import Any
from urllib.parse import urlparse

from ..model_paths import EMBEDDING_MODEL_REPO_ID
from ..wechat.account_settings import load_settings_from_file


RAG_DEFAULTS: dict[str, Any] = {
    "rag_enabled": False,
    "rag_remote_context_redaction": True,
    "rag_allow_remote_embedding": False,
    "rag_embedding_provider": "local",
    "rag_embedding_model": EMBEDDING_MODEL_REPO_ID,
    "rag_embedding_dim": 384,
    "rag_privacy_mode": "balanced",
    "rag_cross_contact_style_enabled": False,
}


def _as_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "yes", "on", "enabled"}:
        return True
    if normalized in {"0", "false", "no", "off", "disabled"}:
        return False
    return default


def apply_rag_defaults(settings: dict[str, Any]) -> dict[str, Any]:
    """Mutate and return settings with explicit RAG defaults."""
    for key, value in RAG_DEFAULTS.items():
        settings.setdefault(key, value)
    settings["rag_enabled"] = _as_bool(settings.get("rag_enabled"), False)
    settings["rag_remote_context_redaction"] = _as_bool(
        settings.get("rag_remote_context_redaction"),
        True,
    )
    settings["rag_allow_remote_embedding"] = _as_bool(
        settings.get("rag_allow_remote_embedding"),
        False,
    )
    settings["rag_cross_contact_style_enabled"] = _as_bool(
        settings.get("rag_cross_contact_style_enabled"),
        False,
    )
    try:
        settings["rag_embedding_dim"] = int(settings.get("rag_embedding_dim") or 384)
    except (TypeError, ValueError):
        settings["rag_embedding_dim"] = 384
    if settings["rag_embedding_dim"] <= 0:
        settings["rag_embedding_dim"] = 384
    if not str(settings.get("rag_embedding_model") or "").strip():
        settings["rag_embedding_model"] = RAG_DEFAULTS["rag_embedding_model"]
    if settings.get("rag_embedding_provider") not in {"local", "remote", "custom"}:
        settings["rag_embedding_provider"] = "local"
    if settings.get("rag_privacy_mode") not in {"balanced", "strict", "raw_local"}:
        settings["rag_privacy_mode"] = "balanced"
    return settings


def load_rag_settings(settings: dict[str, Any] | None = None) -> dict[str, Any]:
    """Load persisted RAG settings with normalized defaults."""
    return apply_rag_defaults(dict(settings if settings is not None else load_settings_from_file()))


def is_remote_llm_model(model_config: dict[str, Any] | None) -> bool:
    """Return whether the active LLM sends prompts outside the local machine."""
    if not model_config:
        return False
    provider = str(model_config.get("provider") or "").strip().lower()
    base_url = str(model_config.get("api_base_url") or "").strip().lower()
    if not base_url:
        return provider not in {"ollama", "lmstudio", "local"}
    parsed = urlparse(base_url if "://" in base_url else f"http://{base_url}")
    host = (parsed.hostname or "").strip().lower()
    if host in {"localhost", "127.0.0.1", "::1"}:
        return False
    try:
        if ipaddress.ip_address(host).is_loopback:
            return False
    except ValueError:
        pass
    return True
