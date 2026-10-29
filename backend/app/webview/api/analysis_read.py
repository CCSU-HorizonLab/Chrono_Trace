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

    def get_conversation_span(self, conversation_id: int) -> dict:
        """
        获取会话消息时间跨度（首条/末条消息日期）。

        「全部」快捷键与时光深度默认窗用它替代 2000-01-01 占位，
        让日期输入框显示真实的首消息日期。走 (conversation_id, timestamp)
        索引，MIN/MAX 微秒级。

        Returns:
            {"success": True, "data": {"from_date": "2024-03-02", "to_date": "2026-10-20"}}
            无消息时 data 为 None
        """
        try:
            if not conversation_id:
                return {"success": False, "error": "缺少参数: conversation_id"}
            from datetime import datetime

            from ...db.connection import get_db

            row = get_db().execute(
                "SELECT MIN(timestamp) AS first_ts, MAX(timestamp) AS last_ts"
                " FROM messages WHERE conversation_id = ?",
                (conversation_id,),
            ).fetchone()
            if not row or row["first_ts"] is None:
                return {"success": True, "data": None}
            return {
                "success": True,
                "data": {
                    "from_date": datetime.fromtimestamp(int(row["first_ts"])).strftime("%Y-%m-%d"),
                    "to_date": datetime.fromtimestamp(int(row["last_ts"])).strftime("%Y-%m-%d"),
                },
            }
        except Exception as e:
            logger.error(f"[Bridge] 获取会话时间跨度失败: {e}")
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

    def get_milestone_messages(self, conversation_id: int, start_ms: int, end_ms: int = 0, limit: int = 200) -> dict:
        """记忆相框回顾：按锚点时间取当时的消息原文。

        end_ms > start_ms 时取 [start_ms, end_ms) 窗口（如情绪高光所在的某一天）；
        否则按 start_ms 容差 ±120s 匹配 sessions 表的会话，取该会话完整时间范围
        （最早留痕/高密度互动的锚点即会话 start_time，由日历摘要换算而来）。
        入参毫秒（前端约定），库内 messages.timestamp / sessions.start_time 均为秒。
        """
        try:
            from ...db.connection import get_db
            db = get_db()

            start_s = int(start_ms) // 1000
            if end_ms and int(end_ms) > int(start_ms):
                start_bound = start_s
                end_bound = int(end_ms) // 1000
            else:
                session = db.execute(
                    "SELECT start_time, end_time FROM sessions "
                    "WHERE conversation_id = ? AND start_time BETWEEN ? AND ?",
                    (conversation_id, start_s - 120, start_s + 120),
                ).fetchone()
                if not session:
                    return {"ok": False, "error": "未找到锚点对应的会话记录"}
                start_bound = session["start_time"]
                end_bound = session["end_time"]

            total = db.execute(
                "SELECT COUNT(*) AS n FROM messages "
                "WHERE conversation_id = ? AND timestamp >= ? AND timestamp < ?",
                (conversation_id, start_bound, end_bound),
            ).fetchone()["n"]

            capped = max(1, min(int(limit), 500))
            cursor = db.execute("""
                SELECT id, sender, is_sender, content, timestamp
                FROM messages
                WHERE conversation_id = ? AND timestamp >= ? AND timestamp < ?
                ORDER BY timestamp ASC
                LIMIT ?
            """, (conversation_id, start_bound, end_bound, capped))
            messages = []
            for row in cursor.fetchall():
                is_me = row["is_sender"] == 1
                sender_name = row["sender"] or ("我" if is_me else "对方")
                messages.append({
                    "id": row["id"],
                    "sender_name": sender_name,
                    "content": row["content"],
                    "create_time": row["timestamp"],
                    "is_me": is_me,
                })

            return {
                "ok": True,
                "messages": messages,
                "total": total,
                "truncated": total > len(messages),
                "start_time": start_bound,
                "end_time": end_bound,
            }
        except Exception as e:
            logger.error(f"[Bridge] 获取记忆相框消息失败: {e}")
            return {"ok": False, "error": str(e)}

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
                    "interpretation": "对方发起 45% 的会话——基本对半，谈不上谁更主动"
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
            # 口径：与对半不可区分（二项检验）或效应量可忽略（h<0.2）
            # 时判「均衡」，不下「谁更主动」的定性；差异显著才分级表述
            from ...services.analysis.initiative_balance import (
                BAND_BALANCED,
                BAND_INSUFFICIENT,
                BAND_OTHER_DOMINANT,
                BAND_OTHER_LEANS,
                BAND_SELF_DOMINANT,
                BAND_SELF_LEANS,
                classify_initiative,
            )

            total_sessions = row["total_sessions"]
            other_pct = initiative_rate
            self_pct = 1.0 - initiative_rate
            band = classify_initiative(
                total_sessions, row["other_initiated_sessions"]
            )
            if band == BAND_INSUFFICIENT:
                interpretation = (
                    f"样本还太少（{total_sessions} 场会话），先不下结论"
                )
            elif band == BAND_BALANCED:
                interpretation = (
                    f"对方发起 {other_pct:.0%} · 您发起 {self_pct:.0%}"
                    "——基本对半，谈不上谁更主动"
                )
            elif band == BAND_OTHER_LEANS:
                interpretation = f"对方发起 {other_pct:.0%} 的会话，主动性略偏向对方"
            elif band == BAND_SELF_LEANS:
                interpretation = f"您发起 {self_pct:.0%} 的会话，主动性略偏向您"
            elif band == BAND_OTHER_DOMINANT:
                interpretation = f"对方发起 {other_pct:.0%} 的会话，主动性明显在对方一侧"
            else:  # BAND_SELF_DOMINANT
                interpretation = f"您发起 {self_pct:.0%} 的会话，主动性明显在您一侧"

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

            # 并发守卫（与 start_feature_extraction 同口径）：同会话已有
            # 运行中的提取时拒绝——此前此处无守卫直接删旧数据再同步提取，
            # 会与运行中的任务互相删数据（W5）
            running_task = service.find_running_task(conversation_id)
            if running_task:
                return {
                    "success": False,
                    "error": "该会话已有进行中的提取任务，请等待完成后再重新分析",
                }

            import threading
            import time as _time
            import uuid as _uuid

            task_id = f"extract_{conversation_id}_{int(_time.time())}_{_uuid.uuid4().hex[:6]}"
            # 取消事件按 task_id 隔离（W5，与 start_feature_extraction 共用注册表）
            cancel_event = threading.Event()
            self._analysis_cancel_events[task_id] = cancel_event
            # 立即注册任务占位：线程内删除阶段（extract_features 步骤 0
            # 之前的窗口）find_running_task 仍得 None，两道互斥门禁都会
            # 放行第二个同会话管线交错删写（W5 收尾）
            service.register_task(task_id, message="准备重新分析")

            def _run_reanalyze():
                try:
                    # 删旧数据由 extract_features 步骤 0 统一执行（此前
                    # 线程内先删一遍属同步时代残留，且放大了无注册窗口）
                    service.extract_features(
                        conversation_id, cancel_event=cancel_event, task_id=task_id
                    )
                except Exception as e:
                    logger.error(f"[Bridge] 重新分析线程失败: {e}")
                    import traceback
                    traceback.print_exc()
                finally:
                    self._analysis_cancel_events.pop(task_id, None)

            threading.Thread(
                target=_run_reanalyze,
                daemon=True,
                name=f"reanalyze-{conversation_id}",
            ).start()

            return {
                "success": True,
                "data": {
                    "task_id": task_id,
                    "status": "started",
                    "message": "Re-analysis started"
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

    def get_group_stats(self, conversation_id: int, start: int = None, end: int = None) -> dict:
        """群聊发言统计（纯本地：按成员消息数/字数/占比/我的排名/时段/高频词）"""
        try:
            from ...services.analysis.group_summary_service import (
                GroupSummaryError,
                GroupSummaryService,
            )

            stats = GroupSummaryService().get_group_stats(
                int(conversation_id),
                start=int(start) if start else None,
                end=int(end) if end else None,
            )
            return {"ok": True, **stats}
        except GroupSummaryError as e:
            return {"ok": False, "error": str(e)}
        except Exception as e:
            logger.error(f"[Bridge] 群聊统计失败: {e}")
            return {"ok": False, "error": f"群聊统计失败：{e}"}

    def generate_group_summary(self, conversation_id: int, days: int = 7) -> dict:
        """生成群聊日报（近 N 天分段 + LLM 总结；无模型时降级为仅统计）"""
        try:
            from ...services.analysis.group_summary_service import (
                GroupSummaryError,
                GroupSummaryService,
            )

            result = GroupSummaryService().generate_group_summary(
                int(conversation_id), int(days or 7)
            )
            return result
        except GroupSummaryError as e:
            return {"ok": False, "error": str(e)}
        except Exception as e:
            logger.error(f"[Bridge] 群日报生成失败: {e}")
            return {"ok": False, "error": f"群日报生成失败：{e}"}

    def cancel_group_summary(self, conversation_id: int) -> dict:
        """取消该群进行中的日报生成（下一次轮询点生效）。"""
        try:
            from ...services.realtime.llm_http import request_llm_cancel

            from ...services.analysis.group_summary_service import GS_CANCEL_SCOPE

            request_llm_cancel(GS_CANCEL_SCOPE, int(conversation_id))
            return {"ok": True}
        except Exception as e:
            logger.error(f"[Bridge] 取消群日报失败: {e}")
            return {"ok": False, "error": str(e)}

