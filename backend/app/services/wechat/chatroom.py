"""群聊消息处理：前缀剥离 + 成员名解析 + 类型判定。

微信 V4 群消息的 message_content 格式为 `wxid_xxx:\\n内容`——发送者
wxid 以冒号换行前缀嵌在内容里。全链路此前无任何地方剥离该前缀，
导致群消息内容带 wxid 前缀进入显示与分析。
"""
from __future__ import annotations

import re
from typing import Optional


# 群消息前缀：`wxid_xxx:\n` 或 `wxid_xxx: \n`（偶尔有无空白变体）
_CHATROOM_PREFIX = re.compile(
    r"^(wxid_[a-zA-Z0-9_]+|-?\d{5,})\s*:\s*\n", re.ASCII
)


def is_chatroom_username(username: str | None) -> bool:
    """判定 username 是否为群聊 ID（@chatroom 结尾）。"""
    return "@chatroom" in (username or "").strip().lower()


def parse_chatroom_message(content: str) -> tuple[Optional[str], str]:
    """剥离群消息 'wxid:\\n' 前缀。

    Returns:
        (sender_wxid, clean_content)；无前缀时 sender_wxid 为 None。
    """
    if not content:
        return None, content or ""
    match = _CHATROOM_PREFIX.match(content)
    if match:
        return match.group(1), content[match.end():]
    return None, content


def resolve_chatroom_display_name(
    sender_wxid: str | None, fallback: str = "成员"
) -> str:
    """解析群成员显示名。

    当前无群成员库可查（path_finder 未发现群成员库文件），用 wxid
    短格式兜底；后续若能读取群成员表则在此接入真名映射。
    """
    if not sender_wxid:
        return fallback
    # wxid_xxx 取后半段作为短名；纯数字 ID 取后 4 位
    if sender_wxid.startswith("wxid_"):
        suffix = sender_wxid[5:]
        return suffix if suffix else sender_wxid
    if sender_wxid.isdigit() and len(sender_wxid) > 4:
        return f"成员{sender_wxid[-4:]}"
    return sender_wxid
