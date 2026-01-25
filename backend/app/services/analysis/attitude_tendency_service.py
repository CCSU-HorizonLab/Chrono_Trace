"""态度倾向服务 - 计算对方对关系的态度倾向

包含 6 个子维度：
1. 正面词频率 (25%权重)
2. 负面词频率 (-20%权重，反向计分)
3. 多媒体使用率 (15%权重)
4. 专属称呼频率 (25%权重)
5. 隐私分享频率 (20%权重)
6. 节日祝福频率 (15%权重)

注意：负面词频率是反向计分，频率越高得分越低
"""

from typing import Dict, Any
from ...db.connection import get_db
from .preprocessing_orchestrator import PreprocessingOrchestrator
from .keyword_libraries import KeywordLibraries


class AttitudeTendencyService:
    """态度倾向服务"""
    
    def __init__(self):
        self.db = get_db()
        self.orchestrator = PreprocessingOrchestrator()
        self.keyword_lib = KeywordLibraries()
    
    def calculate_positive_word_frequency(
        self,
        conversation_id: int
    ) -> float:
        """
        计算正面词频率 (25%权重)
        
        公式: (正面消息数 / 总消息数) × 100%
        
        Args:
            conversation_id: 会话ID
        
        Returns:
            频率 (0-100)
        """
        # 使用预处理的统计数据 (O(1) vs O(N))
        stats = self.orchestrator.get_preprocessed_statistics(conversation_id)
        
        if stats.total_message_count == 0:
            return 0.0
        
        frequency = (stats.total_positive_count / stats.total_message_count) * 100
        return min(100.0, frequency)
    
    def calculate_negative_word_frequency(
        self,
        conversation_id: int
    ) -> float:
        """
        计算负面词频率 (-20%权重，反向计分)
        
        公式: (负面消息数 / 总消息数) × 100%
        注意：这个值会在 calculate_overall_attitude 中反向计分
        
        Args:
            conversation_id: 会话ID
        
        Returns:
            频率 (0-100)
        """
        # 使用预处理的统计数据 (O(1) vs O(N))
        stats = self.orchestrator.get_preprocessed_statistics(conversation_id)
        
        if stats.total_message_count == 0:
            return 0.0
        
        frequency = (stats.total_negative_count / stats.total_message_count) * 100
        return min(100.0, frequency)
    
    def calculate_multimedia_usage(
        self,
        conversation_id: int
    ) -> float:
        """
        计算多媒体使用率 (15%权重)
        
        公式: ((表情包数 + 语音数 + 视频数) / 总消息数) × 100%
        
        Args:
            conversation_id: 会话ID
        
        Returns:
            使用率 (0-100)
        """
        # 使用预处理的统计数据 (O(1) vs O(N))
        stats = self.orchestrator.get_preprocessed_statistics(conversation_id)
        
        if stats.total_message_count == 0:
            return 0.0
        
        multimedia_count = (
            stats.emoji_message_count +
            stats.voice_message_count +
            stats.video_message_count
        )
        
        usage_rate = (multimedia_count / stats.total_message_count) * 100
        return min(100.0, usage_rate)
    
    def calculate_nickname_frequency(
        self,
        conversation_id: int
    ) -> float:
        """
        计算专属称呼频率 (25%权重)
        
        公式: (专属称呼消息数 / 总消息数) × 100%
        
        Args:
            conversation_id: 会话ID
        
        Returns:
            频率 (0-100)
        """
        # 使用预处理的统计数据 (O(1) vs O(N))
        stats = self.orchestrator.get_preprocessed_statistics(conversation_id)
        
        if stats.total_message_count == 0:
            return 0.0
        
        frequency = (stats.nickname_message_count / stats.total_message_count) * 100
        return min(100.0, frequency)
    
    def calculate_privacy_sharing(
        self,
        conversation_id: int
    ) -> float:
        """
        计算隐私分享频率 (20%权重)
        
        公式: (隐私分享消息数 / 总消息数) × 100%
        
        Args:
            conversation_id: 会话ID
        
        Returns:
            频率 (0-100)
        """
        # 使用预处理的统计数据 (O(1) vs O(N))
        stats = self.orchestrator.get_preprocessed_statistics(conversation_id)
        
        if stats.total_message_count == 0:
            return 0.0
        
        frequency = (stats.privacy_message_count / stats.total_message_count) * 100
        return min(100.0, frequency)
    
    def calculate_holiday_greeting(
        self,
        conversation_id: int
    ) -> float:
        """
        计算节日祝福频率 (15%权重)
        
        公式: (独立节日日期数 / 总聊天天数) × 100%
        
        Args:
            conversation_id: 会话ID
        
        Returns:
            频率 (0-100)
        """
        # 使用预处理的统计数据 (O(1) vs O(N))
        stats = self.orchestrator.get_preprocessed_statistics(conversation_id)
        
        if stats.chat_days_count == 0:
            return 0.0
        
        # holidays_sent_count 是独立节日日期数（已去重）
        frequency = (stats.holidays_sent_count / stats.chat_days_count) * 100
        
        # 节日祝福频率可能超过100%（一天多个节日），所以限制上限
        return min(100.0, frequency)
    
    def calculate_overall_attitude(
        self,
        conversation_id: int
    ) -> Dict[str, Any]:
        """
        计算态度倾向总分
        
        权重分配：
        - 正面词频率: 25%
        - 负面词频率: -20% (反向计分)
        - 多媒体使用率: 15%
        - 专属称呼频率: 25%
        - 隐私分享频率: 20%
        - 节日祝福频率: 15%
        
        注意：负面词频率是反向计分，公式为 100 - 负面词频率
        
        Args:
            conversation_id: 会话ID
        
        Returns:
            {
                "overall_score": 总分 (0-100),
                "sub_scores": {
                    "positive_word_frequency": 得分,
                    "negative_word_frequency": 得分,
                    "multimedia_usage": 得分,
                    "nickname_frequency": 得分,
                    "privacy_sharing": 得分,
                    "holiday_greeting": 得分
                },
                "interpretation": 解释文本
            }
        """
        # 计算各子维度
        positive_freq = self.calculate_positive_word_frequency(conversation_id)
        negative_freq = self.calculate_negative_word_frequency(conversation_id)
        multimedia = self.calculate_multimedia_usage(conversation_id)
        nickname = self.calculate_nickname_frequency(conversation_id)
        privacy = self.calculate_privacy_sharing(conversation_id)
        holiday = self.calculate_holiday_greeting(conversation_id)
        
        # 负面词频率反向计分
        negative_score = 100 - negative_freq
        
        # 加权总分
        overall_score = (
            positive_freq * 0.25 +
            negative_score * 0.20 +  # 注意：这里用的是反向分数
            multimedia * 0.15 +
            nickname * 0.25 +
            privacy * 0.20 +
            holiday * 0.15
        )
        
        return {
            "overall_score": round(overall_score, 2),
            "sub_scores": {
                "positive_word_frequency": round(positive_freq, 2),
                "negative_word_frequency": round(negative_freq, 2),  # 原始频率
                "multimedia_usage": round(multimedia, 2),
                "nickname_frequency": round(nickname, 2),
                "privacy_sharing": round(privacy, 2),
                "holiday_greeting": round(holiday, 2)
            },
            "interpretation": self.generate_interpretation(overall_score)
        }
    
    def generate_interpretation(self, score: float) -> str:
        """
        生成解释文本
        
        Args:
            score: 总分 (0-100)
        
        Returns:
            解释文本
        """
        if score >= 80:
            return "对方对这段关系非常重视，态度积极且投入度高"
        elif score >= 60:
            return "对方对这段关系较为重视，态度总体积极"
        elif score >= 40:
            return "对方对这段关系态度中立，投入度一般"
        elif score >= 20:
            return "对方对这段关系投入度较低，态度偏消极"
        else:
            return "对方对这段关系投入度很低，态度消极"
