"""Shared message and version models for realtime providers."""

from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha1
import re


def normalize_text(text: str | None) -> str:
    """Collapse whitespace for stable matching and hashing."""
    return re.sub(r"\s+", " ", str(text or "")).strip()


def runtime_id_to_string(runtime_id) -> str:
    """Normalize UIA runtime ids to a stable string form."""
    if runtime_id is None:
        return ""
    if isinstance(runtime_id, (list, tuple)):
        return "-".join(str(part) for part in runtime_id)
    return str(runtime_id)


def build_message_hash(
    listener_profile: str,
    sender_attr: str,
    message_type: str,
    content: str,
    resolved_timestamp: int,
    runtime_id_or_occurrence: str,
) -> str:
    """Build a stable project-owned message hash."""
    payload = "|".join(
        [
            normalize_text(listener_profile),
            normalize_text(sender_attr),
            normalize_text(message_type).lower(),
            normalize_text(content),
            str(int(resolved_timestamp or 0)),
            normalize_text(runtime_id_or_occurrence),
        ]
    )
    return sha1(payload.encode("utf-8")).hexdigest()


@dataclass(slots=True)
class RealtimeMessage:
    """Provider-neutral message shape consumed by monitor_service."""

    runtime_id: str
    sender_attr: str
    content: str
    message_type: str
    timestamp_label: str = ""
    timestamp: int = 0
    message_hash: str = ""
    is_system: bool = False
    visible_index: int = -1
    metadata: dict = field(default_factory=dict)

    @property
    def id(self) -> str:
        return self.runtime_id

    @property
    def hash(self) -> str:
        return self.message_hash

    @property
    def type(self) -> str:
        return self.message_type

    @property
    def time(self) -> str:
        return self.timestamp_label

    @property
    def CreateTime(self) -> str:
        return self.timestamp_label

    @property
    def is_self(self) -> bool:
        return self.sender_attr == "self"


@dataclass(slots=True)
class WeChatVersionInfo:
    """Detected WeChat runtime information."""

    version: str = ""
    listener_profile: str = ""
    hwnd: int = 0
    exe_path: str = ""

