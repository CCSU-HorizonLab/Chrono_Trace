"""G3 生成侧近期对话净化测试:通知/转账分类、窗口名额、配对统计。"""

import os
import sys


sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.realtime.historical_context import compute_chart_stats
from app.services.realtime.recent_window import (
    KIND_HUMAN_CHAT,
    KIND_SYSTEM_NOTICE,
    KIND_TRANSFER_EVENT,
    KIND_UNPARSEABLE,
    classify_message_kind,
    compute_pairing_stats,
    purify_recent_window,
    transfer_event_line,
)


def _msg(sender: str, content: str, ts: int = 100, **extra):
    return {
        "id": ts,
        "timestamp": ts,
        "sender_attr": sender,
        "content": content,
        "message_type": "text",
        **extra,
    }


def test_classify_transfer_and_system_messages():
    assert classify_message_kind(_msg("friend", "[转账]向你转账100.00元")) == KIND_TRANSFER_EVENT
    assert classify_message_kind(_msg("friend", "已收款")) == KIND_TRANSFER_EVENT
    assert classify_message_kind(_msg("system", "对方撤回了一条消息")) == KIND_SYSTEM_NOTICE
    assert classify_message_kind(_msg("friend", "对方拍了拍我")) == KIND_SYSTEM_NOTICE
    assert classify_message_kind(_msg("friend", "今天好累呀")) == KIND_HUMAN_CHAT
    # 正常文字提及转账不算事件
    assert classify_message_kind(_msg("self", "我昨天给你转了钱,记得收一下哈,顺便说下周末的安排")) == KIND_HUMAN_CHAT
    assert classify_message_kind(_msg("friend", "")) == KIND_UNPARSEABLE
    assert classify_message_kind(_msg("friend", "[转账]", message_type="transfer")) == KIND_TRANSFER_EVENT


def test_purify_drops_notices_and_keeps_chat_quota():
    messages = (
        [_msg("friend", "在吗", 1)]
        + [_msg("system", "对方撤回了一条消息", 2 + i) for i in range(10)]
        + [_msg("self", "在的", 20), _msg("friend", "周末有空吗", 21)]
    )
    result = purify_recent_window(messages, limit=20)
    assert result["dropped_notices"] == 10
    assert result["chat_count"] == 3
    assert all(msg["content"] != "对方撤回了一条消息" for msg in result["window"])


def test_purify_transfer_events_do_not_consume_chat_quota():
    """转账密集窗口仍能保留有效聊天;转账渲染为事件行且限量。"""
    messages = (
        [_msg("friend", "[转账]向你转账50.00元", i) for i in range(10)]
        + [_msg("self", "收到了,谢谢", 100), _msg("friend", "请你喝奶茶", 101)]
    )
    result = purify_recent_window(messages, limit=5)
    assert result["chat_count"] == 2
    assert len(result["transfer_events"]) == 2  # MAX_TRANSFER_EVENTS_IN_WINDOW
    kinds = [msg.get("_window_kind") for msg in result["window"]]
    assert kinds.count(KIND_TRANSFER_EVENT) == 2
    assert kinds.count(KIND_HUMAN_CHAT) == 2


def test_transfer_event_line_is_explicitly_not_speech():
    line = transfer_event_line(_msg("friend", "[转账]向你转账100.00元", 1))
    assert line.startswith("【事件】")
    assert "非聊天发言" in line
    assert "对方" in line


def test_notice_only_window_flagged():
    messages = [_msg("friend", "[转账]向你转账1.00元", 1), _msg("system", "拍了拍", 2)]
    result = purify_recent_window(messages)
    assert result["notice_only"] is True
    assert result["chat_count"] == 0


def test_pairing_stats_use_immediate_reply_matching():
    """回复率:紧邻下一条是对方才算回复,不再把任意后续对方消息算进来。"""
    messages = [
        _msg("self", "在吗", 1),
        _msg("self", "看到回我一下", 2),   # 我方连发,紧邻下一条不是对方 → 未回复
        _msg("friend", "刚看到", 60),
        _msg("self", "嗯嗯", 61),
        _msg("friend", "周末出去走走?", 130),
    ]
    stats = compute_pairing_stats(messages)
    assert stats["self_msg_count"] == 3
    assert stats["friend_msg_count"] == 2
    # 回复的判定:self[1]→self 未回;self[2]→friend 回了;self[3]→friend 回了 → 2/3
    assert stats["reply_rate"] == f"{2/3:.2f}"
    # 间隔取"我方消息→对方回复":2→60 = 58s,61→130 = 69s,均值 63.5 → 64
    assert stats["avg_reply_gap"] == 64


def test_pairing_stats_exclude_transfer_bubbles():
    """转账气泡(上游误标 friend)不参与配对与情绪统计。"""
    messages = [
        _msg("self", "钱转你了", 1),
        _msg("friend", "[转账]已收款", 2),
        _msg("friend", "收到啦谢谢", 300),
    ]
    stats = compute_pairing_stats(messages)
    assert stats["friend_msg_count"] == 1
    assert stats["reply_rate"] == "1.00"
    assert stats["avg_reply_gap"] == 299


def test_compute_chart_stats_delegates_to_purified_pairing():
    messages = [
        _msg("self", "hi", 1),
        _msg("friend", "[转账]已收款", 2),
        _msg("friend", "hello", 3),
    ]
    stats = compute_chart_stats(messages)
    assert stats["friend_msg_count"] == 1
    assert stats["msg_ratio"] == "1:1"


def test_window_sorted_by_time():
    messages = [
        _msg("friend", "晚点聊", 200),
        _msg("self", "好", 100),
        _msg("friend", "[转账]已收款", 150),
    ]
    result = purify_recent_window(messages)
    contents = [msg["content"] for msg in result["window"]]
    assert contents == ["好", "[转账]已收款", "晚点聊"]
