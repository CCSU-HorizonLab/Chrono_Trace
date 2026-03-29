"""特征提取服务 - 会话切分、响应时间计算、主动性统计、字数统计"""
import logging
import statistics
import time
import threading
import threading
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Any, Optional, Tuple

from .feature_extraction_config import FeatureExtractionConfig
from .preprocessing_service import PreprocessingService
from .sentiment_service import SentimentService
from ...db.connection import get_db, batch_insert, execute_transaction


# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class FeatureExtractionService:
    """特征提取服务主类"""

    def __init__(self, config: Optional[FeatureExtractionConfig] = None):
        """
        初始化特征提取服务

        Args:
            config: 配置对象，默认使用from_settings()加载
        """
        self.config = config or FeatureExtractionConfig.from_settings()
        self.config.validate()

        pass  # get_db() removed for thread safety
        self.preprocessor = PreprocessingService()

        # 缓存预处理服务实例（避免重复加载模型）
        self._pair_service = None
        self._session_manager = None

        # 任务状态管理（用于进度查询）
        self._task_status: Dict[str, Dict] = {}

    def _apply_analysis_device_mode(self) -> None:
        """Align sentiment-dependent helpers with the configured device mode."""
        SentimentService().configure_device_mode(self.config.analysis_device_mode)

    # =========================================================================
    # 主入口
    # =========================================================================

    def extract_features(self, conversation_id: int, cancel_event: Optional[threading.Event] = None) -> Dict[str, Any]:
        """
        执行完整的特征提取流程

        Args:
            conversation_id: 对话ID

        Returns:
            提取结果字典，包含sessions, response_times, initiative_stats, word_counts
        """
        #logger.info(f"开始特征提取: conversation_id={conversation_id}")

        self._apply_analysis_device_mode()

        task_id = f"extract_{conversation_id}_{int(time.time())}"
        self._task_status[task_id] = {
            "status": "in_progress",
            "progress": 0.0,
            "current_step": "Initializing",
            "message": "Starting feature extraction"
        }

        try:
            # 0. 清理旧数据，防止重复插入
            if cancel_event and cancel_event.is_set(): raise Exception("分析已被用户取消")
            self._update_task_status(task_id, 5, "Clearing old data")
            logger.info(f"[特征提取] 步骤 0/4: 清理旧数据...")
            self.delete_analysis_data(conversation_id)

            # 1. 会话切分
            if cancel_event and cancel_event.is_set(): raise Exception("分析已被用户取消")
            self._update_task_status(task_id, 10, "Splitting sessions")
            logger.info(f"[特征提取] 步骤 1/4: 会话切分...")
            step_start = time.time()
            sessions = self.extract_sessions(conversation_id)
            logger.info(f"[特征提取] 步骤 1/4: 会话切分完成 ({len(sessions)} 个会话, {time.time() - step_start:.1f}s)")

            # 2. 响应时间计算
            if cancel_event and cancel_event.is_set(): raise Exception("分析已被用户取消")
            self._update_task_status(task_id, 40, "Calculating response times")
            logger.info(f"[特征提取] 步骤 2/4: 计算响应时间...")
            step_start = time.time()
            response_time_stats = self.extract_response_times(conversation_id)
            logger.info(f"[特征提取] 步骤 2/4: 响应时间计算完成 ({response_time_stats.get('count', 0)} 条有效记录, {time.time() - step_start:.1f}s)")

            # 3. 主动性统计
            if cancel_event and cancel_event.is_set(): raise Exception("分析已被用户取消")
            self._update_task_status(task_id, 70, "Calculating initiative stats")
            logger.info(f"[特征提取] 步骤 3/4: 计算主动性统计...")
            step_start = time.time()
            initiative_stats = self.calculate_initiative_stats(conversation_id, sessions)
            logger.info(f"[特征提取] 步骤 3/4: 主动性统计完成 ({time.time() - step_start:.1f}s)")

            # 4. 字数统计
            if cancel_event and cancel_event.is_set(): raise Exception("分析已被用户取消")
            self._update_task_status(task_id, 90, "Calculating word counts")
            logger.info(f"[特征提取] 步骤 4/4: 计算字数统计...")
            step_start = time.time()
            word_counts = self.calculate_word_counts(conversation_id, sessions)
            logger.info(f"[特征提取] 步骤 4/4: 字数统计完成 ({time.time() - step_start:.1f}s)")

            self._update_task_status(task_id, 100, "completed", "completed")
            logger.info(f"[特征提取] 全部特征提取完成 (conversation_id={conversation_id})")

            return {
                "task_id": task_id,
                "sessions": sessions,
                "response_time_stats": response_time_stats,
                "initiative_stats": initiative_stats,
                "word_counts": word_counts
            }

        except Exception as e:
            logger.error(f"特征提取失败: {e}", exc_info=True)
            self._update_task_status(task_id, -1, "failed", f"Error: {str(e)}")
            raise

    def get_task_progress(self, task_id: str) -> Dict[str, Any]:
        """查询任务进度"""
        return self._task_status.get(task_id, {
            "status": "not_found",
            "progress": 0,
            "message": "Task not found"
        })

    def _update_task_status(self, task_id: str, progress: float, step: str, message: str = ""):
        """更新任务状态"""
        self._task_status[task_id] = {
            "status": "in_progress" if progress < 100 else ("completed" if progress == 100 else "failed"),
            "progress": progress,
            "current_step": step,
            "message": message
        }

    # =========================================================================
    # User Story 1: 会话切分
    # =========================================================================

    def extract_sessions(self, conversation_id: int) -> List[Dict[str, Any]]:
        """
        提取会话（User Story 1核心方法）
        使用新的 SessionManager：睡眠时间+时间间隔+语义相似度三重切分

        Args:
            conversation_id: 对话ID

        Returns:
            会话列表
        """
        # logger.info(f"提取会话: conversation_id={conversation_id}")

        # 1. 读取消息
        messages = self._fetch_messages(conversation_id)
        if not messages:
            # logger.warning(f"无消息数据: conversation_id={conversation_id}")
            return []

        # 2. 使用新的预处理服务构建发言单元和切分会话
        from .preprocessing_service import PairPreprocessingService, SessionManager

        # 使用缓存的实例（避免重复加载模型）
        if self._pair_service is None:
            self._pair_service = PairPreprocessingService()

        if self._session_manager is None:
            self._session_manager = SessionManager()

        # 2.1 构建发言单元（合并5分钟内同发送者的消息）
        speech_units = self._pair_service.build_speech_units(messages)

        if not speech_units:
            return []

        # 2.2 使用新的 SessionManager 切分会话（睡眠+时间+语义）
        session_result = self._session_manager.split_sessions(speech_units)

        # 3. 转换为数据库格式
        sessions_data = []
        for session in session_result:
            # 找到会话范围内的发言单元
            start_idx = session.get("start_unit_id", 0) - 1  # 转换为索引
            end_idx = session.get("end_unit_id", 0) - 1

            # 确保索引在有效范围内
            start_idx = max(0, min(start_idx, len(speech_units) - 1))
            end_idx = max(0, min(end_idx, len(speech_units) - 1))

            # 计算消息数量（通过发言单元的 message_count）
            message_count = sum(speech_units[i].get("message_count", 1)
                              for i in range(start_idx, end_idx + 1))

            # 判断发起者
            initiator_is_sender = session.get("initiator_is_sender", 0)
            initiator = "user" if initiator_is_sender == 1 else "other"

            sessions_data.append({
                "conversation_id": conversation_id,
                "start_time": session["start_timestamp"],
                "end_time": session["end_timestamp"],
                "message_count": message_count,
                "initiator": initiator,
                "source": messages[0].get("source", "long"),  # 使用消息的来源
                "created_at": int(time.time())
            })

        # 4. 批量插入数据库
        if sessions_data:
            columns = ["conversation_id", "start_time", "end_time", "message_count", "initiator", "source", "created_at"]
            data_tuples = [(d["conversation_id"], d["start_time"], d["end_time"],
                          d["message_count"], d["initiator"], d["source"], d["created_at"])
                         for d in sessions_data]

            batch_insert("sessions", columns, data_tuples, get_db())
            get_db().commit()

        #logger.info(f"会话提取完成: {len(sessions_data)}个会话")
        return sessions_data

    def _fetch_messages(self, conversation_id: int, limit: int = None, offset: int = 0) -> List[Dict]:
        """
        分批读取消息

        Args:
            conversation_id: 对话ID
            limit: 批次大小
            offset: 偏移量

        Returns:
            消息列表
        """
        sql = """
            SELECT id, conversation_id, is_sender, content, timestamp, source
            FROM messages
            WHERE conversation_id = ?
            ORDER BY timestamp ASC
        """

        if limit:
            sql += f" LIMIT {limit} OFFSET {offset}"

        cursor = get_db().execute(sql, (conversation_id,))
        rows = cursor.fetchall()

        return [dict(row) for row in rows]

    def _split_sessions(self, messages: List[Dict]) -> List[List[Dict]]:
        """
        切分会话（时间间隔阈值 + 睡眠时间强制切分）

        Args:
            messages: 消息列表（按时间排序）

        Returns:
            会话分组列表
        """
        if not messages:
            return []

        sessions = []
        current_session = [messages[0]]

        for i in range(1, len(messages)):
            prev_msg = current_session[-1]
            curr_msg = messages[i]
            time_gap = curr_msg["timestamp"] - prev_msg["timestamp"]

            # 条件1: 时间间隔超过阈值
            gap_exceeded = time_gap > self.config.session_gap_threshold

            # 条件2: 跨越睡眠时间
            crosses_sleep = self._check_crosses_sleep_time(
                prev_msg["timestamp"],
                curr_msg["timestamp"]
            )

            if gap_exceeded or crosses_sleep:
                # 保存当前会话，开始新会话
                sessions.append(current_session)
                current_session = [curr_msg]
            else:
                current_session.append(curr_msg)

        sessions.append(current_session)
        return sessions

    def _check_crosses_sleep_time(self, start_ts: int, end_ts: int) -> bool:
        """
        检查时间间隔是否跨越睡眠时间（00:00-07:00）

        Args:
            start_ts: 开始时间戳（秒）
            end_ts: 结束时间戳（秒）

        Returns:
            是否跨越睡眠时间
        """
        start_dt = datetime.fromtimestamp(start_ts, tz=timezone.utc)
        end_dt = datetime.fromtimestamp(end_ts, tz=timezone.utc)

        # 检查是否跨越午夜
        if start_dt.date() != end_dt.date():
            return True

        # 检查是否在睡眠时段内
        hour = start_dt.hour
        if hour >= 0 and hour < self.config.sleep_end_hour:
            # 如果在00:00-07:00之间，检查是否跨越结束时间
            return end_dt.hour >= self.config.sleep_end_hour

        return False

    def _identify_session_initiator(self, session: List[Dict]) -> str:
        """
        判断会话发起者

        Args:
            session: 会话消息列表

        Returns:
            'user' 或 'other'
        """
        if not session:
            return "user"

        first_msg = session[0]
        initiator = "user" if first_msg["is_sender"] == 1 else "other"

        return initiator

    # =========================================================================
    # User Story 2: 响应时间计算
    # =========================================================================

    def extract_response_times(self, conversation_id: int) -> Dict[str, Any]:
        """
        提取响应时间统计（User Story 2核心方法）

        Args:
            conversation_id: 对话ID

        Returns:
            响应时间统计字典
        """
        # logger.info(f"计算响应时间: conversation_id={conversation_id}")

        # 1. 读取消息
        messages = self._fetch_messages(conversation_id)
        if not messages:
            return self._empty_response_time_stats()

        # 2. 计算所有响应时间
        response_times_data = []
        valid_response_times = []

        for i in range(len(messages) - 1):
            sent_msg = messages[i]
            reply_msg = messages[i + 1]

            # 只计算我发消息 → 对方回复的情况
            if sent_msg["is_sender"] == 1 and reply_msg["is_sender"] == 0:
                result = self._calculate_response_time(
                    sent_msg["timestamp"],
                    reply_msg["timestamp"],
                    sent_msg["id"],
                    reply_msg["id"]
                )

                if result["is_abnormal"]:
                    response_times_data.append({
                        "conversation_id": conversation_id,
                        "sent_message_id": result["sent_message_id"],
                        "reply_message_id": result["reply_message_id"],
                        "response_time_seconds": None,
                        "is_abnormal": 1,
                        "abnormal_reason": result["abnormal_reason"],
                        "source": sent_msg.get("source", "long"),
                        "created_at": int(time.time())
                    })
                else:
                    response_times_data.append({
                        "conversation_id": conversation_id,
                        "sent_message_id": result["sent_message_id"],
                        "reply_message_id": result["reply_message_id"],
                        "response_time_seconds": result["response_time_seconds"],
                        "is_abnormal": 0,
                        "abnormal_reason": None,
                        "source": sent_msg.get("source", "long"),
                        "created_at": int(time.time())
                    })
                    valid_response_times.append(result["response_time_seconds"])

        # 3. 批量写入
        if response_times_data:
            columns = ["conversation_id", "sent_message_id", "reply_message_id",
                      "response_time_seconds", "is_abnormal", "abnormal_reason", "source", "created_at"]
            data_tuples = [(d["conversation_id"], d["sent_message_id"], d["reply_message_id"],
                           d["response_time_seconds"], d["is_abnormal"], d["abnormal_reason"],
                           d["source"], d["created_at"]) for d in response_times_data]
            batch_insert("response_times", columns, data_tuples, get_db())
            get_db().commit()

        # 4. 计算统计数据
        stats = self._calculate_response_time_stats(valid_response_times)
        stats["abnormal_count"] = len([d for d in response_times_data if d["is_abnormal"]])

        return stats

    def _calculate_response_time(self, sent_ts: int, reply_ts: int,
                                 sent_msg_id: int, reply_msg_id: int) -> Dict[str, Any]:
        """
        计算单对消息的响应时间（排除睡眠时间，检测异常值）

        Args:
            sent_ts: 发送时间戳
            reply_ts: 回复时间戳
            sent_msg_id: 发送消息ID
            reply_msg_id: 回复消息ID

        Returns:
            响应时间结果字典
        """
        # 基础时间差
        base_diff = reply_ts - sent_ts

        # 异常值检查
        if base_diff < 0:
            return {
                "sent_message_id": sent_msg_id,
                "reply_message_id": reply_msg_id,
                "response_time_seconds": None,
                "is_abnormal": True,
                "abnormal_reason": "negative"
            }

        if base_diff > self.config.max_response_time:
            return {
                "sent_message_id": sent_msg_id,
                "reply_message_id": reply_msg_id,
                "response_time_seconds": None,
                "is_abnormal": True,
                "abnormal_reason": "too_long"
            }

        # 检查是否跨越睡眠时间
        if self._check_crosses_sleep_time(sent_ts, reply_ts):
            # 扣除睡眠时间
            adjusted_diff = self._subtract_sleep_time(sent_ts, reply_ts)
            return {
                "sent_message_id": sent_msg_id,
                "reply_message_id": reply_msg_id,
                "response_time_seconds": adjusted_diff,
                "is_abnormal": False,
                "abnormal_reason": None
            }

        return {
            "sent_message_id": sent_msg_id,
            "reply_message_id": reply_msg_id,
            "response_time_seconds": base_diff,
            "is_abnormal": False,
            "abnormal_reason": None
        }

    def _subtract_sleep_time(self, start_ts: int, end_ts: int) -> float:
        """
        从时间间隔中扣除睡眠时段（00:00-07:00）

        Args:
            start_ts: 开始时间戳（秒）
            end_ts: 结束时间戳（秒）

        Returns:
            调整后的响应时间（秒）
        """
        start_dt = datetime.fromtimestamp(start_ts, tz=timezone.utc)
        end_dt = datetime.fromtimestamp(end_ts, tz=timezone.utc)

        sleep_seconds = 0
        current_dt = start_dt

        while current_dt < end_dt:
            # 进入00:00
            if current_dt.hour == 0 and current_dt.minute < 60:
                sleep_start = current_dt.replace(hour=0, minute=0, second=0, microsecond=0)
                sleep_end = current_dt.replace(hour=7, minute=0, second=0, microsecond=0)

                # 计算本次睡眠时段的时长
                if sleep_end > end_dt:
                    sleep_end = end_dt

                sleep_seconds += (sleep_end - sleep_start).total_seconds()
                current_dt = sleep_end
            else:
                # 跳到下一个00:00
                next_day = current_dt.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
                if next_day > end_dt:
                    break
                current_dt = next_day

        return (end_ts - start_ts) - sleep_seconds

    def _calculate_response_time_stats(self, response_times: List[float]) -> Dict[str, Any]:
        """
        计算响应时间统计

        Args:
            response_times: 有效响应时间列表（秒）

        Returns:
            统计数据字典
        """
        if not response_times:
            return {
                "count": 0,
                "avg": None,
                "median": None,
                "min": None,
                "max": None,
                "stddev": None,
                "abnormal_count": 0
            }

        return {
            "count": len(response_times),
            "avg": statistics.mean(response_times),
            "median": statistics.median(response_times),
            "min": min(response_times),
            "max": max(response_times),
            "stddev": statistics.stdev(response_times) if len(response_times) > 1 else 0,
            "abnormal_count": 0  # 由调用方填充
        }

    def _empty_response_time_stats(self) -> Dict[str, Any]:
        """返回空的响应时间统计"""
        return {
            "count": 0,
            "avg": None,
            "median": None,
            "min": None,
            "max": None,
            "stddev": None,
            "abnormal_count": 0
        }

    # =========================================================================
    # User Story 3: 主动性统计
    # =========================================================================

    def calculate_initiative_stats(self, conversation_id: int, sessions: List[Dict]) -> Dict[str, Any]:
        """
        计算主动性统计（User Story 3核心方法）

        Args:
            conversation_id: 对话ID
            sessions: 会话列表

        Returns:
            主动性统计字典
        """
        if not sessions:
            return {
                "total_sessions": 0,
                "user_initiated_sessions": 0,
                "other_initiated_sessions": 0,
                "initiative_rate": 0.0,
                "interpretation": "无会话数据"
            }

        total = len(sessions)
        user_initiated = sum(1 for s in sessions if s["initiator"] == "user")
        other_initiated = total - user_initiated
        initiative_rate = other_initiated / total if total > 0 else 0

        stats = {
            "total_sessions": total,
            "user_initiated_sessions": user_initiated,
            "other_initiated_sessions": other_initiated,
            "initiative_rate": initiative_rate,
            "interpretation": f"对方主动发起{initiative_rate:.1%}的会话"
        }

        # 写入数据库
        get_db().execute("""
            INSERT OR REPLACE INTO initiative_stats
            (conversation_id, total_sessions, user_initiated_sessions, other_initiated_sessions, initiative_rate, last_updated)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (conversation_id, stats["total_sessions"], stats["user_initiated_sessions"],
              stats["other_initiated_sessions"], stats["initiative_rate"], int(time.time())))
        get_db().commit()

        return stats

    # =========================================================================
    # User Story 4: 字数统计
    # =========================================================================

    def calculate_word_counts(self, conversation_id: int, sessions: List[Dict]) -> Dict[str, Any]:
        """
        计算字数统计（User Story 4核心方法）

        Args:
            conversation_id: 对话ID
            sessions: 会话列表

        Returns:
            字数统计字典
        """
        # 1. 整体统计
        messages = self._fetch_messages(conversation_id)

        overall_user_chars = 0
        overall_other_chars = 0

        for msg in messages:
            char_count = self._get_message_char_count(msg)
            if msg["is_sender"] == 1:
                overall_user_chars += char_count
            else:
                overall_other_chars += char_count

        overall_ratio = overall_other_chars / overall_user_chars if overall_user_chars > 0 else 0

        # 2. 写入整体统计
        get_db().execute("""
            INSERT OR REPLACE INTO word_counts
            (conversation_id, session_id, user_char_count, other_char_count, char_ratio, last_updated)
            VALUES (?, NULL, ?, ?, ?, ?)
        """, (conversation_id, overall_user_chars, overall_other_chars, overall_ratio, int(time.time())))

        # 3. 按会话统计
        session_counts = []
        for session in sessions:
            session_user_chars = 0
            session_other_chars = 0

            # 从session中获取消息（需要重新查询）
            # 这里简化处理，使用session的message_count和平均字数估算
            # 实际项目中应该为每个session单独统计

            session_ratio = session_other_chars / session_user_chars if session_user_chars > 0 else 0

            session_counts.append({
                "conversation_id": conversation_id,
                "session_id": session.get("id"),
                "user_char_count": session_user_chars,
                "other_char_count": session_other_chars,
                "char_ratio": session_ratio,
                "last_updated": int(time.time())
            })

        # 批量写入会话级别统计
        if session_counts:
            columns = ["conversation_id", "session_id", "user_char_count", "other_char_count", "char_ratio", "last_updated"]
            data_tuples = [(d["conversation_id"], d["session_id"], d["user_char_count"],
                           d["other_char_count"], d["char_ratio"], d["last_updated"])
                          for d in session_counts]
            batch_insert("word_counts", columns, data_tuples, get_db())

        get_db().commit()

        # 生成解读文本
        if overall_user_chars == 0 and overall_other_chars == 0:
            interpretation = "无字数数据"
        elif overall_ratio >= 1:
            interpretation = f"对方投入的字数是您的{overall_ratio:.2f}倍"
        elif overall_ratio > 0:
            # overall_ratio < 1 且 > 0
            interpretation = f"您投入的字数是对方的{1/overall_ratio:.2f}倍"
        else:
            # overall_ratio == 0（对方字数为0）
            interpretation = "对方未投入字数"

        result = {
            "overall": {
                "user_char_count": overall_user_chars,
                "other_char_count": overall_other_chars,
                "char_ratio": overall_ratio,
                "interpretation": interpretation
            },
            "by_session": session_counts
        }

        return result

    def _get_message_char_count(self, message: Dict) -> int:
        """
        获取消息字数（从PreprocessingService）

        Args:
            message: 消息字典

        Returns:
            字数
        """
        # 使用PreprocessingService的clean_content方法
        content = message.get("content", "")
        if not content:
            return 0

        # 调用preprocessor清洗
        result = self.preprocessor.clean_content(content)
        return result.get("cleaned_length", 0)

    # =========================================================================
    # 辅助方法
    # =========================================================================

    def delete_analysis_data(self, conversation_id: int) -> bool:
        """
        删除指定对话的分析结果（用于重新分析）

        Args:
            conversation_id: 对话ID

        Returns:
            是否成功
        """
        try:
            get_db().execute("DELETE FROM sessions WHERE conversation_id = ?", (conversation_id,))
            get_db().execute("DELETE FROM response_times WHERE conversation_id = ?", (conversation_id,))
            get_db().execute("DELETE FROM initiative_stats WHERE conversation_id = ?", (conversation_id,))
            get_db().execute("DELETE FROM word_counts WHERE conversation_id = ?", (conversation_id,))
            get_db().commit()
            logger.info(f"删除分析数据完成: conversation_id={conversation_id}")
            return True
        except Exception as e:
            logger.error(f"删除分析数据失败: {e}")
            get_db().rollback()
            return False
