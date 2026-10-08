"""历史分析读取（会话/响应时间/主动性/字数/日历）——从 bridge.py 拆出（步骤 3 mixin）。

Bridge 继承此 Mixin，方法名不变、前端 API 面与测试零破坏。
"""
from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)


class AnalysisReadApiMixin:
    """历史分析读取（会话/响应时间/主动性/字数/日历）"""

    def get_sessions(self, conversation_id: int, limit: int = 50, offset: int = 0) -> dict:
        """
        获取会话列表

        Args:
            conversation_id: 对话ID
            limit: 返回数量限制
            offset: 分页偏移量

        Returns:
            {
                "success": True,
                "data": {
                    "sessions": [...],
                    "total": 150,
                    "limit": 50,
                    "offset": 0
                }
            }
        """
        try:
            from ...db.connection import get_db

            db = get_db()

            # 查询总数
            count_cursor = db.execute(
                "SELECT COUNT(*) as total FROM sessions WHERE conversation_id = ?",
                (conversation_id,)
            )
            total = count_cursor.fetchone()["total"]

            # 查询会话列表
            cursor = db.execute("""
                SELECT id, conversation_id, start_time, end_time, message_count, initiator, source
                FROM sessions
                WHERE conversation_id = ?
                ORDER BY start_time DESC
                LIMIT ? OFFSET ?
            """, (conversation_id, limit, offset))

            rows = cursor.fetchall()
            sessions = [dict(row) for row in rows]

            # 添加duration字段（分钟）
            for session in sessions:
                duration_seconds = session["end_time"] - session["start_time"]
                session["duration_minutes"] = round(duration_seconds / 60, 1)

            return {
                "success": True,
                "data": {
                    "sessions": sessions,
                    "total": total,
                    "limit": limit,
                    "offset": offset
                }
            }
        except Exception as e:
            logger.error(f"[Bridge] 获取会话列表失败: {e}")
            return {
                "success": False,
                "error": str(e)
            }

    def get_session_messages(self, session_id: int) -> dict:
        """
        获取特定会话的消息列表
        """
        try:
            from ...db.connection import get_db
            db = get_db()
            
            # 查询会话信息以获得时间范围和conversation_id
            session_cursor = db.execute(
                "SELECT conversation_id, start_time, end_time FROM sessions WHERE id = ?",
                (session_id,)
            )
            session = session_cursor.fetchone()
            if not session:
                return {"success": False, "error": "会话不存在"}
                
            # 查询该时间范围内的消息
            cursor = db.execute("""
                SELECT id, sender, is_sender, content, timestamp as create_time
                FROM messages
                WHERE conversation_id = ? AND timestamp >= ? AND timestamp <= ?
                ORDER BY timestamp ASC
            """, (session["conversation_id"], session["start_time"], session["end_time"]))
            
            rows = cursor.fetchall()
            messages = []
            for row in rows:
                msg = dict(row)
                # 处理 sender_name
                is_me = msg["is_sender"] == 1
                sender_name = msg.get("sender")
                if not sender_name:
                    sender_name = "我" if is_me else "对方"
                
                messages.append({
                    "id": msg["id"],
                    "sender_name": sender_name,
                    "content": msg["content"],
                    "create_time": msg["create_time"],
                    "is_me": is_me
                })
                
            return {
                "success": True,
                "data": {
                    "messages": messages
                }
            }
        except Exception as e:
            logger.error(f"[Bridge] 获取会话消息失败: {e}")
            return {
                "success": False,
                "error": str(e)
            }

    def get_response_times(self, conversation_id: int) -> dict:
        """
        获取响应时间统计

        Args:
            conversation_id: 对话ID

        Returns:
            {
                "success": True,
                "data": {
                    "count": 250,
                    "avg": 180.5,
                    "median": 120.0,
                    "min": 15.0,
                    "max": 3600.0,
                    "stddev": 300.2,
                    "abnormal_count": 5
                }
            }
        """
        try:
            from ...services.analysis.analysis_service import AnalysisService

            service = AnalysisService()
            stats = service.get_response_time_stats(conversation_id)

            return {
                "success": True,
                "data": stats
            }
        except Exception as e:
            logger.error(f"[Bridge] 获取响应时间统计失败: {e}")
            return {
                "success": False,
                "error": str(e)
            }

    def get_initiative_stats(self, conversation_id: int) -> dict:
        """
        获取主动性统计

        Args:
            conversation_id: 对话ID

        Returns:
            {
                "success": True,
                "data": {
                    "total_sessions": 100,
                    "user_initiated_sessions": 55,
                    "other_initiated_sessions": 45,
                    "initiative_rate": 0.45,
                    "interpretation": "对方主动发起45%的会话，您更主动"
                }
            }
        """
        try:
            from ...db.connection import get_db

            db = get_db()

            cursor = db.execute("""
                SELECT total_sessions, user_initiated_sessions, other_initiated_sessions, initiative_rate
                FROM initiative_stats
                WHERE conversation_id = ?
            """, (conversation_id,))

            row = cursor.fetchone()

            if not row:
                return {
                    "success": True,
                    "data": {
                        "total_sessions": 0,
                        "user_initiated_sessions": 0,
                        "other_initiated_sessions": 0,
                        "initiative_rate": 0.0,
                        "interpretation": "无会话数据"
                    }
                }

            initiative_rate = row["initiative_rate"]
            if initiative_rate > 0.5:
                interpretation = f"对方主动发起{initiative_rate:.1%}的会话，对方更主动"
            elif initiative_rate < 0.5:
                interpretation = f"对方主动发起{initiative_rate:.1%}的会话，您更主动"
            else:
                interpretation = f"对方主动发起{initiative_rate:.1%}的会话，双方平衡"

            return {
                "success": True,
                "data": {
                    "total_sessions": row["total_sessions"],
                    "user_initiated_sessions": row["user_initiated_sessions"],
                    "other_initiated_sessions": row["other_initiated_sessions"],
                    "initiative_rate": initiative_rate,
                    "interpretation": interpretation
                }
            }
        except Exception as e:
            logger.error(f"[Bridge] 获取主动性统计失败: {e}")
            return {
                "success": False,
                "error": str(e)
            }

    def get_word_counts(self, conversation_id: int, by_session: bool = False) -> dict:
        """
        获取字数统计

        Args:
            conversation_id: 对话ID
            by_session: 是否按会话分组

        Returns:
            {
                "success": True,
                "data": {
                    "overall": {
                        "user_char_count": 10000,
                        "other_char_count": 15000,
                        "char_ratio": 1.5,
                        "interpretation": "对方投入的字数是您的1.5倍"
                    },
                    "by_session": [...]
                }
            }
        """
        try:
            from ...db.connection import get_db

            db = get_db()

            # 查询整体统计
            overall_cursor = db.execute("""
                SELECT user_char_count, other_char_count, char_ratio
                FROM word_counts
                WHERE conversation_id = ? AND session_id IS NULL
            """, (conversation_id,))

            overall_row = overall_cursor.fetchone()

            if not overall_row:
                return {
                    "success": True,
                    "data": {
                        "overall": {
                            "user_char_count": 0,
                            "other_char_count": 0,
                            "char_ratio": 0,
                            "interpretation": "无字数数据"
                        },
                        "by_session": []
                    }
                }

            user_chars = overall_row["user_char_count"]
            other_chars = overall_row["other_char_count"]
            char_ratio = overall_row["char_ratio"] or 0

            if user_chars == 0 and other_chars == 0:
                interpretation = "无字数数据"
            elif char_ratio >= 1:
                interpretation = f"对方投入的字数是您的{char_ratio:.2f}倍"
            elif char_ratio > 0:
                interpretation = f"您投入的字数是对方的{1/char_ratio:.2f}倍"
            else:
                interpretation = "无对比数据"

            result = {
                "success": True,
                "data": {
                    "overall": {
                        "user_char_count": user_chars,
                        "other_char_count": other_chars,
                        "char_ratio": round(char_ratio, 2),
                        "interpretation": interpretation
                    },
                    "by_session": []
                }
            }

            # 如果需要按会话统计
            if by_session:
                session_cursor = db.execute("""
                    SELECT session_id, user_char_count, other_char_count, char_ratio
                    FROM word_counts
                    WHERE conversation_id = ? AND session_id IS NOT NULL
                    ORDER BY session_id ASC
                """, (conversation_id,))

                session_rows = session_cursor.fetchall()
                result["data"]["by_session"] = [
                    {
                        "session_id": row["session_id"],
                            "word_count": {
                                "user_char_count": row["user_char_count"],
                                "other_char_count": row["other_char_count"],
                                "char_ratio": round(row["char_ratio"] or 0, 2)
                            }
                        }
                    for row in session_rows
                ]

            return result
        except Exception as e:
            logger.error(f"[Bridge] 获取字数统计失败: {e}")
            return {
                "success": False,
                "error": str(e)
            }

    def get_activity_calendar(self, conversation_id: int, year: Optional[int] = None) -> dict:
        """
        获取互动活跃日历数据。
        """
        try:
            from ...services.analysis.analysis_service import AnalysisService

            service = AnalysisService()
            data = service.get_activity_calendar(conversation_id, year)

            return {
                "success": True,
                "data": data
            }
        except Exception as e:
            logger.error(f"[Bridge] 获取活跃日历失败: {e}")
            return {
                "success": False,
                "error": str(e)
            }

    def reanalyze(self, conversation_id: int) -> dict:
        """
        重新分析对话（删除旧数据+重新提取特征）

        Args:
            conversation_id: 对话ID

        Returns:
            {
                "success": True,
                "data": {
                    "task_id": "extract_42_xxx",
                    "status": "started",
                    "message": "Re-analysis started"
                }
            }
        """
        try:
            logger.debug(f"[Bridge] 重新分析: conversation_id={conversation_id}")

            service = self._get_feature_service()

            # 删除旧数据
            service.delete_analysis_data(conversation_id)

            # 重新提取
            result = service.extract_features(conversation_id)

            return {
                "success": True,
                "data": {
                    "task_id": result["task_id"],
                    "status": "completed",
                    "message": "Re-analysis completed"
                }
            }
        except Exception as e:
            import traceback
            logger.error(f"[Bridge] 重新分析失败: {e}")
            traceback.print_exc()
            return {
                "success": False,
                "error": str(e)
            }

