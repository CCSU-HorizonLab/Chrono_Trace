"""基础统计收集（BasicPreprocessingService）。（拆分自原 preprocessing_service.py）"""
import re
import json
import logging
import time
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime
from ....db.connection import get_db

logger = logging.getLogger(__name__)


class BasicPreprocessingService:
    """基础预处理服务 - 收集消息和时间统计"""

    def __init__(self):
        pass  # get_db() removed for thread safety

    def collect_message_statistics(
        self,
        conversation_id: int,
        from_ts: Optional[int] = None,
        to_ts: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        收集消息统计信息

        Args:
            conversation_id: 会话ID
            from_ts: 开始时间戳（可选）
            to_ts: 结束时间戳（可选）

        Returns:
            {
                "total_message_count": 1234,
                "total_positive_count": 800,
                "total_negative_count": 200,
                "total_neutral_count": 234
            }
        """
        # 构建查询条件
        sql = "SELECT COUNT(*) FROM messages WHERE conversation_id = ? AND message_type = 1"
        params = [conversation_id]

        if from_ts is not None:
            sql += " AND timestamp >= ?"
            params.append(from_ts)

        if to_ts is not None:
            sql += " AND timestamp <= ?"
            params.append(to_ts)

        # 总消息数
        cursor = get_db().execute(sql, tuple(params))
        total_message_count = cursor.fetchone()[0]

        # 从情感缓存获取统计
        sql = """
            SELECT
                COUNT(*) as total,
                SUM(CASE WHEN polarity = 1 THEN 1 ELSE 0 END) as positive,
                SUM(CASE WHEN polarity = -1 THEN 1 ELSE 0 END) as negative,
                SUM(CASE WHEN polarity = 0 THEN 1 ELSE 0 END) as neutral
            FROM sentiment_cache sc
            JOIN messages m ON sc.message_id = m.id
            WHERE m.conversation_id = ?
        """
        params = [conversation_id]

        if from_ts is not None:
            sql += " AND m.timestamp >= ?"
            params.append(from_ts)

        if to_ts is not None:
            sql += " AND m.timestamp <= ?"
            params.append(to_ts)

        cursor = get_db().execute(sql, tuple(params))
        row = cursor.fetchone()

        return {
            "total_message_count": total_message_count,
            "total_positive_count": row[1] or 0,
            "total_negative_count": row[2] or 0,
            "total_neutral_count": row[3] or 0
        }

    def collect_time_statistics(
        self,
        conversation_id: int,
        from_ts: Optional[int] = None,
        to_ts: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        收集时间统计信息

        Returns:
            {
                "conversation_start_timestamp": 1234567890,
                "conversation_end_timestamp": 1234567890,
                "conversation_duration_days": 123.5,
                "chat_days_count": 100
            }
        """
        # 构建查询
        # 注意：活跃天数按本地时区分桶（'localtime'），与情感共振维度的
        # active_days 口径一致；用 UTC 会在东八区把 00:00-08:00 的消息算进前一天
        sql = """
            SELECT
                MIN(timestamp) as start_ts,
                MAX(timestamp) as end_ts,
                COUNT(DISTINCT DATE(timestamp, 'unixepoch', 'localtime')) as chat_days
            FROM messages
            WHERE conversation_id = ? AND message_type = 1
        """
        params = [conversation_id]

        if from_ts is not None:
            sql += " AND timestamp >= ?"
            params.append(from_ts)

        if to_ts is not None:
            sql += " AND timestamp <= ?"
            params.append(to_ts)

        cursor = get_db().execute(sql, tuple(params))
        row = cursor.fetchone()

        start_ts = row[0]
        end_ts = row[1]
        chat_days = row[2]

        # 计算持续时间（天）
        duration_days = 0
        if start_ts and end_ts:
            duration_days = (end_ts - start_ts) / (24 * 3600)

        return {
            "conversation_start_timestamp": start_ts or 0,
            "conversation_end_timestamp": end_ts or 0,
            "conversation_duration_days": round(duration_days, 2),
            "chat_days_count": chat_days or 0
        }

    def collect_length_statistics(
        self,
        conversation_id: int,
        from_ts: Optional[int] = None,
        to_ts: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        收集消息长度统计信息

        Returns:
            {
                "total_characters": 12345,
                "average_message_length": 12.5
            }
        """
        # 从预处理缓存获取统计
        sql = """
            SELECT
                SUM(char_count) as total_chars,
                AVG(char_count) as avg_chars,
                COUNT(*) as count
            FROM message_preprocessed mp
            JOIN messages m ON mp.message_id = m.id
            WHERE m.conversation_id = ? AND mp.is_valid = 1
        """
        params = [conversation_id]

        if from_ts is not None:
            sql += " AND m.timestamp >= ?"
            params.append(from_ts)

        if to_ts is not None:
            sql += " AND m.timestamp <= ?"
            params.append(to_ts)

        cursor = get_db().execute(sql, tuple(params))
        row = cursor.fetchone()

        total_chars = row[0] or 0
        avg_chars = row[1] or 0

        return {
            "total_characters": total_chars,
            "average_message_length": round(avg_chars, 2)
        }


# ============================================================
# 交互对预处理服务 - 构建发言单元和交互对
# ============================================================
