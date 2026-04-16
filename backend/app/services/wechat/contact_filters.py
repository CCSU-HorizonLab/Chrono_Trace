"""Shared filters for WeChat system/service contacts."""

from __future__ import annotations


# These built-in accounts are not meaningful as real relationship contacts.
EXCLUDED_CONTACT_USERNAMES = frozenset(
    {
        "brandsessionholder",
        "filehelper",
        "fmessage",
        "floatbottle",
        "medianote",
        "notifymessage",
        "qqmail",
        "weixin",
    }
)


def normalize_contact_username(username: str | None) -> str:
    return (username or "").strip().lower()


def is_excluded_contact_username(username: str | None) -> bool:
    normalized = normalize_contact_username(username)
    if not normalized:
        return False
    return (
        normalized in EXCLUDED_CONTACT_USERNAMES
        or "@chatroom" in normalized
        or "@openim" in normalized
        or normalized.startswith("gh_")
    )
