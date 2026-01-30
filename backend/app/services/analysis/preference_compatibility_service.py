"""喜好兼容度服务 - 计算喜好维度 (20% 权重)

包含 2 个子维度计算：
1. 话题提及频率 (40% 权重)
2. 喜好话题延续性 (60% 权重)
"""

import logging
from dataclasses import dataclass
from typing import List, Optional, Set

from ...db.connection import get_db
from .preprocessing_orchestrator import PreprocessedStatistics

# 配置日志
logger = logging.getLogger(__name__)


@dataclass
class PreferenceCompatibilityResult:
    """喜好兼容度计算结果"""
    
    # 子维度分数 (0-100)
    topic_mention_score: float = 0.0
    topic_continuity_score: float = 0.0
    
    # 综合评分 (0-100)
    overall_score: float = 0.0
    
    # 解释文本
    interpretation: str = ""
    
    # 原始值 (用于调试和展示)
    preference_session_count: int = 0
    total_session_count: int = 0
    topic_mention_frequency: float = 0.0
    avg_continuity: float = 0.0
    matched_keywords: List[str] = None
    
    def __post_init__(self):
        if self.matched_keywords is None:
            self.matched_keywords = []


class PreferenceCompatibilityService:
    """喜好兼容度服务 - 计算喜好维度"""
    
    # 子维度权重
    WEIGHT_TOPIC_MENTION = 0.40
    WEIGHT_TOPIC_CONTINUITY = 0.60
    
    def __init__(self, preference_keywords: Optional[List[str]] = None):
        """
        初始化喜好兼容度服务
        
        Args:
            preference_keywords: 喜好关键词列表 (如 ["篮球", "电影", "旅行"])
        """
        self.db = get_db()
        self.preference_keywords = preference_keywords or []
        
    def set_preference_keywords(self, keywords: List[str]):
        """设置喜好关键词"""
        self.preference_keywords = [k.strip() for k in keywords if k.strip()]
        
    def calculate_scores(
        self,
        conversation_id: int,
        stats: PreprocessedStatistics
    ) -> PreferenceCompatibilityResult:
        """
        计算所有子维度分数并返回综合评分
        
        Args:
            conversation_id: 会话 ID
            stats: 预处理统计数据
            
        Returns:
            PreferenceCompatibilityResult: 包含所有分数和解释的结果
        """
        result = PreferenceCompatibilityResult()
        result.total_session_count = stats.total_sessions
        
        # 如果没有喜好关键词，返回 0 分
        if not self.preference_keywords:
            logger.info(f"未设置喜好关键词,喜好维度权重为 0 (会话 {conversation_id})")
            result.interpretation = "未设置喜好关键词,该维度不参与好感度评分"
            return result
        
        # 识别包含喜好关键词的会话
        preference_sessions, matched_keywords = self.identify_preference_sessions(
            conversation_id
        )
        result.preference_session_count = len(preference_sessions)
        result.matched_keywords = matched_keywords
        
        # 1. 话题提及频率 (40%)
        result.topic_mention_frequency = self._calculate_topic_mention_raw(
            len(preference_sessions), stats.total_sessions
        )
        result.topic_mention_score = self.calculate_topic_mention_score(
            len(preference_sessions), stats.total_sessions
        )
        
        # 2. 喜好话题延续性 (60%)
        result.avg_continuity = self._calculate_topic_continuity_raw(
            conversation_id, preference_sessions
        )
        result.topic_continuity_score = self.calculate_topic_continuity_score(
            conversation_id, preference_sessions
        )
        
        # 综合评分
        result.overall_score = self._calculate_overall_score(result)
        
        # 生成解释
        result.interpretation = self.generate_interpretation(result.overall_score)
        
        logger.info(f"喜好兼容度计算完成: {result.overall_score:.1f} 分 (会话 {conversation_id})")
        return result
    
    # ========================================
    # 会话识别方法
    # ========================================
    
    def identify_preference_sessions(
        self,
        conversation_id: int
    ) -> tuple[List[int], List[str]]:
        """
        识别包含喜好关键词的会话
        
        Args:
            conversation_id: 会话 ID
            
        Returns:
            (包含喜好关键词的会话 ID 列表, 匹配到的关键词列表)
        """
        if not self.preference_keywords:
            return [], []
        
        try:
            # 从 speech_units 表查找包含关键词的内容
            # 然后关联到会话
            preference_session_ids: Set[int] = set()
            matched_keywords: Set[str] = set()
            
            # 获取所有会话的发言单元
            cursor = self.db.execute("""
                SELECT su.id, su.content, su.start_timestamp
                FROM speech_units su
                WHERE su.conversation_id = ?
                ORDER BY su.start_timestamp ASC
            """, (conversation_id,))
            
            speech_units = cursor.fetchall()
            
            # 获取会话边界信息
            cursor = self.db.execute("""
                SELECT id, start_unit_id, end_unit_id
                FROM sessions
                WHERE conversation_id = ?
            """, (conversation_id,))
            
            sessions = cursor.fetchall()
            
            # 如果没有会话表，使用简化逻辑
            if not sessions:
                # 直接检查发言单元内容
                for unit in speech_units:
                    unit_id, content, _ = unit
                    content_lower = (content or "").lower()
                    
                    for keyword in self.preference_keywords:
                        if keyword.lower() in content_lower:
                            # 使用发言单元 ID 作为会话标识
                            preference_session_ids.add(unit_id)
                            matched_keywords.add(keyword)
                
                return list(preference_session_ids), list(matched_keywords)
            
            # 有会话表，检查每个会话的发言单元
            for session in sessions:
                session_id, start_unit_id, end_unit_id = session
                
                # 获取该会话内的发言单元
                for unit in speech_units:
                    unit_id, content, _ = unit
                    if start_unit_id <= unit_id <= end_unit_id:
                        content_lower = (content or "").lower()
                        
                        for keyword in self.preference_keywords:
                            if keyword.lower() in content_lower:
                                preference_session_ids.add(session_id)
                                matched_keywords.add(keyword)
                                break  # 找到一个关键词就标记该会话
            
            return list(preference_session_ids), list(matched_keywords)
            
        except Exception as e:
            logger.error(f"识别喜好会话失败: {e}")
            return [], []
    
    # ========================================
    # 子维度分数计算方法
    # ========================================
    
    def calculate_topic_mention_score(
        self,
        preference_session_count: int,
        total_session_count: int
    ) -> float:
        """
        计算话题提及频率得分 (0-100)
        
        公式: (包含喜好关键词的会话数 / 总会话数) × 100
        满分标准: 30% 以上提及率为满分
        """
        if total_session_count == 0:
            return 0.0
        
        frequency = preference_session_count / total_session_count
        # 30% 以上提及率为满分
        score = min((frequency / 0.30) * 100, 100)
        return round(score, 2)
    
    def _calculate_topic_mention_raw(
        self,
        preference_session_count: int,
        total_session_count: int
    ) -> float:
        """计算话题提及频率原始值 (0-1)"""
        if total_session_count == 0:
            return 0.0
        return preference_session_count / total_session_count
    
    def calculate_topic_continuity_score(
        self,
        conversation_id: int,
        preference_session_ids: List[int]
    ) -> float:
        """
        计算喜好话题延续性得分 (0-100)
        
        基于包含喜好关键词的会话内交互对的语义相似度平均值
        """
        continuity = self._calculate_topic_continuity_raw(
            conversation_id, preference_session_ids
        )
        # 相似度直接映射到 0-100
        return round(continuity * 100, 2)
    
    def _calculate_topic_continuity_raw(
        self,
        conversation_id: int,
        preference_session_ids: List[int]
    ) -> float:
        """
        计算喜好话题延续性原始值 (0-1)
        
        使用喜好会话内交互对的语义相似度平均值
        """
        if not preference_session_ids:
            return 0.0
        
        try:
            # 获取所有交互对的语义相似度
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
            logger.error(f"计算喜好话题延续性失败: {e}")
            return 0.0
    
    # ========================================
    # 综合评分和解释
    # ========================================
    
    def _calculate_overall_score(self, result: PreferenceCompatibilityResult) -> float:
        """
        计算综合评分 (加权平均)
        
        权重:
        - 话题提及频率: 40%
        - 喜好话题延续性: 60%
        """
        overall = (
            result.topic_mention_score * self.WEIGHT_TOPIC_MENTION +
            result.topic_continuity_score * self.WEIGHT_TOPIC_CONTINUITY
        )
        return round(overall, 2)
    
    def generate_interpretation(self, score: float) -> str:
        """
        根据分数生成解释文本
        
        Args:
            score: 综合评分 (0-100)
            
        Returns:
            解释文本
        """
        if score >= 80:
            return "兴趣高度契合，经常聊到共同喜好话题，话题延续性强"
        elif score >= 60:
            return "兴趣较为契合，偶尔聊到共同喜好话题"
        elif score >= 40:
            return "兴趣契合度一般，共同话题较少"
        elif score >= 20:
            return "兴趣契合度较低，很少涉及共同喜好"
        else:
            return "兴趣契合度很低，几乎没有共同话题"
