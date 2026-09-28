"""G3 生成侧近期对话净化:系统通知/转账事件不得污染建议生成的消息窗口。

写入侧(provider 的 system 标记)不等于生成侧已净化——UIA/db_watch 对
转账气泡会标成 ``friend + text``,直接进 prompt 会被模型解读成
"对方只发过转账 = 冷淡/不接话"。本模块在 prompt 装配前统一分类:

- ``human_chat``       正常人工聊天(含图片/语音占位);
- ``transfer_event``   转账/收款/红包等资金事件,渲染为事件行,不伪装成发言;
- ``system_notice``    系统通知(撤回/拍一拍/验证消息等),不占窗口名额;
- ``unparseable``      空内容或无法解析的消息,丢弃。
"""

from __future__ import annotations

import re
from typing import Any, Iterable

KIND_HUMAN_CHAT = "human_chat"
KIND_TRANSFER_EVENT = "transfer_event"
KIND_SYSTEM_NOTICE = "system_notice"
KIND_UNPARSEABLE = "unparseable"

# 资金事件:只匹配事件性文本,正常文字提及转账("我昨天给你转了钱记得收")
# 不含下列强模式,不会被误伤。
TRANSFER_TEXT_PATTERNS = (
    "[转账]",
    "[收款]",
    "[红包]",
    "向你转账",
    "给你转账",
    "已收款",
    "已收钱",
    "收到转账",
    "朋友转账",
    "微信转账",
    "转账给你",
    "退还转账",
    "已退还",
    "领取了红包",
    "发出红包",
    "微信支付收款",
    "收款到账",
)

SYSTEM_NOTICE_PATTERNS = (
    "撤回了一条消息",
    "撤回了一条新消息",
    "拍了拍",
    "以下为新消息",
    "以下是新消息",
    "以上是打招呼的内容",
    "你已添加了",
    "对方开启了朋友验证",
    "开启了朋友验证",
    "请先发送朋友验证请求",
    "对方开启了免打扰",
    "以上的消息",
    " invited ",  # 群邀请
    "加入了群聊",
    "修改群名为",
    "你被移出群聊",
)

UNPARSEABLE_PATTERNS = (
    "[不支持的消息类型]",
    "[未知消息]",
    "[Invalid message]",
)

# 事件行在窗口里的渲染上限:转账密集时最多保留最近这几条做背景。
MAX_TRANSFER_EVENTS_IN_WINDOW = 2

_SYSTEM_NOTICE_RE = re.compile("|".join(re.escape(pattern) for pattern in SYSTEM_NOTICE_PATTERNS))
_TRANSFER_RE = re.compile("|".join(re.escape(pattern) for pattern in TRANSFER_TEXT_PATTERNS))
_UNPARSEABLE_RE = re.compile("|".join(re.escape(pattern) for pattern in UNPARSEABLE_PATTERNS))


def classify_message_kind(message: dict[str, Any] | None) -> str:
    """把单条消息分类为 human_chat / transfer_event / system_notice / unparseable。"""
    if not isinstance(message, dict):
        return KIND_UNPARSEABLE

    sender_attr = str(message.get("sender_attr") or "").strip().lower()
    message_type = str(message.get("message_type") or message.get("type") or "").strip().lower()

    if sender_attr == "system" or message_type in {"system", "notice"}:
        return KIND_SYSTEM_NOTICE
    if message_type in {"transfer", "red_packet", "payment", "wallet"}:
        return KIND_TRANSFER_EVENT

    content = str(message.get("content") or "").strip()
    if not content:
        return KIND_UNPARSEABLE
    if _UNPARSEABLE_RE.search(content):
        return KIND_UNPARSEABLE
    if _TRANSFER_RE.search(content) and len(content) <= 60:
        # 事件性气泡通常很短;长文本里"顺带提到"转账的仍是人工聊天。
        return KIND_TRANSFER_EVENT
    if _SYSTEM_NOTICE_RE.search(content) and len(content) <= 60:
        return KIND_SYSTEM_NOTICE
    return KIND_HUMAN_CHAT


def transfer_event_line(message: dict[str, Any]) -> str:
    """转账事件的摘要文案:明确标注非聊天发言,不得伪装成对方主动说话。"""
    content = str(message.get("content") or "").strip()
    sender_attr = str(message.get("sender_attr") or "").strip().lower()
    who = "对方" if sender_attr == "friend" else "我"
    return f"【事件】{who}侧发生资金往来（{content[:24]}，非聊天发言）"


def purify_recent_window(
    messages: Iterable[dict[str, Any]],
    *,
    limit: int = 20,
) -> dict[str, Any]:
    """净化最近消息窗口:通知剔除、转账转事件行、聊天保留名额。

    返回::

        {
            "window": [...],           # 时间正序,含 human_chat 与少量 transfer_event
            "chat_window": [...],      # 仅 human_chat,截断到 limit(选窗结果)
            "all_chats": [...],        # 全部人工聊天(压缩摘要用,不截断)
            "dropped_notices": int,
            "dropped_unparseable": int,
            "transfer_events": [...],  # 被 rendered 为事件行的原始消息
            "chat_count": int,
            "notice_only": bool,       # 窗口内没有任何有效人工聊天
        }
    """
    ordered = list(messages or [])
    chats: list[dict[str, Any]] = []
    notices = 0
    unparseable = 0
    transfers: list[dict[str, Any]] = []

    for message in ordered:
        kind = classify_message_kind(message)
        if kind == KIND_HUMAN_CHAT:
            chats.append(dict(message, _window_kind=KIND_HUMAN_CHAT))
        elif kind == KIND_TRANSFER_EVENT:
            transfers.append(message)
        elif kind == KIND_SYSTEM_NOTICE:
            notices += 1
        else:
            unparseable += 1

    # 名额只留给人工聊天;最近几条转账事件作为背景附加,不占聊天名额。
    chat_window = chats[-max(0, int(limit)):] if limit else chats
    kept_transfers = transfers[-MAX_TRANSFER_EVENTS_IN_WINDOW:]

    merged = sorted(
        chat_window + [dict(msg, _window_kind=KIND_TRANSFER_EVENT) for msg in kept_transfers],
        key=_message_order_key,
    )

    return {
        "window": merged,
        "chat_window": chat_window,
        "all_chats": chats,
        "dropped_notices": notices,
        "dropped_unparseable": unparseable,
        "transfer_events": kept_transfers,
        "chat_count": len(chat_window),
        "notice_only": bool(ordered) and not chats and (notices + len(transfers)) > 0,
    }


def _message_order_key(message: dict[str, Any]) -> tuple[int, int, int, int]:
    def _safe_int(value: Any, default: int = 0) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    timestamp = _safe_int(message.get("timestamp"))
    visible_index = _safe_int(message.get("visible_index"), -1)
    created_at = _safe_int(message.get("created_at"))
    row_id = _safe_int(message.get("id"))
    if visible_index >= 0:
        return (timestamp, 0, visible_index, created_at or row_id)
    return (timestamp, 1, created_at, row_id)


def compute_pairing_stats(messages: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """基于净化后消息的回复配对统计(供 chart_stats 使用)。

    修复旧实现的两个配对错误:

    - 回复率:旧逻辑把"我方消息之后任意位置出现对方消息"都算回复;
      现在要求紧邻下一条是对方消息;
    - 回复间隔:旧逻辑算的是对方相邻两条消息的间隔;现在算
      我方消息 → 对方下一条回复 的时延。
    """
    chats = [
        message
        for message in (messages or [])
        if classify_message_kind(message) == KIND_HUMAN_CHAT
    ]
    friend_msgs = [msg for msg in chats if str(msg.get("sender_attr") or "") == "friend"]
    self_msgs = [msg for msg in chats if str(msg.get("sender_attr") or "") == "self"]

    replied_count = 0
    gaps: list[int] = []
    for index, msg in enumerate(chats):
        if str(msg.get("sender_attr") or "") != "self":
            continue
        next_msg = chats[index + 1] if index + 1 < len(chats) else None
        if next_msg is not None and str(next_msg.get("sender_attr") or "") == "friend":
            replied_count += 1
            gap = int(next_msg.get("timestamp") or 0) - int(msg.get("timestamp") or 0)
            if 0 < gap < 3600:
                gaps.append(gap)

    positive_count = sum(
        1 for msg in friend_msgs if ((msg.get("sentiment") or {}).get("polarity", 0) or 0) > 0
    )

    return {
        "reply_rate": f"{replied_count / len(self_msgs):.2f}" if self_msgs else "N/A",
        "positive_rate": f"{positive_count / len(friend_msgs):.2f}" if friend_msgs else "N/A",
        "msg_ratio": f"{len(self_msgs)}:{len(friend_msgs)}" if (self_msgs or friend_msgs) else "N/A",
        "avg_reply_gap": round(sum(gaps) / len(gaps)) if gaps else None,
        "friend_msg_count": len(friend_msgs),
        "self_msg_count": len(self_msgs),
    }
