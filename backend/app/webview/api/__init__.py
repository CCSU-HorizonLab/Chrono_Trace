"""Bridge API 域 mixin 共享小件。"""

from __future__ import annotations


def conversation_is_group(conversation_id: int) -> bool:
    """会话是否群聊（前端已挡单聊专属功能，此处为 bridge 直调/竞态兜底）。

    会话不存在返回 False：下游按「会话不存在」口径自然报错。
    """
    from ...db.connection import get_db

    row = get_db().execute(
        "SELECT conversation_type FROM conversations WHERE id = ?",
        (int(conversation_id),),
    ).fetchone()
    return bool(row) and row[0] == "group"
