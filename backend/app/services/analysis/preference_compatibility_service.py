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
        pass  # get_db() removed for thread safety
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
        
        debug_log(f"\n{'*'*40}")
        debug_log(f"【喜好兼容度】开始计分 (会话 ID {conversation_id})")
        debug_log(f"*[注] 该项占总分20%权重，自身包含2个子维度*")
        
        # 如果没有喜好关键词，返回 0 分
        if not self.preference_keywords:
            debug_log(f"[喜好兼容度调试] 未设置喜好关键词({conversation_id})，该维度不参与好感度评分(权重降为0)")
            logger.info(f"未设置喜好关键词,喜好维度权重为 0 (会话 {conversation_id})")
            result.interpretation = "未设置喜好关键词,该维度不参与好感度评分"
            return result
        
        # 识别包含喜好关键词的会话
        preference_sessions, matched_keywords = self.identify_preference_sessions(
            conversation_id
        )
        result.preference_session_count = len(preference_sessions)
        result.matched_keywords = matched_keywords
        debug_log(f"[喜好兼容度调试] 当前配置的喜好关键词: {self.preference_keywords}")
        debug_log(f"[喜好兼容度调试] 命中喜好的会话数: {result.preference_session_count} / 总会话数: {stats.total_sessions}")
        debug_log(f"[喜好兼容度调试] 实际匹配到的关键词: {matched_keywords}")
        
        # 1. 话题提及频率 (40%)
        result.topic_mention_frequency = self._calculate_topic_mention_raw(
            len(preference_sessions), stats.total_sessions
        )
        result.topic_mention_score = self.calculate_topic_mention_score(
            len(preference_sessions), stats.total_sessions
        )
        debug_log(f"\n[喜好兼容度调试] --- 1. 话题提及频率 (权重40%) ---")
        debug_log(f"占比(频率): {result.topic_mention_frequency*100:.1f}% -> 得分: {result.topic_mention_score}")
        
        # 2. 喜好话题延续性 (60%)
        result.avg_continuity = self._calculate_topic_continuity_raw(
            conversation_id, preference_sessions
        )
        result.topic_continuity_score = self.calculate_topic_continuity_score(
            conversation_id, preference_sessions
        )
        debug_log(f"\n[喜好兼容度调试] --- 2. 喜好话题延续性 (权重60%) ---")
        debug_log(f"包含喜好的会话的平均相关度: {result.avg_continuity:.3f} -> 得分: {result.topic_continuity_score}")
        
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
            import json
            
            preference_session_ids: Set[int] = set()
            matched_keywords: Set[str] = set()
            
            # 第一步：获取所有发言单元的 message_ids
            cursor = get_db().execute("""
                SELECT su.id, su.message_ids, su.first_message_timestamp
                FROM speech_units su
                WHERE su.conversation_id = ?
                ORDER BY su.first_message_timestamp ASC
            """, (conversation_id,))
            speech_units = cursor.fetchall()
            
            # 第二步：收集所有 message_id 并批量查消息内容
            all_msg_ids = []
            unit_msg_map = {}  # {unit_id: [msg_id, ...]}
            for unit in speech_units:
                try:
                    msg_ids = json.loads(unit[1])
                    if msg_ids:
                        unit_msg_map[unit[0]] = msg_ids
                        all_msg_ids.extend(msg_ids)
                except:
                    pass
            
            # 批量查询消息内容
            msg_content_map = {}
            if all_msg_ids:
                placeholders = ','.join('?' * len(all_msg_ids))
                cursor = get_db().execute(f"""
                    SELECT id, content FROM messages WHERE id IN ({placeholders})
                """, all_msg_ids)
                for row in cursor.fetchall():
                    content = row[1]
                    if isinstance(content, bytes):
                        try:
                            content = content.decode('utf-8', errors='replace')
                        except:
                            content = ""
                    msg_content_map[row[0]] = content or ""
            
            # 第三步：组装发言单元内容并匹配关键词
            unit_contents = {}  # {unit_id: "拼接后的内容"}
            for unit in speech_units:
                unit_id = unit[0]
                msg_ids = unit_msg_map.get(unit_id, [])
                content = " ".join(msg_content_map.get(mid, "") for mid in msg_ids)
                unit_contents[unit_id] = content
            
            # 获取会话边界信息
            cursor = get_db().execute("""
                SELECT id, start_unit_id, end_unit_id
                FROM sessions
                WHERE conversation_id = ?
            """, (conversation_id,))
            sessions = cursor.fetchall()
            
            # 如果没有会话表，使用简化逻辑
            if not sessions:
                for unit_id, content in unit_contents.items():
                    content_lower = content.lower()
                    for keyword in self.preference_keywords:
                        if keyword.lower() in content_lower:
                            preference_session_ids.add(unit_id)
                            matched_keywords.add(keyword)
                return list(preference_session_ids), list(matched_keywords)
            
            # 有会话表，检查每个会话
            for session in sessions:
                session_id, start_unit_id, end_unit_id = session
                for unit_id, content in unit_contents.items():
                    if start_unit_id <= unit_id <= end_unit_id:
                        content_lower = content.lower()
                        for keyword in self.preference_keywords:
                            if keyword.lower() in content_lower:
                                preference_session_ids.add(session_id)
                                matched_keywords.add(keyword)
                                break
            
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
            cursor = get_db().execute("""
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
        if score >= 80:
            return "兴趣高度契合，经常聊到共同喜好话题，已获得较高的喜好加分"
        if score >= 60:
            return "兴趣较为契合，偶尔会延展到共同喜好话题，已获得中等喜好加分"
        if score >= 40:
            return "兴趣契合度一般，共同话题较少，获得少量喜好加分"
        if score >= 20:
            return "兴趣契合度较低，很少涉及共同喜好，喜好加分较少"
        return "兴趣契合度很低，几乎没有共同话题，暂时没有形成明显加分"
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
