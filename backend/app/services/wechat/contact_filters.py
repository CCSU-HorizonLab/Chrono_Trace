"""Shared filters for WeChat system/service contacts."""

from __future__ import annotations


# These built-in accounts are not meaningful as real relationship contacts.
EXCLUDED_CONTACT_USERNAMES = frozenset(
    {
        "brandsessionholder",
        "exmail_tool",
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


def is_excluded_contact_username(
    username: str | None, *, exclude_chatroom: bool = True
) -> bool:
    """Return True if the username is a system/service contact to exclude.

    exclude_chatroom=False 放行群聊（导入链路使用——群数据需入库供
    浏览与导出）；分析/RAG/监听等消费方保持默认排除。
    """
    normalized = normalize_contact_username(username)
    if not normalized:
        return False
    return (
        normalized in EXCLUDED_CONTACT_USERNAMES
        or (exclude_chatroom and "@chatroom" in normalized)
        or "@openim" in normalized
        or normalized.startswith("gh_")
    )
