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
    sender_wxid: str | None,
    fallback: str = "成员",
    name_map: Optional[dict] = None,
) -> str:
    """解析群成员显示名。

    name_map 为 contact 库的 wxid→显示名映射（我的备注优先于微信昵
    称，见 ContactDBV4.get_display_name_map），命中优先返回；未提供/
    未命中走 wxid 短格式兜底。群名片（群内昵称）在 chat_room 的
    ext_buffer protobuf 里，暂不解析——备注/昵称已覆盖 99.9% 成员。
    """
    if not sender_wxid:
        return fallback
    if name_map:
        mapped = name_map.get(sender_wxid)
        if mapped:
            return mapped
    # wxid_xxx 取后半段作为短名；纯数字 ID 取后 4 位
    if sender_wxid.startswith("wxid_"):
        suffix = sender_wxid[5:]
        return suffix if suffix else sender_wxid
    if sender_wxid.isdigit() and len(sender_wxid) > 4:
        return f"成员{sender_wxid[-4:]}"
    return sender_wxid
