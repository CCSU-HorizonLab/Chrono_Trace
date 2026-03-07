"""态度倾向服务 - 计算对方对关系的态度倾向

包含 2 个基础子维度：
1. 正面情绪出现频率 (50%权重)
2. 负面情绪出现频率 (50%权重，反向计分)

额外加分项（不在前端显示）：
- 信任倾诉加分：对方向你倾诉对他人的负面情绪，视为信任信号
- 多媒体(通话)加分：基于月均语音/视频通话频率
- 节日祝福加分：双方都发了或者一方发了，都有额外加分
- 专属称呼加分：如果对方在会话中主动叫了专属称呼，视为极高亲密度的加分项
- 节日祝福加分：双方都发了或者一方发了，都有额外加分
- 专属称呼加分：如果对方在会话中主动叫了专属称呼，视为极高亲密度的加分项

注意：
- 负面方向判定：区分"对我"、"对他人"、"模糊"
- "对我"才扣分，"对他人"触发信任加分，"模糊"忽略
- 前端显示原始频率值（低负面频率 = 好）
"""

import os
from typing import Dict, Any, List
from ...db.connection import get_db
from .preprocessing_orchestrator import PreprocessingOrchestrator
from .keyword_libraries import KeywordLibraries
from .negative_direction_service import NegativeDirectionService

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
        计算正面情绪出现频率 (30%权重)
        
        引入“语境主动性”：如果是对方主动发起的会话中，对方表达的正面情绪，赋予 1.5 倍权重。
        其余情况按 1.0 倍计算。
        
        公式: (加权正面消息数 / (正面消息数 + 负面消息数)) × 100%
        """
        stats = self.orchestrator.get_preprocessed_statistics(conversation_id)
        
        total_emotional = stats.total_positive_count + stats.total_negative_count
        if total_emotional == 0:
            return 0.0
            
        # 查询属于“对方主动发起的会话”中的由“对方发送”的正面情绪消息数
        # 由于 orchestrator.get_preprocessed_statistics 已经包含了全部的正面情绪数量，我们还需要进一步细分
        cursor = self.db.execute("""
            SELECT COUNT(*) 
            FROM messages m
            INNER JOIN sentiment_cache sc ON m.id = sc.message_id
            INNER JOIN sessions s ON m.timestamp BETWEEN s.start_time AND s.end_time AND m.conversation_id = s.conversation_id
            WHERE m.conversation_id = ?
              AND m.is_sender = 0
              AND m.message_type = 1
              AND sc.polarity = 1
              AND s.initiator = 'other'
        """, (conversation_id,))
        
        other_initiated_positive_count = cursor.fetchone()[0] or 0
        normal_positive_count = stats.total_positive_count - other_initiated_positive_count
        
        # 对方主动找我时的正面情绪，乘以1.5倍系数
        weighted_positive_count = normal_positive_count + (other_initiated_positive_count * 1.5)
        
        frequency = (weighted_positive_count / total_emotional) * 100
        
        if DEBUG_TRACE:
            debug_log("\n[态度调试] === 正面情绪频率（含语境主动性） ===")
            debug_log(f"[态度调试] 全部正面消息数: {stats.total_positive_count}")
            debug_log(f"[态度调试] 其中对方主动发起会话时的正面数: {other_initiated_positive_count} (权重x1.5)")
            debug_log(f"[态度调试] 其中其他情况的正面数: {normal_positive_count} (权重x1.0)")
            debug_log(f"[态度调试] 加权后的正面得分基数: {weighted_positive_count:.2f}")
            debug_log(f"[态度调试] 负面消息数: {stats.total_negative_count}")
            debug_log(f"[态度调试] 有效情绪总数(原始正+负): {total_emotional}")
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
        计算多媒体使用加分 (最高 20 分)
        
        基于通话频率计算（仅针对语音和视频通话）：
        公式: 平均每月通话次数 / 满分阈值(4次/月) * 20.0 加分
        """
        stats = self.orchestrator.get_preprocessed_statistics(conversation_id)
        
        if stats.total_message_count == 0:
            return 0.0
        
        # 仅统计语音和视频通话
        call_count = (
            stats.voice_message_count +
            stats.video_message_count
        )
        
        # 按自然日计算月份跨度（至少按1个月算）
        total_months = max(1.0, stats.chat_days_count / 30.0)
        calls_per_month = call_count / total_months
        
        # 优化算法：以一个月为周期。
        # 每月4次通话（约每周1次）即视为非常频繁，达到满分。
        # 恋人或密切家人间这个数字很容易达到，普通朋友较难，能有效区分亲密度。
        bonus_score = min(20.0, (calls_per_month / 4.0) * 20.0)
        
        if DEBUG_TRACE:
            debug_log("\n[态度调试] === 多媒体(通话)使用加分 ===")
            debug_log(f"[态度调试] 聊天总跨度(按天折算月): {total_months:.2f} 月")
            debug_log(f"[态度调试] 语音/视频通话总数: {call_count} 次")
            debug_log(f"[态度调试] 月均通话频率: {calls_per_month:.2f} 次/月 (满分阈值: 4次/月)")
            debug_log(f"[态度调试] 最终附加加分: +{bonus_score:.2f} 分")
            
        return bonus_score
    
    def calculate_nickname_frequency(
        self,
        conversation_id: int
    ) -> float:
        """
        计算专属称呼频率 (20%权重)
        
        优化思路3: 计算“涵盖专属称呼的对方参与会话数 / 总会话数”
        引入深夜机制: 深夜(23:00-05:00)提及专属称呼的会话, 权重 × 1.5
        """
        # 获取总会话数
        cursor = self.db.execute(
            "SELECT COUNT(*) FROM sessions WHERE conversation_id = ?",
            (conversation_id,)
        )
        total_sessions = cursor.fetchone()[0] or 0
        
        if total_sessions == 0:
            return 0.0
            
        # 考虑到预处理阶段没有落库单条消息的专属称呼标记，
        # 我们这里取全量由对方发送的消息，并联表获取它们所属的session_id
        cursor = self.db.execute("""
            SELECT 
                s.id as session_id,
                m.content,
                m.timestamp
            FROM sessions s
            INNER JOIN messages m ON m.timestamp BETWEEN s.start_time AND s.end_time 
                                 AND m.conversation_id = s.conversation_id
            WHERE s.conversation_id = ?
              AND m.is_sender = 0
              AND m.message_type = 1
        """, (conversation_id,))
        
        # 这个字典记录每个遇到专属称呼的session，是否在深夜发生过
        # 结构: { session_id: is_late_night_boolean }
        nickname_sessions = {}
        
        keywords = self.keyword_lib.get_all_keywords().get('nickname', [])
        
        for row in cursor.fetchall():
            session_id = row[0]
            content = row[1]
            timestamp = row[2]
            
            # 如果这个session已经被标记为含专属且且为深夜了，可以跳过（已达最高分）
            if nickname_sessions.get(session_id) is True:
                continue
                
            # 检查是否包含称呼
            has_nickname = False
            if content and isinstance(content, str):
                for kw in keywords:
                    if kw in content:
                        has_nickname = True
                        break
                        
            if has_nickname:
                # 检查是否深夜
                is_late_night = False
                if timestamp:
                    from datetime import datetime
                    msg_dt = datetime.fromtimestamp(timestamp)
                    if msg_dt.hour >= 23 or msg_dt.hour < 5:
                        is_late_night = True
                
                # 更新字典：如果没记录过，直接存入。如果记录过且这次是深夜，升级为True
                if session_id not in nickname_sessions:
                    nickname_sessions[session_id] = is_late_night
                elif is_late_night:
                    nickname_sessions[session_id] = True
                    
        # 结算
        weighted_nickname_session_count = 0.0
        for s_id, is_late in nickname_sessions.items():
            if is_late:
                weighted_nickname_session_count += 1.5
            else:
                weighted_nickname_session_count += 1.0
                
        # 放大系数：只要包含一次就非常重要。假设20%的会话含有称呼即可拿满15分附加分。
        frequency_ratio = weighted_nickname_session_count / total_sessions
        bonus_score = min(15.0, (frequency_ratio / 0.2) * 15.0)
        
        if DEBUG_TRACE:
            debug_log("\n[态度调试] === 专属称呼会话加分（思路3） ===")
            debug_log(f"[态度调试] 总会话数: {total_sessions}")
            debug_log(f"[态度调试] 包含专属称呼的会话数: {len(nickname_sessions)}")
            debug_log(f"[态度调试] 加权后会话数: {weighted_nickname_session_count:.2f} (包含深夜1.5倍机制)")
            debug_log(f"[态度调试] 计算得出附加加分: +{bonus_score:.2f} 分")
            
        return bonus_score
    
    def calculate_holiday_greeting(
        self,
        conversation_id: int
    ) -> float:
        """
        计算节日祝福附加分
        
        只要包含节日祝福即可加分，满分为 10 分附加分，根据 (独立节日日期数 / 总节日数) 的比例计算
        """
        from .holiday_library import HolidayLibrary
        stats = self.orchestrator.get_preprocessed_statistics(conversation_id)
        
        total_holidays = (
            len(HolidayLibrary.FIXED_HOLIDAYS) +
            len(HolidayLibrary.LUNAR_HOLIDAYS_RANGE) +
            len(HolidayLibrary.FLOATING_HOLIDAYS)
        )
        if total_holidays == 0:
            return 0.0
        
        # 将节日祝福频率映射为最高 10 分的附加分
        frequency_ratio = stats.holidays_sent_count / total_holidays
        bonus_score = min(10.0, frequency_ratio * 10 * 3) # 放大系数3，让附加分更容易获得
        
        if DEBUG_TRACE:
            debug_log("\n[态度调试] === 节日祝福加分 ===")
            debug_log(f"[态度调试] 独立互动节日总数: {stats.holidays_sent_count}")
            debug_log(f"[态度调试] 系统内置总节日数: {total_holidays}")
            debug_log(f"[态度调试] 计算得出附加加分: +{bonus_score:.2f} 分")
            
        return bonus_score
    
    def calculate_overall_attitude(
        self,
        conversation_id: int
    ) -> Dict[str, Any]:
        """
        计算态度倾向总分
        
        权重分配（2个显示维度，剔除专属称呼、假日、隐私和多媒体后的100%均分）：
        - 正面情绪出现频率: 50%
        - 负面情绪得分: 50% (反向计分)
        
        额外加分（不显示）：
        - 信任倾诉加分: 直接加到总分
        - 多媒体通话加分: 直接加到总分
        - 节日祝福加分: 直接加到总分
        - 专属称呼加分: 直接加到总分
        
        sub_scores 中所有值都是原始频率/比率（0-100）：
        - 正面情绪: 越高越好
        - 负面情绪: 越低越好（前端需要反转评级）
        """
        debug_log(f"\n{'='*60}")
        debug_log(f"[态度调试] 开始计算态度倾向 (conversation_id={conversation_id})")
        debug_log(f"{'='*60}")
        
        # 计算各子维度
        positive_freq = self.calculate_positive_word_frequency(conversation_id)
        
        # 负面方向判定（含深夜信任倾诉加成）
        negative_info = self.calculate_negative_with_direction(conversation_id)
        negative_score = negative_info["negative_score"]  # 反向得分，参与加权
        # 信任倾诉及专属称呼、节日加分（独立加到总分上）
        attitude_stats = self.orchestrator.get_preprocessed_statistics(conversation_id)
        
        # 基础信任加分
        base_trust_bonus = min(20.0, negative_info["trust_bonus"])
        
        # 深夜隐私倾诉额外加分 (最高 10 分)
        late_night_privacy_bonus = min(10.0, attitude_stats.privacy_message_count * 2.0)
        trust_bonus = min(30.0, base_trust_bonus + late_night_privacy_bonus)
        
        multimedia_bonus = self.calculate_multimedia_usage(conversation_id) # 现为附加分
        nickname_bonus = self.calculate_nickname_frequency(conversation_id) # 现为附加分
        holiday_bonus = self.calculate_holiday_greeting(conversation_id) # 获取附加加分
        
        # 2个主维度加权 (50 + 50 = 100)
        weighted_total = (
            positive_freq * 0.50 +
            negative_score * 0.50
        )
        
        # 信任倾诉、多媒体、专属称呼、节日加分（独立加到总分上）
        overall_score = weighted_total + trust_bonus + holiday_bonus + nickname_bonus + multimedia_bonus
        overall_score = max(0.0, min(100.0, overall_score))
        
        debug_log(f"\n[态度调试] === 最终加权计算 ===")
        debug_log(f"[态度调试] 正面情绪频率: {positive_freq:.2f} × 0.50 = {positive_freq*0.50:.2f}")
        debug_log(f"[态度调试] 负面情绪得分: {negative_score:.2f} × 0.50 = {negative_score*0.50:.2f}")
        debug_log(f"[态度调试] 2主维度加权合计: {weighted_total:.2f}")
        debug_log(f"[态度调试] + 信任倾诉加分: {trust_bonus:.2f}")
        debug_log(f"[态度调试] + 多媒体(通话)加分: {multimedia_bonus:.2f}")
        debug_log(f"[态度调试] + 节日互动加分: {holiday_bonus:.2f}")
        debug_log(f"[态度调试] + 专属称呼加分: {nickname_bonus:.2f}")
        debug_log(f"[态度调试] === 总分: {overall_score:.2f} ===")
        debug_log(f"{'='*60}\n")
        
        return {
            "overall_score": round(overall_score, 2),
            "sub_scores": {
                # 仅保留基础维度，移除 bonus 类维度
                "positive_emotion_frequency": round(positive_freq, 2),
                "negative_emotion_frequency": round(negative_info["raw_frequency"], 2),
            },
            "bonus_scores": {
                "trust_bonus": round(trust_bonus, 2),
                "multimedia_bonus": round(multimedia_bonus, 2),
                "holiday_bonus": round(holiday_bonus, 2),
                "nickname_bonus": round(nickname_bonus, 2),
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
