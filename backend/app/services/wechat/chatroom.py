"""群聊消息处理：前缀剥离 + 成员名解析 + 类型判定。

微信 V4 群消息的 message_content 格式为 `wxid_xxx:\\n内容`——发送者
wxid 以冒号换行前缀嵌在内容里。全链路此前无任何地方剥离该前缀，
导致群消息内容带 wxid 前缀进入显示与分析。
"""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


# 群消息前缀三种形态：`wxid_xxx:\n`（未设微信号用户）、自定义微信号
# （字母开头 6-20 位，如 `wwmilk:\n`）、纯数字 ID。后两种此前未识别，
# 导致内容带前缀入库污染词频/情感，sender 停留在 username 形态
_CHATROOM_PREFIX = re.compile(
    r"^(wxid_[a-zA-Z0-9_]+|[a-zA-Z][-_a-zA-Z0-9]{5,19}|-?\d{5,})\s*:\s*\n", re.ASCII
)


def is_chatroom_username(username: str | None) -> bool:
    """判定 username 是否为群聊 ID（@chatroom 结尾）。"""
    return "@chatroom" in (username or "").strip().lower()


def parse_chatroom_message(
    content: str, known_ids: Optional[set] = None
) -> tuple[Optional[str], str]:
    """剥离群消息 '发送者ID:\\n' 前缀（wxid_/微信号/纯数字三形态）。

    字母自定义微信号/纯数字 ID 形态与普通正文有歧义（`Warning:\\n注意`、
    `13800001111:\\n号码`、`20261113:\\n日期`），必须命中 known_ids 花名册
    （contact 全量 username 键集）才剥；wxid_ 形态特异无条件剥。宁可漏剥
    前缀残留，不可误伤正文。

    Returns:
        (sender_id, clean_content)；无前缀时 sender_id 为 None。sender_id
        为消息前缀里的原始 ID（wxid_xxx 或 username），由调用方经
        contact 昵称映射解析显示名。
    """
    if not content:
        return None, content or ""
    match = _CHATROOM_PREFIX.match(content)
    if match:
        sid = match.group(1)
        if not sid.startswith("wxid_") and not (known_ids and sid in known_ids):
            return None, content
        return sid, content[match.end():]
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


def load_contact_name_map() -> dict:
    """全账号合并的 username→显示名映射（各账号 contact.db 解密）。

    花名册白名单（键集，见 parse_chatroom_message）与群成员显示名解
    析两用，全表数万行构建毫秒级。单账号失败跳过、全部失败返回空
    dict——调用方按花名册缺席降级（歧义前缀不剥，仅 wxid_ 形态仍工作）。
    """
    import json

    from .account_settings import build_custom_paths, default_settings_path, get_wechat_accounts
    from .db.v4.contact import ContactDBV4

    try:
        settings = json.loads(default_settings_path().read_text("utf-8"))
    except (OSError, ValueError) as e:
        logger.warning("花名册加载失败（settings 不可读）: %s", e)
        return {}
    merged: dict = {}
    for acc in get_wechat_accounts(settings):
        key = str(acc.get("db_key") or "").strip()
        if not key and not acc.get("raw_keys"):
            continue
        paths = build_custom_paths(acc) or {}
        wechat_dir, wxid = paths.get("wechat_dir"), paths.get("current_user")
        if not wechat_dir or not wxid:
            continue
        contact_path = Path(wechat_dir) / wxid / "db_storage" / "contact" / "contact.db"
        if not contact_path.is_file():
            continue
        try:
            db = ContactDBV4(str(contact_path), key, raw_keys=acc.get("raw_keys") or None)
            try:
                merged.update(db.get_display_name_map())
            finally:
                db.close()
        except Exception as e:  # 解密失败不拖垮整体：跳过该账号
            logger.warning("花名册加载失败（跳过账号 %s）: %s", wxid, e)
    return merged


_ROSTER_CACHE: Optional[dict] = None


def get_contact_roster() -> dict:
    """进程级缓存花名册：监听每快照/导出每消息解密一次 contact.db 不可接受。

    好友圈在进程生命周期内变化极小，不设失效；导入侧每次全量重建不走缓存。
    """
    global _ROSTER_CACHE
    if _ROSTER_CACHE is None:
        _ROSTER_CACHE = load_contact_name_map()
    return _ROSTER_CACHE
