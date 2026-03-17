"""预处理编排器 - 协调所有预处理服务并收集29个统计常量

这是好感度分析系统的关键路径组件,必须在任何维度分析之前完成。

功能:
- orchestrate_preprocessing(): 主入口,协调所有预处理服务
- get_preprocessed_statistics(): 返回PreprocessedStatistics数据类
- invalidate_cache(): 清除预处理缓存
"""

import time
import json
import logging
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, asdict
from datetime import datetime

from ...db.connection import get_db
from .sentiment_service import SentimentService
from .preprocessing_service import (
    BasicPreprocessingService,
    PairPreprocessingService,
    SessionManager,
    AttitudePreprocessingService,
    AttitudeStatistics
)
from .keyword_libraries import KeywordLibraries

# 配置日志
logger = logging.getLogger(__name__)


def _step_elapsed(start_time: float) -> str:
    """格式化步骤耗时，便于在终端观察进度。"""
    return f"{time.time() - start_time:.1f}s"


@dataclass
class PreprocessedStatistics:
    """预处理统计数据结构 - 包含所有29个统计常量"""
    
    # 基础消息统计 (4个)
    total_message_count: int = 0
    total_positive_count: int = 0
    total_negative_count: int = 0
    total_neutral_count: int = 0
    
    # 时间统计 (4个)
    conversation_start_timestamp: int = 0
    conversation_end_timestamp: int = 0
    conversation_duration_days: float = 0.0
    chat_days_count: int = 0
    
    # 长度统计 (2个)
    total_characters: int = 0
    average_message_length: float = 0.0
    
    # 交互对统计 (3个)
    total_interaction_pairs: int = 0
    bidirectional_pairs: int = 0
    same_parity_pairs: int = 0
    
    # 会话统计 (3个)
    total_sessions: int = 0
    average_session_length: float = 0.0
    average_session_gap: float = 0.0
    
    # 会话发起者统计 (2个)
    sender_initiated_count: int = 0
    contact_initiated_count: int = 0
    
    # 态度统计 (7个)
    emoji_message_count: int = 0
    voice_message_count: int = 0
    video_message_count: int = 0
    nickname_message_count: int = 0
    privacy_message_count: int = 0
    holiday_message_count: int = 0
    holidays_sent_count: int = 0
    
    # 元数据
    conversation_id: int = 0
    preprocessing_timestamp: int = 0
    preprocessing_duration_ms: int = 0


class PreprocessingOrchestrator:
    """预处理编排器 - 协调所有预处理服务"""
    
    def __init__(self):
        pass  # get_db() removed for thread safety
        
        # 初始化所有服务
        self.sentiment_service = SentimentService()
        self.basic_service = BasicPreprocessingService()
        self.pair_service = PairPreprocessingService()
        self.session_manager = SessionManager()
        self.keyword_lib = KeywordLibraries()
        self.attitude_service = AttitudePreprocessingService(keyword_lib=self.keyword_lib)
    
    def orchestrate_preprocessing(
        self,
        conversation_id: int,
        force_reprocess: bool = False
    ) -> PreprocessedStatistics:
        """
        主入口 - 协调所有预处理服务并收集29个统计常量
        
        Args:
            conversation_id: 会话ID
            force_reprocess: 是否强制重新处理(忽略缓存)
        
        Returns:
            PreprocessedStatistics: 包含所有29个统计常量的数据类
        """
        start_time = time.time()
        logger.info(f"[预处理] 开始处理会话 {conversation_id} (force={force_reprocess})")
        
        # 1. 检查缓存
        if not force_reprocess:
            cached_stats = self._load_cached_statistics(conversation_id)
            if cached_stats:
                logger.info(f"[预处理] 使用缓存的统计数据 (会话 {conversation_id})")
                return cached_stats
        
        # 2. 收集所有统计数据
        stats = self._collect_all_statistics(conversation_id)
        
        # 3. 保存结果
        duration_ms = int((time.time() - start_time) * 1000)
        stats.preprocessing_duration_ms = duration_ms
        self._save_preprocessing_results(conversation_id, stats)

        logger.info(f"[预处理] 全部完成,耗时 {duration_ms}ms (会话 {conversation_id})")
        return stats
    
    def _collect_all_statistics(self, conversation_id: int) -> PreprocessedStatistics:
        """
        收集所有29个统计常量 (O(N) 单次遍历)
        
        Args:
            conversation_id: 会话ID
        
        Returns:
            PreprocessedStatistics: 统计数据
        """
        logger.info(f"[预处理] 开始收集统计数据 (会话 {conversation_id})")
        stats = PreprocessedStatistics()
        stats.conversation_id = conversation_id
        stats.preprocessing_timestamp = int(time.time())
        
        # ===== 步骤1: 加载消息 =====
        step_start = time.time()
        logger.info(f"[预处理] 步骤 1/8: 加载消息...")
        messages = self._load_messages(conversation_id)
        logger.info(f"[预处理] 步骤 1/8: 加载消息完成 ({len(messages)} 条, {_step_elapsed(step_start)})")

        if not messages:
            logger.warning(f"会话 {conversation_id} 没有消息")
            return stats

        # ===== 步骤2: 情感分析 (批量处理) =====
        step_start = time.time()
        logger.info(f"[预处理] 步骤 2/8: 情感分析与向量缓存...")
        self._ensure_sentiment_analysis(conversation_id, messages)
        logger.info(f"[预处理] 步骤 2/8: 情感分析完成 ({_step_elapsed(step_start)})")

        # ===== 步骤3: 基础统计 =====
        step_start = time.time()
        logger.info(f"[预处理] 步骤 3/8: 收集基础统计...")
        basic_stats = self.basic_service.collect_message_statistics(conversation_id)
        stats.total_message_count = basic_stats["total_message_count"]
        stats.total_positive_count = basic_stats["total_positive_count"]
        stats.total_negative_count = basic_stats["total_negative_count"]
        stats.total_neutral_count = basic_stats["total_neutral_count"]
        logger.info(f"[预处理] 步骤 3/8: 基础统计完成 (总消息 {stats.total_message_count}, {_step_elapsed(step_start)})")

        # ===== 步骤4: 时间统计 =====
        step_start = time.time()
        logger.info(f"[预处理] 步骤 4/8: 收集时间统计...")
        time_stats = self.basic_service.collect_time_statistics(conversation_id)
        stats.conversation_start_timestamp = time_stats["conversation_start_timestamp"]
        stats.conversation_end_timestamp = time_stats["conversation_end_timestamp"]
        stats.conversation_duration_days = time_stats["conversation_duration_days"]
        stats.chat_days_count = time_stats["chat_days_count"]
        logger.info(f"[预处理] 步骤 4/8: 时间统计完成 ({stats.conversation_duration_days:.1f} 天, {_step_elapsed(step_start)})")

        # ===== 步骤5: 长度统计 =====
        step_start = time.time()
        logger.info(f"[预处理] 步骤 5/8: 收集长度统计...")
        length_stats = self.basic_service.collect_length_statistics(conversation_id)
        stats.total_characters = length_stats["total_characters"]
        stats.average_message_length = length_stats["average_message_length"]
        logger.info(f"[预处理] 步骤 5/8: 长度统计完成 (平均长度 {stats.average_message_length:.1f}, {_step_elapsed(step_start)})")

        # ===== 步骤6: 构建发言单元和交互对 =====
        step_start = time.time()
        logger.info(f"[预处理] 步骤 6/8: 构建发言单元和交互对...")
        speech_units = self.pair_service.build_speech_units(messages)
        interaction_pairs = self.pair_service.build_interaction_pairs(speech_units)
        
        # 保存到数据库
        self.pair_service.clear_cached_pairs(conversation_id)
        unit_id_map = self.pair_service.save_speech_units_with_mapping(
            conversation_id,
            speech_units
        )
        for pair in interaction_pairs:
            pair["first_unit_id"] = unit_id_map[pair["first_unit_id"]]
            pair["second_unit_id"] = unit_id_map[pair["second_unit_id"]]
        self.pair_service.save_interaction_pairs(conversation_id, interaction_pairs)
        
        # 收集交互对统计
        pair_stats = self.pair_service.collect_pair_statistics(interaction_pairs)
        stats.total_interaction_pairs = pair_stats["total_interaction_pairs"]
        stats.bidirectional_pairs = pair_stats["bidirectional_pairs"]
        stats.same_parity_pairs = pair_stats["same_parity_pairs"]
        logger.info(f"[预处理] 步骤 6/8: 交互对构建完成 ({len(speech_units)} 个发言单元, {stats.total_interaction_pairs} 个交互对, {_step_elapsed(step_start)})")

        # ===== 步骤7: 会话切分 =====
        step_start = time.time()
        logger.info(f"[预处理] 步骤 7/8: 会话切分...")
        sessions = self.session_manager.split_sessions(speech_units, conversation_id)
        
        # 保存会话
        self.session_manager.save_sessions(conversation_id, sessions)
        
        # 收集会话统计
        session_stats = self.session_manager.collect_session_statistics(sessions)
        stats.total_sessions = session_stats["total_sessions"]
        stats.average_session_length = session_stats["average_session_length"]
        stats.average_session_gap = session_stats["average_session_gap"]
        
        # 识别会话发起者
        initiator_stats = self.session_manager.identify_session_initiators(sessions)
        stats.sender_initiated_count = initiator_stats["sender_initiated_count"]
        stats.contact_initiated_count = initiator_stats["contact_initiated_count"]
        logger.info(f"[预处理] 步骤 7/8: 会话切分完成 ({stats.total_sessions} 个会话, {_step_elapsed(step_start)})")

        # ===== 步骤8: 态度统计 =====
        step_start = time.time()
        logger.info(f"[预处理] 步骤 8/8: 收集态度统计...")
        attitude_stats = self.attitude_service.collect_attitude_statistics(messages)
        stats.emoji_message_count = attitude_stats.emoji_message_count
        stats.voice_message_count = attitude_stats.voice_message_count
        stats.video_message_count = attitude_stats.video_message_count
        stats.nickname_message_count = attitude_stats.nickname_message_count
        stats.privacy_message_count = attitude_stats.privacy_message_count
        stats.holiday_message_count = attitude_stats.holiday_message_count
        stats.holidays_sent_count = attitude_stats.holidays_sent_count
        logger.info(f"[预处理] 步骤 8/8: 态度统计完成 ({_step_elapsed(step_start)})")
        logger.info(f"[预处理] 统计收集完成 (会话 {conversation_id})")
        return stats
    
    def _load_messages(self, conversation_id: int) -> List[Dict[str, Any]]:
        """
        加载会话的所有消息（仅文本消息）
        
        Args:
            conversation_id: 会话ID
        
        Returns:
            消息列表
        """
        cursor = get_db().execute("""
            SELECT id, content, is_sender, timestamp, message_type
            FROM messages
            WHERE conversation_id = ?
              AND message_type = 1  -- 只加载文本消息
            ORDER BY timestamp ASC
        """, (conversation_id,))
        
        messages = []
        for row in cursor.fetchall():
            # 确保 content 不为 None
            content = row[1] if row[1] is not None else ""
            
            messages.append({
                "id": row[0],
                "content": content,
                "is_sender": row[2],
                "timestamp": row[3],
                "message_type": row[4]
            })
        
        return messages
    
    def _ensure_sentiment_analysis(
        self,
        conversation_id: int,
        messages: List[Dict[str, Any]]
    ):
        """
        确保所有消息都已完成情感分析
        
        Args:
            conversation_id: 会话ID
            messages: 消息列表
        """
        # 检查哪些消息需要分析
        messages_to_analyze = []

        for msg in messages:
            if msg["message_type"] != 1:
                continue

            cached = self.sentiment_service.get_sentiment_from_cache(msg["id"])
            if not cached:
                messages_to_analyze.append(msg)

        if not messages_to_analyze:
            logger.info(f"[预处理] 情感分析缓存命中，无需重新计算")
            return

        logger.info(f"[预处理] 需要分析 {len(messages_to_analyze)} 条消息")

        total_to_analyze = len(messages_to_analyze)
        batch_size = 500
        total_batches = (total_to_analyze + batch_size - 1) // batch_size
        sentiment_start = time.time()

        for i in range(0, total_to_analyze, batch_size):
            batch_index = i // batch_size + 1
            batch_msgs = messages_to_analyze[i:i + batch_size]
            texts = [msg["content"] or "" for msg in batch_msgs]

            batch_results = self.sentiment_service.analyze_batch(texts)

            cache_data = []
            for msg, result in zip(batch_msgs, batch_results):
                cache_data.append({
                    "message_id": msg["id"],
                    "polarity": result["polarity"],
                    "intensity": result["intensity"],
                    "embedding": result["embedding"]
                })

            self.sentiment_service.batch_cache_sentiments(cache_data)

            import gc
            import torch
            gc.collect()
            if torch.cuda.is_available():
                torch.cuda.empty_cache()

            time.sleep(0.1)

            processed = min(i + batch_size, total_to_analyze)
            percentage = (processed / total_to_analyze) * 100
            logger.info(
                f"[预处理] 情感分析批次 {batch_index}/{total_batches}: "
                f"{processed}/{total_to_analyze} ({percentage:.1f}%), "
                f"累计耗时 {_step_elapsed(sentiment_start)}"
            )

        logger.info(f"[预处理] 情感分析全部完成并缓存 ({total_to_analyze} 条消息)")
        return

    def _save_preprocessing_results(
        self,
        conversation_id: int,
        stats: PreprocessedStatistics
    ):
        """
        保存预处理结果到数据库
        
        Args:
            conversation_id: 会话ID
            stats: 统计数据
        """
        # 将dataclass转换为JSON
        stats_json = json.dumps(asdict(stats), ensure_ascii=False)
        
        # 保存到settings表 (使用conversation_id作为key的一部分)
        key = f"preprocessing_stats_{conversation_id}"
        
        try:
            get_db().execute("""
                INSERT OR REPLACE INTO settings (key, value, updated_at)
                VALUES (?, ?, ?)
            """, (key, stats_json, int(time.time())))
            
            get_db().commit()
            logger.debug(f"统计数据已保存到数据库 (会话 {conversation_id})")

        except Exception as e:
            logger.error(f"保存统计数据失败: {e}", exc_info=True)
    
    def _load_cached_statistics(
        self,
        conversation_id: int
    ) -> Optional[PreprocessedStatistics]:
        """
        从缓存加载预处理统计数据
        
        Args:
            conversation_id: 会话ID
        
        Returns:
            PreprocessedStatistics 或 None
        """
        key = f"preprocessing_stats_{conversation_id}"
        
        try:
            cursor = get_db().execute("""
                SELECT value FROM settings WHERE key = ?
            """, (key,))
            
            row = cursor.fetchone()
            if not row:
                return None
            
            # 解析JSON
            stats_dict = json.loads(row[0])
            stats = PreprocessedStatistics(**stats_dict)
            
            return stats
        
        except Exception as e:
            logger.error(f"加载缓存失败: {e}", exc_info=True)
            return None
    
    def invalidate_cache(self, conversation_id: int):
        """
        清除预处理缓存
        
        Args:
            conversation_id: 会话ID
        """
        key = f"preprocessing_stats_{conversation_id}"
        
        try:
            get_db().execute("""
                DELETE FROM settings WHERE key = ?
            """, (key,))
            
            get_db().commit()
            logger.debug(f"缓存已清除 (会话 {conversation_id})")

        except Exception as e:
            logger.error(f"清除缓存失败: {e}", exc_info=True)
    
    def get_preprocessed_statistics(
        self,
        conversation_id: int,
        force_reprocess: bool = False
    ) -> PreprocessedStatistics:
        """
        获取预处理统计数据 (公共接口)
        
        Args:
            conversation_id: 会话ID
            force_reprocess: 是否强制重新处理
        
        Returns:
            PreprocessedStatistics: 统计数据
        """
        return self.orchestrate_preprocessing(conversation_id, force_reprocess)
