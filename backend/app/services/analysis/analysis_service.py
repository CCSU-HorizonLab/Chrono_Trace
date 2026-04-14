"""历史数据分析服务"""
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime, timedelta
from ...db.connection import get_db
from .wordcloud_generator import WordCloudGenerator
from .preprocessing_service import PreprocessingService
import logging


logger = logging.getLogger(__name__)
class AnalysisService:
    """历史数据分析服务（统一分析入口）"""

    def __init__(self):
        pass  # get_db() removed for thread safety
        self.wordcloud_gen = WordCloudGenerator()
        self.preprocessor = PreprocessingService()

        # 延迟加载特征提取服务（避免循环导入）
        self._feature_service = None
    
    def get_conversation_list(self, account_wxid: str = "") -> Dict[str, Any]:
        """
        获取所有联系人列表（用于前端下拉选择）
        
        Returns:
            {
                "ok": True,
                "conversations": [
                    {
                        "id": 1,
                        "name": "张三",
                        "username": "wxid_xxx",
                        "message_count": 1234,
                        "last_message_time": "2025-01-07 15:30"
                    },
                    ...
                ]
            }
        """
        try:
            # 查询所有会话，关联联系人表获取备注名/昵称
            # 优先级: contacts.remark > contacts.nickname > conversations.display_name > conversations.username
            cursor = get_db().execute("""
                SELECT 
                    c.id,
                    c.username,
                    c.display_name,
                    COALESCE(
                        NULLIF(TRIM(ct.remark), ''),
                        NULLIF(TRIM(ct.nickname), ''),
                        NULLIF(TRIM(c.display_name), ''),
                        NULLIF(TRIM(c.username), ''),
                        '未知联系人'
                    ) as name,
                    c.message_count,
                    c.updated_at,
                    COALESCE(
                        NULLIF(TRIM(c.avatar_path), ''),
                        NULLIF(TRIM(ct.avatar_path), '')
                    ) as avatar
                FROM conversations c
                LEFT JOIN contacts ct
                    ON c.account_wxid = ct.account_wxid
                   AND c.username = ct.username
                WHERE c.is_deleted = 0
                    AND (? = '' OR c.account_wxid = ?)
                    AND c.message_count > 0
                ORDER BY c.updated_at DESC
            """, (account_wxid, account_wxid))
            
            conversations = []
            for row in cursor.fetchall():
                conversations.append({
                    "id": row[0],
                    "username": row[1],
                    "name": row[3],  # 优先使用备注名
                    "message_count": row[4],
                    "last_message_time": datetime.fromtimestamp(row[5]).strftime("%Y-%m-%d %H:%M"),
                    "avatar": row[6],
                })
            
            logger.debug(f"[DEBUG] 查询到 {len(conversations)} 个联系人")
            
            return {
                "ok": True,
                "conversations": conversations
            }
        except Exception as e:
            logger.error(f"[ERROR] 获取联系人列表失败: {e}")
            import traceback
            traceback.print_exc()
            return {
                "ok": False,
                "error": str(e),
                "conversations": []
            }
    
    def get_analysis(
        self, 
        conversation_id: int,
        from_date: str,
        to_date: str
    ) -> Dict[str, Any]:
        """
        获取分析数据（词云 + 统计）
        
        Args:
            conversation_id: 会话ID（必填）
            from_date: 开始日期 "2025-01-01"
            to_date: 结束日期 "2025-01-07"
        
        Returns:
            {
                "subject": {...},
                "timeseries": [],
                "wordcloud": [...]
            }
        """
        try:
            logger.info(f"[DEBUG] 开始分析: conversation_id={conversation_id}, from={from_date}, to={to_date}")
            
            # 1. 转换日期为时间戳
            from_ts = int(datetime.strptime(from_date, "%Y-%m-%d").timestamp())
            to_ts = int(datetime.strptime(to_date + " 23:59:59", "%Y-%m-%d %H:%M:%S").timestamp())
            
            logger.debug(f"[DEBUG] 时间戳范围: {from_ts} - {to_ts}")
            
            # 2. 获取会话详情
            subject_info = self._get_subject_info(conversation_id)
            if not subject_info:
                return {
                    "error": "会话不存在",
                    "subject": None,
                    "timeseries": [],
                    "wordcloud": []
                }
            
            logger.info(f"[DEBUG] 会话详情: {subject_info}")
            
            # 3. 使用预处理服务获取清洗后的消息（默认使用缓存）
            preprocessed = self.preprocessor.preprocess_conversation(
                conversation_id, from_ts, to_ts, use_cache=True
            )
            
            msg_count = preprocessed["total_messages"]
            valid_count = preprocessed["valid_messages"]
            
            logger.debug(f"[DEBUG] 查询到 {msg_count} 条消息, 有效消息 {valid_count} 条")
            logger.debug(f"[DEBUG] 预处理统计: {preprocessed['stats']}")
            logger.debug(f"[DEBUG] 缓存命中率: {preprocessed['stats'].get('cache_hit_rate', 0) * 100}%")
            
            # 4. 生成词云（使用清洗后的文本）
            cleaned_texts = [msg["cleaned_content"] for msg in preprocessed["cleaned_messages"]]
            wordcloud = self.wordcloud_gen.generate(cleaned_texts, top_n=50)
            sentiment_summary = self._build_sentiment_timeseries(conversation_id, from_ts, to_ts)
            
            logger.debug(f"[DEBUG] 生成词云: {len(wordcloud)} 个词")
            
            # 5. 组装返回数据
            return {
                "subject": {
                    "id": subject_info["id"],
                    "name": subject_info["name"],
                    "avatar": subject_info.get("avatar"),
                    "stats": {
                        "msgCount": msg_count,
                        "validMsgCount": valid_count,
                        "avgCharCount": preprocessed["stats"]["avg_char_count"],
                        "avgWordCount": preprocessed["stats"]["avg_word_count"],
                        "avgScore": sentiment_summary["avg_score"],
                        "maxDay": sentiment_summary["max_day"],
                        "minDay": sentiment_summary["min_day"]
                    }
                },
                "timeseries": sentiment_summary["timeseries"],
                "wordcloud": wordcloud
            }
        
        except Exception as e:
            logger.error(f"[ERROR] 分析失败: {e}")
            import traceback
            traceback.print_exc()
            return {
                "error": str(e),
                "subject": None,
                "timeseries": [],
                "wordcloud": []
            }
    
    def _build_sentiment_timeseries(
        self,
        conversation_id: int,
        from_ts: int,
        to_ts: int
    ) -> Dict[str, Any]:
        """按天聚合情感趋势数据"""
        cursor = get_db().execute("""
            SELECT
                DATE(m.timestamp, 'unixepoch', 'localtime') AS day,
                AVG(sc.intensity) AS avg_score,
                SUM(CASE WHEN sc.polarity = 1 THEN 1 ELSE 0 END) AS positive_count,
                SUM(CASE WHEN sc.polarity = 0 THEN 1 ELSE 0 END) AS neutral_count,
                SUM(CASE WHEN sc.polarity = -1 THEN 1 ELSE 0 END) AS negative_count,
                COUNT(*) AS msg_count,
                AVG(CASE WHEN m.is_sender = 1 THEN sc.intensity END) AS user_score,
                AVG(CASE WHEN m.is_sender = 0 THEN sc.intensity END) AS other_score
            FROM messages m
            INNER JOIN sentiment_cache sc ON sc.message_id = m.id
            WHERE m.conversation_id = ?
                AND m.message_type = 1
                AND m.timestamp BETWEEN ? AND ?
                AND m.content IS NOT NULL
                AND TRIM(m.content) != ''
            GROUP BY day
            ORDER BY day ASC
        """, (conversation_id, from_ts, to_ts))

        rows = cursor.fetchall()
        if not rows:
            return {
                "timeseries": [],
                "avg_score": 0.0,
                "max_day": None,
                "min_day": None
            }

        timeseries: List[Dict[str, Any]] = []
        total_weighted_score = 0.0
        total_count = 0
        max_row: Optional[Tuple[str, float]] = None
        min_row: Optional[Tuple[str, float]] = None

        for row in rows:
            day = str(row[0])
            avg_score = float(row[1] or 0.0)
            positive_count = int(row[2] or 0)
            neutral_count = int(row[3] or 0)
            negative_count = int(row[4] or 0)
            msg_count = int(row[5] or 0)
            user_score = None if row[6] is None else round(float(row[6]), 3)
            other_score = None if row[7] is None else round(float(row[7]), 3)

            timeseries.append({
                "ts": day,
                "score": round(avg_score, 3),
                "positive": positive_count,
                "neutral": neutral_count,
                "negative": negative_count,
                "msgCount": msg_count,
                "userScore": user_score,
                "otherScore": other_score
            })

            total_weighted_score += avg_score * msg_count
            total_count += msg_count

            if max_row is None or avg_score > max_row[1]:
                max_row = (day, avg_score)
            if min_row is None or avg_score < min_row[1]:
                min_row = (day, avg_score)

        return {
            "timeseries": timeseries,
            "avg_score": round(total_weighted_score / total_count, 3) if total_count else 0.0,
            "max_day": max_row[0] if max_row else None,
            "min_day": min_row[0] if min_row else None
        }

    def _get_subject_info(self, conversation_id: int) -> Optional[Dict]:
        """获取会话详情"""
        cursor = get_db().execute("""
            SELECT 
                c.id,
                c.username,
                c.account_wxid,
                COALESCE(
                    NULLIF(TRIM(ct.remark), ''),
                    NULLIF(TRIM(ct.nickname), ''),
                    NULLIF(TRIM(c.display_name), ''),
                    NULLIF(TRIM(c.username), ''),
                    '未知联系人'
                ) as name,
                COALESCE(
                    NULLIF(TRIM(c.avatar_path), ''),
                    NULLIF(TRIM(ct.avatar_path), '')
                ) as avatar
            FROM conversations c
            LEFT JOIN contacts ct
                ON c.account_wxid = ct.account_wxid
               AND c.username = ct.username
            WHERE c.id = ?
        """, (conversation_id,))
        
        row = cursor.fetchone()
        if not row:
            return None
        
        return {
            "id": row[0],
            "username": row[1],
            "account_wxid": row[2],
            "name": row[3],
            "avatar": row[4]
        }
    
    def _get_messages(
        self, 
        conversation_id: int, 
        from_ts: int, 
        to_ts: int,
        limit: int = 10000
    ) -> List[str]:
        """获取消息内容列表"""
        cursor = get_db().execute("""
            SELECT content
            FROM messages
            WHERE conversation_id = ?
                AND timestamp BETWEEN ? AND ?
                AND message_type = 1
                AND content IS NOT NULL
                AND content != ''
            ORDER BY timestamp DESC
            LIMIT ?
        """, (conversation_id, from_ts, to_ts, limit))
        
        messages = [row[0] for row in cursor.fetchall()]
        return messages

    # =========================================================================
    # 特征提取服务集成
    # =========================================================================

    def _get_feature_service(self):
        """延迟加载特征提取服务"""
        if self._feature_service is None:
            from .feature_extraction_service import FeatureExtractionService
            self._feature_service = FeatureExtractionService()
        return self._feature_service

    def extract_features(self, conversation_id: int, config: Optional[Dict] = None) -> Dict[str, Any]:
        """
        提取对话特征（会话切分、响应时间、主动性、字数统计）

        Args:
            conversation_id: 对话ID
            config: 可选配置参数

        Returns:
            特征提取结果
        """
        from .feature_extraction_config import FeatureExtractionConfig

        service = self._get_feature_service()
        if config:
            base_config = FeatureExtractionConfig.from_settings()
            service.config = FeatureExtractionConfig(**{
                **base_config.__dict__,
                **config,
            })
            service.config.validate()
        return service.extract_features(conversation_id)

    def get_feature_extraction_progress(self, task_id: str) -> Dict[str, Any]:
        """
        查询特征提取任务进度

        Args:
            task_id: 任务ID

        Returns:
            任务进度信息
        """
        service = self._get_feature_service()
        return service.get_task_progress(task_id)

    def get_sessions(
        self,
        conversation_id: int,
        limit: int = 50,
        offset: int = 0
    ) -> List[Dict[str, Any]]:
        """
        获取会话列表

        Args:
            conversation_id: 对话ID
            limit: 每页数量
            offset: 偏移量

        Returns:
            会话列表
        """
        service = self._get_feature_service()

        # 从数据库查询会话
        cursor = get_db().execute("""
            SELECT id, conversation_id, start_time, end_time, message_count, initiator, source
            FROM sessions
            WHERE conversation_id = ?
            ORDER BY start_time DESC
            LIMIT ? OFFSET ?
        """, (conversation_id, limit, offset))

        sessions = []
        for row in cursor.fetchall():
            sessions.append({
                "id": row[0],
                "conversation_id": row[1],
                "start_time": row[2],
                "end_time": row[3],
                "message_count": row[4],
                "initiator": row[5],
                "source": row[6]
            })

        return sessions

    def get_response_time_stats(self, conversation_id: int) -> Dict[str, Any]:
        """
        获取响应时间统计

        Args:
            conversation_id: 对话ID

        Returns:
            响应时间统计数据
        """
        cursor = get_db().execute("""
            SELECT
                COUNT(*) as count,
                AVG(response_time_seconds) as avg,
                MIN(response_time_seconds) as min,
                MAX(response_time_seconds) as max
            FROM response_times
            WHERE conversation_id = ?
                AND is_abnormal = 0
        """, (conversation_id,))

        row = cursor.fetchone()

        # 计算中位数
        cursor = get_db().execute("""
            SELECT response_time_seconds
            FROM response_times
            WHERE conversation_id = ?
                AND is_abnormal = 0
            ORDER BY response_time_seconds
        """, (conversation_id,))
        all_times = [row[0] for row in cursor.fetchall()]
        median = all_times[len(all_times) // 2] if all_times else None

        # 统计异常值数量
        cursor = get_db().execute("""
            SELECT COUNT(*)
            FROM response_times
            WHERE conversation_id = ?
                AND is_abnormal = 1
        """, (conversation_id,))
        abnormal_count = cursor.fetchone()[0]

        # 计算分布直方图
        # 分段: <1m, 1-10m, 10-30m, 30m-1h, 1h-6h, 6h-24h, >1d
        distribution = {
            "<1m": 0, "1m-10m": 0, "10m-30m": 0, "30m-1h": 0,
            "1h-6h": 0, "6h-24h": 0, ">1d": 0
        }

        # 为了更准确的分布，我们需要再次查询所有数据进行分桶
        # 注意: 如果可以，最好使用 SQL Case When 在数据库层面做统计，但 SQLite/MySQL 语法略有不同
        # 这里为了兼容性和简单起见，利用 Python 处理 (假设数据量不是特别巨大，或者复用上面的 all_times)
        
        # 如果上面计算中位数没有获取 all_times (比如 row[0] 为 0)，需要处理空情况
        if not all_times:
            # 尝试重新获取一次，或者确定上面逻辑已覆盖
            pass 
        
        for t in all_times:
            if t < 60:
                distribution["<1m"] += 1
            elif t < 600:
                distribution["1m-10m"] += 1
            elif t < 1800:
                distribution["10m-30m"] += 1
            elif t < 3600:
                distribution["30m-1h"] += 1
            elif t < 21600:
                distribution["1h-6h"] += 1
            elif t < 86400:
                distribution["6h-24h"] += 1
            else:
                distribution[">1d"] += 1

        return {
            "count": row[0] or 0,
            "avg": row[1],
            "median": median,
            "min": row[2],
            "max": row[3],
            "stddev": None,  # 暂不计算标准差
            "abnormal_count": abnormal_count,
            "distribution": distribution
        }

    def get_initiative_stats(self, conversation_id: int) -> Dict[str, Any]:
        """
        获取主动性统计

        Args:
            conversation_id: 对话ID

        Returns:
            主动性统计数据
        """
        cursor = get_db().execute("""
            SELECT total_sessions, user_initiated_sessions, other_initiated_sessions, initiative_rate
            FROM initiative_stats
            WHERE conversation_id = ?
        """, (conversation_id,))

        row = cursor.fetchone()
        if not row:
            return {
                "total_sessions": 0,
                "user_initiated_sessions": 0,
                "other_initiated_sessions": 0,
                "initiative_rate": 0.0,
                "interpretation": "无数据"
            }

        return {
            "total_sessions": row[0],
            "user_initiated_sessions": row[1],
            "other_initiated_sessions": row[2],
            "initiative_rate": row[3],
            "interpretation": f"对方主动发起{row[3] * 100:.1f}%的会话"
        }

    def get_word_counts(self, conversation_id: int, by_session: bool = False) -> Dict[str, Any]:
        """
        获取字数统计

        Args:
            conversation_id: 对话ID
            by_session: 是否按会话统计

        Returns:
            字数统计数据
        """
        if by_session:
            # 按会话统计
            cursor = get_db().execute("""
                SELECT
                    session_id,
                    user_char_count,
                    other_char_count,
                    char_ratio
                FROM word_counts
                WHERE conversation_id = ?
                    AND session_id IS NOT NULL
                ORDER BY session_id
            """, (conversation_id,))

            by_session_data = []
            for row in cursor.fetchall():
                by_session_data.append({
                    "session_id": row[0],
                    "user_char_count": row[1],
                    "other_char_count": row[2],
                    "char_ratio": row[3]
                })

            return {
                "overall": {},
                "by_session": by_session_data
            }
        else:
            # 整体统计
            cursor = get_db().execute("""
                SELECT
                    user_char_count,
                    other_char_count,
                    char_ratio
                FROM word_counts
                WHERE conversation_id = ?
                    AND session_id IS NULL
            """, (conversation_id,))

            row = cursor.fetchone()
            if not row:
                return {
                    "overall": {
                        "user_char_count": 0,
                        "other_char_count": 0,
                        "char_ratio": 0.0,
                        "interpretation": "无数据"
                    },
                    "by_session": []
                }

            ratio = row[2] or 0
            if ratio >= 1:
                interpretation = f"对方投入的字数是您的{ratio:.2f}倍"
            else:
                interpretation = f"您投入的字数是对方的{1/ratio:.2f}倍" if ratio > 0 else "无对比数据"

            return {
                "overall": {
                    "user_char_count": row[0],
                    "other_char_count": row[1],
                    "char_ratio": ratio,
                    "interpretation": interpretation
                },
                "by_session": []
            }

    def get_activity_calendar(self, conversation_id: int, year: Optional[int] = None) -> Dict[str, Any]:
        """
        获取按天聚合的活跃日历数据。

        Args:
            conversation_id: 对话ID
            year: 可选年份；不传时默认使用最新有数据的年份
        """
        cursor = get_db().execute("""
            SELECT start_time, end_time, message_count, initiator
            FROM sessions
            WHERE conversation_id = ?
            ORDER BY start_time ASC
        """, (conversation_id,))

        rows = cursor.fetchall()

        global_first_session_start_time = None
        global_peak_session = {"start_time": None, "message_count": 0}

        if not rows:
            default_year = year or datetime.now().year
            return {
                "year": default_year,
                "years": [default_year],
                "entries": [],
                "summary": {
                    "active_days": 0,
                    "total_messages": 0,
                    "current_streak": 0,
                    "longest_streak": 0,
                    "peak_day": None,
                    "global_first_session_start_time": None,
                    "global_peak_session": None
                },
                "max_activity_score": 0
            }

        daily_all: Dict[str, Dict[str, Any]] = {}
        years = set()

        for row in rows:
            start_time = row[0]
            end_time = row[1]
            message_count = row[2] or 0
            initiator = row[3] or "other"
            start_dt = datetime.fromtimestamp(start_time)
            date_str = start_dt.strftime("%Y-%m-%d")
            years.add(start_dt.year)
            
            if global_first_session_start_time is None:
                global_first_session_start_time = start_time
            if message_count > global_peak_session["message_count"]:
                global_peak_session["message_count"] = message_count
                global_peak_session["start_time"] = start_time

            if date_str not in daily_all:
                daily_all[date_str] = {
                    "date": date_str,
                    "message_count": 0,
                    "session_count": 0,
                    "active_duration_seconds": 0,
                    "first_timestamp": start_time,
                    "last_timestamp": end_time or start_time,
                    "user_initiated_sessions": 0,
                    "other_initiated_sessions": 0,
                }

            day = daily_all[date_str]
            day["message_count"] += message_count
            day["session_count"] += 1
            day["active_duration_seconds"] += max(0, (end_time or start_time) - start_time)
            day["first_timestamp"] = min(day["first_timestamp"], start_time)
            day["last_timestamp"] = max(day["last_timestamp"], end_time or start_time)

            if initiator == "user":
                day["user_initiated_sessions"] += 1
            else:
                day["other_initiated_sessions"] += 1

        available_years = sorted(years)
        selected_year = year if year in years else available_years[-1]

        selected_entries = [
            entry for entry in daily_all.values()
            if int(entry["date"][:4]) == selected_year
        ]
        selected_entries.sort(key=lambda item: item["date"])

        max_messages = max((entry["message_count"] for entry in selected_entries), default=0)
        max_sessions = max((entry["session_count"] for entry in selected_entries), default=0)
        max_duration = max((entry["active_duration_seconds"] for entry in selected_entries), default=0)

        max_activity_score = 0
        for entry in selected_entries:
            message_ratio = entry["message_count"] / max_messages if max_messages else 0
            session_ratio = entry["session_count"] / max_sessions if max_sessions else 0
            duration_ratio = entry["active_duration_seconds"] / max_duration if max_duration else 0
            raw_score = (session_ratio * 0.45) + (message_ratio * 0.4) + (duration_ratio * 0.15)
            activity_score = round(raw_score * 100)

            entry["activity_score"] = activity_score
            entry["activity_level"] = min(4, max(1, int(raw_score * 4 + 0.9999)))
            entry["first_time"] = datetime.fromtimestamp(entry["first_timestamp"]).strftime("%H:%M")
            entry["last_time"] = datetime.fromtimestamp(entry["last_timestamp"]).strftime("%H:%M")
            max_activity_score = max(max_activity_score, activity_score)

        active_dates = [datetime.strptime(entry["date"], "%Y-%m-%d").date() for entry in selected_entries]
        longest_streak = 0
        running_streak = 0
        previous_date = None

        for current_date in active_dates:
            if previous_date and current_date == previous_date + timedelta(days=1):
                running_streak += 1
            else:
                running_streak = 1
            longest_streak = max(longest_streak, running_streak)
            previous_date = current_date

        peak_entry = None
        if selected_entries:
            peak_entry = max(
                selected_entries,
                key=lambda entry: (entry["activity_score"], entry["message_count"], entry["session_count"])
            )

        return {
            "year": selected_year,
            "years": available_years,
            "entries": selected_entries,
            "summary": {
                "active_days": len(selected_entries),
                "total_messages": sum(entry["message_count"] for entry in selected_entries),
                "current_streak": running_streak if active_dates else 0,
                "longest_streak": longest_streak,
                "peak_day": {
                    "date": peak_entry["date"],
                    "message_count": peak_entry["message_count"],
                    "session_count": peak_entry["session_count"],
                    "activity_score": peak_entry["activity_score"]
                } if peak_entry else None,
                "global_first_session_start_time": global_first_session_start_time * 1000 if global_first_session_start_time else None,
                "global_peak_session": {
                    "start_time": global_peak_session["start_time"] * 1000,
                    "message_count": global_peak_session["message_count"]
                } if global_peak_session["start_time"] else None
            },
            "max_activity_score": max_activity_score
        }

    def reanalyze(self, conversation_id: int) -> Dict[str, Any]:
        """
        重新分析对话（删除旧数据+重新提取特征）

        Args:
            conversation_id: 对话ID

        Returns:
            重新分析结果
        """
        service = self._get_feature_service()
        service.delete_analysis_data(conversation_id)
        return service.extract_features(conversation_id)

