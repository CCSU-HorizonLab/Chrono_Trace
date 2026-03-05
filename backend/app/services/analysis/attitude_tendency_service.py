"""态度倾向服务 - 计算对方对关系的态度倾向

包含 6 个子维度：
1. 正面情绪出现频率 (20%权重)
2. 负面情绪出现频率 (20%权重，反向计分)
3. 多媒体使用率 (15%权重)
4. 专属称呼频率 (20%权重)
5. 隐私分享频率 (15%权重)
6. 节日祝福频率 (10%权重)

额外加分项（不在前端显示）：
- 信任倾诉加分：对方向你倾诉对他人的负面情绪，视为信任信号

注意：
- 负面方向判定：区分"对我"、"对他人"、"模糊"
- "对我"才扣分，"对他人"触发信任加分，"模糊"忽略
- 前端显示原始频率值（低负面频率 = 好）
"""

import logging
import os
from typing import Dict, Any, List
from ...db.connection import get_db
from .preprocessing_orchestrator import PreprocessingOrchestrator
from .keyword_libraries import KeywordLibraries
from .negative_direction_service import NegativeDirectionService

logger = logging.getLogger(__name__)

# ===== 调试开关：设为True时输出详细跟踪日志 =====
DEBUG_TRACE = True

def debug_log(msg: str):
    """专门用于记录分析调试的物理日志"""
    if DEBUG_TRACE:
        from .affinity_debug_logger import affinity_debug_log
        affinity_debug_log(msg)


class AttitudeTendencyService:
    """态度倾向服务"""
    
    def __init__(self):
        self.db = get_db()
        self.orchestrator = PreprocessingOrchestrator()
        self.keyword_lib = KeywordLibraries()
        self.direction_service = NegativeDirectionService()
    
    def calculate_positive_word_frequency(
        self,
        conversation_id: int
    ) -> float:
        """
        计算正面情绪出现频率 (20%权重)
        
        公式: (正面消息数 / 总消息数) × 100%
        """
        stats = self.orchestrator.get_preprocessed_statistics(conversation_id)
        
        if stats.total_message_count == 0:
            return 0.0
        
        frequency = (stats.total_positive_count / stats.total_message_count) * 100
        
        if DEBUG_TRACE:
            debug_log("\n[态度调试] === 正面情绪频率 ===")
            debug_log(f"[态度调试] 正面消息数: {stats.total_positive_count}")
            debug_log(f"[态度调试] 总消息数: {stats.total_message_count}")
            debug_log(f"[态度调试] 频率: {frequency:.2f}%")
        
        return min(100.0, frequency)
    
    def calculate_negative_with_direction(
        self,
        conversation_id: int
    ) -> Dict[str, Any]:
        """
        分析负面消息方向并计算相关数值
        
        返回：
        - raw_frequency: 原始负面频率（前端显示用，越低越好）
        - negative_score: 反向得分（参与加权计算，越高越好）
        - trust_bonus: 信任倾诉加分（独立加到总分）
        - 各方向统计数
        """
        stats = self.orchestrator.get_preprocessed_statistics(conversation_id)
        
        if stats.total_message_count == 0:
            return {
                "raw_frequency": 0.0,
                "negative_score": 100.0,
                "trust_bonus": 0.0,
                "to_me_count": 0,
                "to_others_count": 0,
                "ambiguous_count": 0,
                "total_negative_count": 0,
            }
        
        # 获取对方发送的负面消息内容
        negative_messages = self._get_negative_messages(conversation_id)
        
        # 逐条判定方向
        to_me_count = 0
        to_others_count = 0
        ambiguous_count = 0
        
        if DEBUG_TRACE:
            debug_log(f"\n[态度调试] === 负面情绪方向判定（共{len(negative_messages)}条负面消息）===")
        
        for i, msg in enumerate(negative_messages):
            result = self.direction_service.classify(msg["content"])
            
            if DEBUG_TRACE:
                content_preview = msg["content"][:40].replace('\n', ' ')
                debug_log(
                    f"[态度调试] [{i+1:3d}] "
                    f"方向={result.direction:10s} "
                    f"置信={result.confidence:.2f} "
                    f"| \"{content_preview}...\""
                )
                if result.reason:
                    debug_log(f"[态度调试]       ↳ {result.reason}")
            
            if result.direction == "to_me":
                to_me_count += 1
            elif result.direction == "to_others":
                to_others_count += 1
            else:
                ambiguous_count += 1
        
        total_negative = len(negative_messages)
        
        # ---- 计算各项数值 ----
        
        # 原始负面频率（前端显示用：越低越好）
        raw_frequency = (total_negative / stats.total_message_count) * 100
        
        # 有效负面频率（仅 to_me 计入扣分）
        effective_neg_freq = (to_me_count / stats.total_message_count) * 100
        
        # 负面得分（参与加权，越高代表负面越少 = 越好）
        negative_score = max(0.0, min(100.0, 100 - effective_neg_freq))
        
        # 信任倾诉加分（独立项，不混入负面得分）
        # 放大系数20，上限30分
        trust_bonus = min(30.0, (to_others_count / stats.total_message_count) * 20 * 100)
        
        if DEBUG_TRACE:
            debug_log(f"\n[态度调试] === 负面频率汇总 ===")
            debug_log(f"[态度调试] to_me: {to_me_count}, to_others: {to_others_count}, ambiguous: {ambiguous_count}")
            debug_log(f"[态度调试] 原始负面频率(前端显示): {raw_frequency:.2f}%")
            debug_log(f"[态度调试] 有效负面频率(仅to_me): {effective_neg_freq:.2f}%")
            debug_log(f"[态度调试] 负面得分(参与加权): {negative_score:.2f}")
            debug_log(f"[态度调试] 信任倾诉加分(独立加分): {trust_bonus:.2f}")
        
        return {
            "raw_frequency": round(raw_frequency, 2),
            "negative_score": round(negative_score, 2),
            "trust_bonus": round(trust_bonus, 2),
            "to_me_count": to_me_count,
            "to_others_count": to_others_count,
            "ambiguous_count": ambiguous_count,
            "total_negative_count": total_negative,
        }
    
    def calculate_multimedia_usage(
        self,
        conversation_id: int
    ) -> float:
        """
        计算多媒体使用率 (15%权重)
        
        公式: ((表情包数 + 语音数 + 视频数) / 总消息数) × 100%
        """
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
        计算专属称呼频率 (20%权重)
        
        公式: (专属称呼消息数 / 总消息数) × 100%
        """
        stats = self.orchestrator.get_preprocessed_statistics(conversation_id)
        
        if stats.total_message_count == 0:
            return 0.0
        
        frequency = (stats.nickname_message_count / stats.total_message_count) * 100
        return min(100.0, frequency)
    
    def calculate_holiday_greeting(
        self,
        conversation_id: int
    ) -> float:
        """
        计算节日祝福频率 (10%权重)
        
        公式: (独立节日日期数 / 总聊天天数) × 100%
        """
        stats = self.orchestrator.get_preprocessed_statistics(conversation_id)
        
        if stats.chat_days_count == 0:
            return 0.0
        
        frequency = (stats.holidays_sent_count / stats.chat_days_count) * 100
        return min(100.0, frequency)
    
    def calculate_overall_attitude(
        self,
        conversation_id: int
    ) -> Dict[str, Any]:
        """
        计算态度倾向总分
        
        权重分配（5个显示维度，剔除隐私分享并将15%权重平分给其他维度）：
        - 正面情绪出现频率: 25% (+5%)
        - 负面情绪得分: 25% (+5%) (反向计分)
        - 多媒体使用率: 15%
        - 专属称呼频率: 25% (+5%)
        - 节日祝福频率: 10%
        
        额外加分（不显示）：
        - 信任倾诉加分: 直接加到总分
        
        sub_scores 中所有值都是原始频率/比率（0-100）：
        - 正面情绪: 越高越好
        - 负面情绪: 越低越好（前端需要反转评级）
        """
        debug_log(f"\n{'='*60}")
        debug_log(f"[态度调试] 开始计算态度倾向 (conversation_id={conversation_id})")
        debug_log(f"{'='*60}")
        
        # 计算各子维度
        positive_freq = self.calculate_positive_word_frequency(conversation_id)
        
        # 负面方向判定
        negative_info = self.calculate_negative_with_direction(conversation_id)
        negative_score = negative_info["negative_score"]  # 反向得分，参与加权
        trust_bonus = negative_info["trust_bonus"]         # 独立加分
        
        multimedia = self.calculate_multimedia_usage(conversation_id)
        nickname = self.calculate_nickname_frequency(conversation_id)
        holiday = self.calculate_holiday_greeting(conversation_id)
        
        # 5个维度加权 (25 + 25 + 15 + 25 + 10 = 100)
        weighted_total = (
            positive_freq * 0.25 +
            negative_score * 0.25 +
            multimedia * 0.15 +
            nickname * 0.25 +
            holiday * 0.10
        )
        
        # 信任倾诉加分（独立加到总分上）
        overall_score = weighted_total + trust_bonus
        overall_score = max(0.0, min(100.0, overall_score))
        
        debug_log(f"\n[态度调试] === 最终加权计算 ===")
        debug_log(f"[态度调试] 正面情绪频率: {positive_freq:.2f} × 0.25 = {positive_freq*0.25:.2f}")
        debug_log(f"[态度调试] 负面情绪得分: {negative_score:.2f} × 0.25 = {negative_score*0.25:.2f}")
        debug_log(f"[态度调试] 多媒体使用率: {multimedia:.2f} × 0.15 = {multimedia*0.15:.2f}")
        debug_log(f"[态度调试] 专属称呼频率: {nickname:.2f} × 0.25 = {nickname*0.25:.2f}")
        debug_log(f"[态度调试] 节日祝福频率: {holiday:.2f} × 0.10 = {holiday*0.10:.2f}")
        debug_log(f"[态度调试] 5维度加权合计: {weighted_total:.2f}")
        debug_log(f"[态度调试] + 信任倾诉加分: {trust_bonus:.2f}")
        debug_log(f"[态度调试] === 总分: {overall_score:.2f} ===")
        debug_log(f"{'='*60}\n")
        
        return {
            "overall_score": round(overall_score, 2),
            "sub_scores": {
                # 所有值均为原始频率（0-100），前端直接显示
                "positive_emotion_frequency": round(positive_freq, 2),
                "negative_emotion_frequency": round(negative_info["raw_frequency"], 2),
                "multimedia_usage": round(multimedia, 2),
                "nickname_frequency": round(nickname, 2),
                "holiday_greeting": round(holiday, 2),
            },
            "negative_direction_detail": {
                "to_me_count": negative_info["to_me_count"],
                "to_others_count": negative_info["to_others_count"],
                "ambiguous_count": negative_info["ambiguous_count"],
                "trust_bonus": negative_info["trust_bonus"],
            },
            "interpretation": self.generate_interpretation(overall_score)
        }
    
    def generate_interpretation(self, score: float) -> str:
        """生成解释文本"""
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
    
    # ===== 辅助方法 =====
    
    def _get_negative_messages(self, conversation_id: int) -> List[Dict[str, Any]]:
        """
        获取对方发送的负面消息列表
        """
        cursor = self.db.execute("""
            SELECT m.id, m.content
            FROM messages m
            INNER JOIN sentiment_cache sc ON m.id = sc.message_id
            WHERE m.conversation_id = ?
              AND m.is_sender = 0
              AND m.message_type = 1
              AND sc.polarity = -1
        """, (conversation_id,))
        
        messages = []
        for row in cursor.fetchall():
            content = row[1]
            if isinstance(content, bytes):
                try:
                    content = content.decode('utf-8', errors='replace')
                except:
                    content = ""
            elif not isinstance(content, str):
                content = str(content) if content is not None else ""
            messages.append({
                "id": row[0],
                "content": content or "",
            })
        
        return messages
