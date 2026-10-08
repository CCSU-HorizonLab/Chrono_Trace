"""聊天记录导出格式化器：TXT / CSV / HTML。

私聊：`is_sender` 判我/对方；群聊：`sender` 字段存成员 wxid，
经 `chatroom.resolve_chatroom_display_name` 解析显示名。
"""
from __future__ import annotations

import csv
import html as html_module
import io
from datetime import datetime
from typing import Any, Optional

# 群成员气泡配色（按 sender 哈希取色，保证同一成员颜色稳定）
_MEMBER_COLORS = [
    "#e67e22", "#8e44ad", "#16a085", "#2980b9", "#d35400",
    "#c0392b", "#27ae60", "#f39c12", "#7f8c8d", "#2c3e50",
]

_TYPE_LABELS = {
    1: "文本", 3: "图片", 34: "语音", 43: "视频", 47: "表情",
    48: "位置", 49: "链接/小程序", 50: "通话", 42: "名片", 10000: "系统",
}


def _fmt_time(ts: int) -> str:
    if not ts:
        return ""
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")


def _fmt_date_short(ts: int) -> str:
    if not ts:
        return ""
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")


def _type_label(msg_type: int) -> str:
    return _TYPE_LABELS.get(msg_type, f"类型{msg_type}")


def _sender_name(msg: dict[str, Any], my_name: str = "我") -> str:
    if msg.get("is_sender"):
        return my_name
    sender = str(msg.get("sender") or "").strip()
    if sender and sender != msg.get("talker"):
        # 群成员：解析 wxid 短名
        from ..wechat.chatroom import resolve_chatroom_display_name
        return resolve_chatroom_display_name(sender)
    return str(msg.get("talker_display_name") or msg.get("talker") or "对方")


def format_txt(messages: list[dict[str, Any]], conversation_name: str) -> str:
    """纯文本格式：`[YYYY-MM-DD HH:MM] 发送者：内容`"""
    lines = [f"═══ {conversation_name} 聊天记录 ═══", f"导出时间：{_fmt_time(int(datetime.now().timestamp()))}", ""]
    current_date = ""
    for msg in messages:
        ts = int(msg.get("timestamp") or 0)
        date_part = datetime.fromtimestamp(ts).strftime("%Y-%m-%d") if ts else ""
        if date_part and date_part != current_date:
            lines.append(f"── {date_part} ──")
            current_date = date_part
        content = _clean_content(msg)
        sender = _sender_name(msg)
        lines.append(f"[{_fmt_date_short(ts)}] {sender}：{content}")
    return "\n".join(lines) + "\n"


def format_csv(messages: list[dict[str, Any]]) -> str:
    """CSV 格式（BOM 头 + UTF-8，Excel 直接打开不乱码）。"""
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["时间", "发送者", "是否本人", "消息类型", "内容"])
    for msg in messages:
        writer.writerow([
            _fmt_time(int(msg.get("timestamp") or 0)),
            _sender_name(msg),
            "是" if msg.get("is_sender") else "否",
            _type_label(int(msg.get("message_type") or 1)),
            _clean_content(msg),
        ])
    return "﻿" + output.getvalue()


def format_html(messages: list[dict[str, Any]], conversation_name: str) -> str:
    """聊天气泡风格 HTML（内联 CSS，浏览器直接打开可看）。"""
    rows = []
    color_map: dict[str, str] = {}
    for msg in messages:
        is_me = bool(msg.get("is_sender"))
        sender = _sender_name(msg)
        content = html_module.escape(_clean_content(msg))
        ts = int(msg.get("timestamp") or 0)
        time_str = _fmt_date_short(ts)
        if is_me:
            align, bubble, name_html = "right", "me", ""
        else:
            if sender not in color_map:
                color_map[sender] = _MEMBER_COLORS[len(color_map) % len(_MEMBER_COLORS)]
            align = "left"
            bubble = f"other" if not msg.get("sender") else "member"
            color = color_map[sender]
            name_html = f'<div class="sender" style="color:{color}">{html_module.escape(sender)}</div>'
        rows.append(f'''<div class="msg {align}">
  {name_html}
  <div class="bubble {bubble}">{content}</div>
  <div class="time">{time_str}</div>
</div>''')
    body = "\n".join(rows)
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<title>{html_module.escape(conversation_name)} 聊天记录</title>
<style>
  body {{ font-family: -apple-system, "Segoe UI", "PingFang SC", sans-serif; background: #f5f5f5; max-width: 720px; margin: 0 auto; padding: 20px; }}
  h1 {{ text-align: center; color: #333; font-size: 18px; margin-bottom: 20px; }}
  .msg {{ margin: 8px 0; clear: both; }}
  .msg.right {{ text-align: right; }}
  .msg.left {{ text-align: left; }}
  .bubble {{ display: inline-block; padding: 8px 14px; border-radius: 12px; max-width: 70%; word-wrap: break-word; text-align: left; font-size: 14px; line-height: 1.5; }}
  .bubble.me {{ background: #95ec69; color: #000; }}
  .bubble.other {{ background: #fff; color: #000; }}
  .bubble.member {{ background: #fff; color: #000; border: 1px solid #e0e0e0; }}
  .sender {{ font-size: 11px; color: #999; margin-bottom: 2px; }}
  .time {{ font-size: 10px; color: #ccc; margin-top: 2px; }}
  .msg.right .time {{ text-align: right; }}
</style>
</head>
<body>
<h1>{html_module.escape(conversation_name)}</h1>
{body}
</body>
</html>
"""


def _clean_content(msg: dict[str, Any]) -> str:
    content = str(msg.get("content") or "").strip()
    msg_type = int(msg.get("message_type") or 1)
    if msg_type == 1:
        # 群消息可能有 wxid:\n 前缀（旧数据未剥离时兜底）
        from ..wechat.chatroom import parse_chatroom_message
        _, content = parse_chatroom_message(content)
        return content
    return _TYPE_LABELS.get(msg_type, f"[消息]") if not content else content
