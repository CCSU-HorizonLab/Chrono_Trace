"""聊天积极度服务 - 计算聊天积极度维度 (30% 权重)

包含 5 个子维度计算：
1. 日均消息数 (10% 权重)
2. 回复及时率 (20% 权重)
3. 话题延续性 (25% 权重)
4. 主动发起率 (35% 权重)

包含 1 个加分项：
- 长文本占比 (最高加 10 分)
"""

import logging
from dataclasses import dataclass
from typing import Optional

from ...db.connection import get_db
from .preprocessing_orchestrator import PreprocessedStatistics

# ===== 调试开关：设为True时输出详细跟踪日志 =====
DEBUG_TRACE = True

def debug_log(msg: str):
    """专门用于记录分析调试的物理日志"""
    if DEBUG_TRACE:
        from .affinity_debug_logger import affinity_debug_log
        affinity_debug_log(msg)

# 配置日志
logger = logging.getLogger(__name__)


@dataclass
class ChatPositivityResult:
    """聊天积极度计算结果"""
    
    # 子维度分数 (0-100)
    daily_message_score: float = 0.0
    reply_timeliness_score: float = 0.0
    long_text_bonus: float = 0.0
    topic_continuity_score: float = 0.0
    active_initiation_score: float = 0.0
    
    # 综合评分 (0-100)
    overall_score: float = 0.0
    
    # 解释文本
    interpretation: str = ""
    
    # 原始值 (用于调试和展示)
    daily_message_count: float = 0.0
    reply_timeliness_rate: float = 0.0
    long_text_ratio: float = 0.0
    topic_continuity_avg: float = 0.0
    active_initiation_rate: float = 0.0


class ChatPositivityService:
    """聊天积极度服务 - 计算聊天积极度维度"""
    
    # 子维度权重
    WEIGHT_DAILY_MESSAGE = 0.15
    WEIGHT_REPLY_TIMELINESS = 0.25
    WEIGHT_TOPIC_CONTINUITY = 0.25
    WEIGHT_ACTIVE_INITIATION = 0.35
    
    # 评分标准化参数
    DAILY_MESSAGE_BASELINE = 10.0  # 日均 10 条消息为满分基准
    LONG_TEXT_THRESHOLD = 50       # 长文本阈值 (字符数)
    
    def __init__(self, timeliness_threshold_seconds: int = 300):
        """
        初始化聊天积极度服务
        
        Args:
            timeliness_threshold_seconds: 回复及时阈值 (秒)，默认 5 分钟
        """
        self.db = get_db()
        self.timeliness_threshold = timeliness_threshold_seconds
        
    def calculate_scores(
        self,
        conversation_id: int,
        stats: PreprocessedStatistics
    ) -> ChatPositivityResult:
        """
        计算所有子维度分数并返回综合评分
        
        Args:
            conversation_id: 会话 ID
            stats: 预处理统计数据
            
        Returns:
            ChatPositivityResult: 包含所有分数和解释的结果
        """
        result = ChatPositivityResult()
        
        debug_log(f"\n{'*'*40}")
        debug_log(f"【聊天积极度】开始计分 (会话 ID {conversation_id})")
        debug_log(f"*[注] 该项占总分30%权重，自身包含6个子维度*")
        
        # 1. 日均消息数 (10%)
        result.daily_message_count = self._calculate_daily_message_count_raw(stats)
        result.daily_message_score = self.calculate_daily_message_score(stats)
        debug_log(f"\n[聊天积极度调试] --- 1. 日均消息数 (权重10%) ---")
        debug_log(f"总消息数: {stats.total_message_count}, 持续天数: {stats.conversation_duration_days:.1f}")
        debug_log(f"日均消息数: {result.daily_message_count:.2f} (满分基准: {self.DAILY_MESSAGE_BASELINE}) -> 得分: {result.daily_message_score}")
        
        # 2. 回复及时率 (20%)
        result.reply_timeliness_rate = self._calculate_reply_timeliness_raw(conversation_id)
        result.reply_timeliness_score = self.calculate_reply_timeliness_score(conversation_id)
        debug_log(f"\n[聊天积极度调试] --- 2. 回复及时率 (权重20%) ---")
        debug_log(f"及时回复比例: {result.reply_timeliness_rate*100:.1f}% -> 得分: {result.reply_timeliness_score}")
        
        # 3. 话题延续性 (25%)
        result.topic_continuity_avg = self._calculate_topic_continuity_raw(conversation_id)
        result.topic_continuity_score = self.calculate_topic_continuity_score(conversation_id)
        debug_log(f"\n[聊天积极度调试] --- 3. 话题延续性 (权重25%) ---")
        debug_log(f"平均语义相似度: {result.topic_continuity_avg:.3f} (满分基准: 0.5) -> 得分: {result.topic_continuity_score}")
        
        # 4. 主动发起率 (35%)
        result.active_initiation_rate = self._calculate_active_initiation_raw(stats)
        result.active_initiation_score = self.calculate_active_initiation_score(stats)
        debug_log(f"\n[聊天积极度调试] --- 4. 主动发起率 (权重35%) ---")
        debug_log(f"对方发起的会话比例: {result.active_initiation_rate*100:.1f}% (满分基准: 50.0%) -> 得分: {result.active_initiation_score}")

        # 5. 加分项: 长文本占比 (最高 10 分)
        result.long_text_ratio = self._calculate_long_text_ratio_raw(conversation_id, stats)
        result.long_text_bonus = self.calculate_long_text_bonus(conversation_id, stats)
        debug_log(f"\n[聊天积极度调试] --- 5. 加分项: 长文本占比 ---")
        debug_log(f"长文本(>{self.LONG_TEXT_THRESHOLD}字)占比: {result.long_text_ratio*100:.1f}% (满分基准: 30.0%) -> 加分: +{result.long_text_bonus}")
        
        # 综合评分
        result.overall_score = self._calculate_overall_score(result)
        
        # 生成解释
        result.interpretation = self.generate_interpretation(result.overall_score)
        
        logger.info(f"聊天积极度计算完成: {result.overall_score:.1f} 分 (会话 {conversation_id})")
        return result
    
    # ========================================
    # 子维度分数计算方法
    # ========================================
    
    def calculate_daily_message_score(self, stats: PreprocessedStatistics) -> float:
        """
        计算日均消息数得分 (0-100)
        
        公式: min(日均消息数 / 基准值 * 100, 100)
        基准值: 10 条/天
        """
        daily_count = self._calculate_daily_message_count_raw(stats)
        score = min((daily_count / self.DAILY_MESSAGE_BASELINE) * 100, 100)
        return round(score, 2)
    
    def _calculate_daily_message_count_raw(self, stats: PreprocessedStatistics) -> float:
        """计算日均消息数原始值"""
        if stats.conversation_duration_days <= 0:
            return 0.0
        return stats.total_message_count / max(stats.conversation_duration_days, 1.0)
    
    def calculate_reply_timeliness_score(self, conversation_id: int) -> float:
        """
        计算回复及时率得分 (0-100)
        
        公式: (及时回复交互对数 / 总交互对数) × 100
        及时: 回复时间 <= timeliness_threshold
        """
        timeliness_rate = self._calculate_reply_timeliness_raw(conversation_id)
        return round(timeliness_rate * 100, 2)
    
    def _calculate_reply_timeliness_raw(self, conversation_id: int) -> float:
        """
        计算回复及时率原始值 (0-1)
        
        从交互对表中统计在阈值时间内回复的比例
        """
        try:
            cursor = self.db.execute("""
                SELECT 
                    COUNT(*) as total,
                    SUM(CASE WHEN time_gap <= ? AND time_gap >= 0 THEN 1 ELSE 0 END) as timely
                FROM interaction_pairs
                WHERE conversation_id = ?
            """, (self.timeliness_threshold, conversation_id))
            
            row = cursor.fetchone()
            total = row[0] or 0
            timely = row[1] or 0
            
            if total == 0:
                return 0.0
            
            debug_log(f"[聊天积极度调试深入] 交互对总数: {total}, 及时回复(<={self.timeliness_threshold}s)数: {timely}")
            return timely / total
            
        except Exception as e:
            logger.error(f"计算回复及时率失败: {e}")
            return 0.0
    
    def calculate_long_text_bonus(
        self,
        conversation_id: int,
        stats: PreprocessedStatistics
    ) -> float:
        """
        计算长文本占比加分 (0-10)
        
        公式: min((长文本占比 / 0.3) * 10, 10.0)
        """
        ratio = self._calculate_long_text_ratio_raw(conversation_id, stats)
        # 长文本占比 30% 以上为满分10分
        score = min((ratio / 0.30) * 10.0, 10.0)
        return round(score, 2)
    
    def _calculate_long_text_ratio_raw(
        self,
        conversation_id: int,
        stats: PreprocessedStatistics
    ) -> float:
        """计算长文本占比原始值 (0-1)"""
        if stats.total_message_count == 0:
            return 0.0
        
        try:
            cursor = self.db.execute("""
                SELECT COUNT(*) 
                FROM message_preprocessed mp
                JOIN messages m ON mp.message_id = m.id
                WHERE m.conversation_id = ?
                    AND mp.is_valid = 1
                    AND mp.char_count > ?
            """, (conversation_id, self.LONG_TEXT_THRESHOLD))
            
            long_count = cursor.fetchone()[0] or 0
            return long_count / stats.total_message_count
            
        except Exception as e:
            logger.error(f"计算长文本占比失败: {e}")
            return 0.0
    
    def calculate_topic_continuity_score(self, conversation_id: int) -> float:
        """
        计算话题延续性得分 (0-100)
        
        公式: min((平均语义相似度 / 0.5) * 100, 100)
        """
        continuity = self._calculate_topic_continuity_raw(conversation_id)
        # 满分阈值为 0.5
        score = min((continuity / 0.5) * 100, 100)
        return round(score, 2)
    
    def _calculate_topic_continuity_raw(self, conversation_id: int) -> float:
        """
        计算话题延续性原始值 (0-1)
        
        使用交互对的语义相似度平均值
        """
        try:
            cursor = self.db.execute("""
                SELECT AVG(semantic_similarity)
                FROM interaction_pairs
                WHERE conversation_id = ?
                    AND semantic_similarity IS NOT NULL
            """, (conversation_id,))
            
            row = cursor.fetchone()
            avg_similarity = row[0] if row[0] is not None else 0.0
            
            return max(0.0, min(1.0, avg_similarity))
            
        except Exception as e:
            logger.error(f"计算话题延续性失败: {e}")
            return 0.0
    
    def calculate_active_initiation_score(self, stats: PreprocessedStatistics) -> float:
        """
        计算主动发起率得分 (0-100)
        
        公式: min((对方发起会话数 / 总会话数 / 0.5) * 100, 100)
        """
        rate = self._calculate_active_initiation_raw(stats)
        score = min((rate / 0.5) * 100, 100)
        return round(score, 2)
    
    def _calculate_active_initiation_raw(self, stats: PreprocessedStatistics) -> float:
        """
        计算主动发起率原始值 (0-1)
        
        对方发起的会话占总会话的比例
        """
        total_sessions = stats.total_sessions
        if total_sessions == 0:
            return 0.0
        
        # contact_initiated_count 是对方发起的会话数
        # 对方越主动，好感度越高
        return stats.contact_initiated_count / total_sessions
    
    # ========================================
    # 综合评分和解释
    # ========================================
    
    def _calculate_overall_score(self, result: ChatPositivityResult) -> float:
        """
        计算综合评分 (加权平均)
        
        权重:
        - 日均消息数: 15%
        - 回复及时率: 25%
        - 话题延续性: 25%
        - 主动发起率: 35%
        加分:
        - 长文本占比加分 (最高10分)
        """
        overall = (
            result.daily_message_score * self.WEIGHT_DAILY_MESSAGE +
            result.reply_timeliness_score * self.WEIGHT_REPLY_TIMELINESS +
            result.topic_continuity_score * self.WEIGHT_TOPIC_CONTINUITY +
            result.active_initiation_score * self.WEIGHT_ACTIVE_INITIATION
        )
        overall += result.long_text_bonus
        return min(round(overall, 2), 100.0)
    
    def generate_interpretation(self, score: float) -> str:
        """
        根据分数生成解释文本
        
        Args:
            score: 综合评分 (0-100)
            
        Returns:
            解释文本
        """
        if score >= 80:
            return "对方积极度非常高，回复及时且主动发起话题，对这段关系非常投入"
        elif score >= 60:
            return "对方积极度较高，愿意投入时间和精力维持对话"
        elif score >= 40:
            return "对方积极度一般，偶尔主动但不够热情"
        elif score >= 20:
            return "对方积极度较低，回复较慢且较少主动发起话题"
        else:
            return "对方积极度很低，可能对这段关系兴趣不大"
