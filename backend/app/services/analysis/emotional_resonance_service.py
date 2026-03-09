"""情感共振率服务 - 计算情感共鸣程度

包含5个子维度:
1. 双向积极情感响应率 (20%权重)
2. 情感极性一致性 (15%权重)
3. 情绪强度匹配度 (10%权重)
4. 共情意图识别率 (30%权重)
5. 负面情绪协同化解率 (25%权重)

注意: 负面化解率现在考虑负面方向判定，
"对他人"的负面倾诉不计入需要化解的分母。
"""

import math
from typing import Dict, Any, List, Optional
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


class EmotionalResonanceService:
    """情感共振率服务"""
    
    def __init__(self):
        pass  # get_db() removed for thread safety
        self.orchestrator = PreprocessingOrchestrator()
        self.keyword_lib = KeywordLibraries()
        self.direction_service = NegativeDirectionService()
    
    def calculate_bidirectional_positive_response(
        self,
        conversation_id: int
    ) -> float:
        """
        计算双向积极情感响应率 (20%权重)
        
        公式: (positive-positive交互对数 / 总积极消息数) × 100%
        
        Args:
            conversation_id: 会话ID
        
        Returns:
            响应率 (0-100)
        """
        # 获取预处理统计
        stats = self.orchestrator.get_preprocessed_statistics(conversation_id)
        total_positive_count = stats.total_positive_count
        
        if total_positive_count == 0:
            return 0.0
        
        # 获取交互对
        pairs = self._get_interaction_pairs(conversation_id)
        
        # 计算positive-positive对数
        positive_positive_count = sum(
            1 for pair in pairs 
            if pair['from_polarity'] == 1 and pair['to_polarity'] == 1
        )
        
        rate = (positive_positive_count / total_positive_count) * 100
        
        debug_log(f"\n[情感共振调试] --- 1. 双向积极情感响应率 (权重20%) ---")
        debug_log(f"总积极消息数: {total_positive_count}, 积极-积极响应对数: {positive_positive_count}")
        debug_log(f"响应率: {rate:.1f}%")
        
        return round(rate, 2)
    
    def calculate_polarity_consistency(
        self,
        conversation_id: int
    ) -> float:
        """
        计算情感极性一致性 (15%权重)
        
        公式: (同极性交互对比例) × (同极性对的平均语义相似度)
        
        Args:
            conversation_id: 会话ID
        
        Returns:
            一致性得分 (0-1,需要×100转为百分制)
        """
        pairs = self._get_interaction_pairs(conversation_id)
        
        if not pairs:
            return 0.0
        
        # 筛选同极性对
        same_polarity_pairs = [
            pair for pair in pairs 
            if pair['from_polarity'] == pair['to_polarity']
        ]
        
        if not same_polarity_pairs:
            return 0.0
        
        # 同极性比例
        ratio = len(same_polarity_pairs) / len(pairs)
        
        # 同极性对的平均语义相似度
        avg_similarity = sum(
            pair['semantic_similarity'] or 0.0 
            for pair in same_polarity_pairs
        ) / len(same_polarity_pairs)
        
        # 极性一致性得分
        score = ratio * avg_similarity
        
        debug_log(f"\n[情感共振调试] --- 2. 情感极性一致性 (权重15%) ---")
        debug_log(f"同极性交互对数: {len(same_polarity_pairs)} / 交互对总数: {len(pairs)} (比例: {ratio*100:.1f}%)")
        debug_log(f"同极性平均语义相似度: {avg_similarity:.3f} -> 一致性得分: {score*100:.2f}")
        
        # 转换为百分制
        return round(score * 100, 2)
    
    def calculate_intensity_matching(
        self,
        conversation_id: int
    ) -> float:
        """
        计算情绪强度匹配度 (10%权重)
        
        公式: 1 / (mean_abs_diff + 0.1), 使用tanh归一化到0-1
        
        Args:
            conversation_id: 会话ID
        
        Returns:
            匹配度得分 (0-100)
        """
        pairs = self._get_interaction_pairs(conversation_id)
        
        if not pairs:
            return 0.0
        
        # 计算强度差异
        intensity_diffs = [
            abs(pair['from_intensity'] - pair['to_intensity']) 
            for pair in pairs
        ]
        
        mean_abs_diff = sum(intensity_diffs) / len(intensity_diffs)
        
        # 强度匹配度
        raw_score = 1 / (mean_abs_diff + 0.1)
        
        # 使用tanh归一化到0-1
        normalized_score = math.tanh(raw_score)
        
        debug_log(f"\n[情感共振调试] --- 3. 情绪强度匹配度 (权重10%) ---")
        debug_log(f"平均强度差异(mean_abs_diff): {mean_abs_diff:.3f} -> 归一化得分: {normalized_score*100:.2f}")
        
        # 转换为百分制
        return round(normalized_score * 100, 2)
    
    def calculate_empathy_recognition(
        self,
        conversation_id: int
    ) -> float:
        """
        计算共情意图识别率 (30%权重)
        
        公式: (包含共情关键词的消息数 / 总消息数) × 100%
        
        Args:
            conversation_id: 会话ID
        
        Returns:
            识别率 (0-100)
        """
        # 获取预处理统计
        stats = self.orchestrator.get_preprocessed_statistics(conversation_id)
        total_messages = stats.total_message_count
        
        if total_messages == 0:
            return 0.0
        
        # 获取共情关键词
        empathy_keywords = self.keyword_lib.get_keywords('empathy')
        
        if not empathy_keywords:
            return 0.0
        
        # 统计包含共情词的消息数
        empathy_count = self._count_messages_with_keywords(
            conversation_id, 
            empathy_keywords
        )
        
        rate = (empathy_count / total_messages) * 100
        
        debug_log(f"\n[情感共振调试] --- 4. 共情意图识别率 (权重30%) ---")
        debug_log(f"包含共情关键词消息数: {empathy_count} / 总消息数: {total_messages}")
        debug_log(f"识别率: {rate:.1f}%")
        
        return round(rate, 2)
    
    def calculate_negative_resolution(
        self,
        conversation_id: int
    ) -> float:
        """
        计算负面情绪协同化解率 (25%权重)
        
        公式: (共情回复数 / 需要化解的负面交互对数) × 100%
        共情回复定义: 积极极性 AND 包含安抚关键词
        
        注意: 现在考虑负面方向判定：
        - "对我"方向的负面需要化解
        - "模糊"方向的负面也纳入化解统计
        - "对他人"方向的负面是信任倾诉，不需要化解，不计入分母
        
        Args:
            conversation_id: 会话ID
        
        Returns:
            化解率 (0-100)
        """
        pairs = self._get_interaction_pairs(conversation_id)
        
        # 筛选负面发起的交互对
        negative_pairs = [
            pair for pair in pairs 
            if pair['from_polarity'] == -1
        ]
        
        if not negative_pairs:
            return 0.0
        
        # 使用方向判定过滤：只保留"对我"和"模糊"方向的负面
        # "对他人"的负面是倾诉行为，不需要化解
        needs_resolution_pairs = []
        for pair in negative_pairs:
            from_content = pair.get('from_content', '')
            if from_content:
                direction_result = self.direction_service.classify(from_content)
                if direction_result.direction != "to_others":
                    needs_resolution_pairs.append(pair)
            else:
                # 无法获取内容时保守处理，纳入化解统计
                needs_resolution_pairs.append(pair)
        
        if not needs_resolution_pairs:
            return 100.0  # 所有负面都是倾诉性质，化解率满分
        
        # 获取安抚关键词
        soothing_keywords = self.keyword_lib.get_keywords('soothing')
        
        if not soothing_keywords:
            return 0.0
        
        # 计算共情回复数
        empathetic_count = 0
        for pair in needs_resolution_pairs:
            # 检查回复是否为积极 + 包含安抚词
            if pair['to_polarity'] == 1:
                if self._contains_keywords(pair['to_content'], soothing_keywords):
                    empathetic_count += 1
        
        rate = (empathetic_count / len(needs_resolution_pairs)) * 100
        
        debug_log(f"\n[情感共振调试] --- 5. 负面情绪协同化解率 (权重25%) ---")
        debug_log(f"需要化解的负面交互对数(排除'对他人'): {len(needs_resolution_pairs)}")
        debug_log(f"其中包含安抚词的积极回复数: {empathetic_count} -> 化解率: {rate:.1f}%")
        
        return round(rate, 2)
    
    def calculate_overall_resonance(
        self,
        conversation_id: int
    ) -> Dict[str, Any]:
        """
        计算情感共振率总分
        
        权重分配:
        - 双向积极情感响应率: 20%
        - 情感极性一致性: 15%
        - 情绪强度匹配度: 10%
        - 共情意图识别率: 30%
        - 负面情绪协同化解率: 25%
        
        Args:
            conversation_id: 会话ID
        
        Returns:
            {
                "overall_score": 总分 (0-100),
                "sub_scores": {
                    "bidirectional_positive_response": 得分,
                    "polarity_consistency": 得分,
                    "intensity_matching": 得分,
                    "empathy_recognition": 得分,
                    "negative_resolution": 得分
                },
                "interpretation": 解释文本
            }
        """
        
        debug_log(f"\n{'*'*40}")
        debug_log(f"【情感共振率】开始计分 (会话 ID {conversation_id})")
        debug_log(f"*[注] 该项占总分30%权重，自身包含5个子维度*")
        
        # 计算5个子维度
        bidirectional_rate = self.calculate_bidirectional_positive_response(conversation_id)
        polarity_score = self.calculate_polarity_consistency(conversation_id)
        intensity_score = self.calculate_intensity_matching(conversation_id)
        empathy_rate = self.calculate_empathy_recognition(conversation_id)
        resolution_rate = self.calculate_negative_resolution(conversation_id)
        
        # 加权总分
        overall_score = (
            bidirectional_rate * 0.20 +
            polarity_score * 0.15 +
            intensity_score * 0.10 +
            empathy_rate * 0.30 +
            resolution_rate * 0.25
        )
        
        # 确保在0-100范围内
        overall_score = max(0.0, min(100.0, overall_score))
        overall_score = round(overall_score, 2)
        
        # 生成解释
        interpretation = self.generate_interpretation(overall_score)
        
        return {
            "overall_score": overall_score,
            "sub_scores": {
                "bidirectional_positive_response": bidirectional_rate,
                "polarity_consistency": polarity_score,
                "intensity_matching": intensity_score,
                "empathy_recognition": empathy_rate,
                "negative_resolution": resolution_rate
            },
            "interpretation": interpretation
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
            return "情感共振强烈,双方情绪高度同步"
        elif score >= 60:
            return "情感共振良好,双方理解较深"
        elif score >= 40:
            return "情感共振一般,存在改善空间"
        elif score >= 20:
            return "情感共振较弱,需要加强沟通"
        else:
            return "情感共振很弱,缺乏情感连接"
    
    # ===== 辅助方法 =====
    
    def _get_interaction_pairs(
        self,
        conversation_id: int
    ) -> List[Dict[str, Any]]:
        """
        获取交互对数据
        
        Args:
            conversation_id: 会话ID
        
        Returns:
            交互对列表
        """
        cursor = get_db().execute("""
            SELECT 
                from_polarity, 
                to_polarity,
                from_intensity, 
                to_intensity,
                semantic_similarity,
                to_speech_unit_id,
                from_speech_unit_id
            FROM interaction_pairs
            WHERE conversation_id = ?
        """, (conversation_id,))
        
        # 先把所有行取出来，避免后续嵌套查询导致游标冲突
        rows = cursor.fetchall()
        
        # 收集所有需要查询的 speech_unit_id
        all_unit_ids = set()
        for row in rows:
            if row[5]:  # to_speech_unit_id
                all_unit_ids.add(row[5])
            if row[6]:  # from_speech_unit_id
                all_unit_ids.add(row[6])
        
        # 批量加载所有 speech_unit 的内容
        unit_content_map = self._batch_get_speech_unit_contents(all_unit_ids)
        
        pairs = []
        for row in rows:
            pairs.append({
                'from_polarity': row[0],
                'to_polarity': row[1],
                'from_intensity': row[2],
                'to_intensity': row[3],
                'semantic_similarity': row[4],
                'to_content': unit_content_map.get(row[5], ""),
                'from_content': unit_content_map.get(row[6], ""),
            })
        
        return pairs
    
    def _batch_get_speech_unit_contents(self, unit_ids: set) -> dict:
        """
        批量获取多个发言单元的内容
        
        避免在循环中逐条查询导致SQLite游标冲突
        
        Args:
            unit_ids: 发言单元ID集合
        
        Returns:
            {unit_id: content_text} 映射字典
        """
        import json
        
        if not unit_ids:
            return {}
        
        result_map = {}
        unit_id_list = list(unit_ids)
        
        # 第一步：批量获取所有 speech_unit 的 message_ids
        placeholders = ','.join('?' * len(unit_id_list))
        cursor = get_db().execute(f"""
            SELECT id, message_ids FROM speech_units WHERE id IN ({placeholders})
        """, unit_id_list)
        
        unit_msg_map = {}  # {unit_id: [msg_id1, msg_id2, ...]}
        all_msg_ids = set()
        
        for row in cursor.fetchall():
            try:
                msg_ids = json.loads(row[1])
                if msg_ids:
                    unit_msg_map[row[0]] = msg_ids
                    all_msg_ids.update(msg_ids)
            except:
                pass
        
        # 第二步：批量获取所有消息内容
        msg_content_map = {}  # {msg_id: content}
        if all_msg_ids:
            msg_id_list = list(all_msg_ids)
            placeholders = ','.join('?' * len(msg_id_list))
            cursor = get_db().execute(f"""
                SELECT id, content FROM messages WHERE id IN ({placeholders})
            """, msg_id_list)
            
            for row in cursor.fetchall():
                content = row[1]
                if isinstance(content, bytes):
                    try:
                        content = content.decode('utf-8', errors='replace')
                    except:
                        content = ""
                msg_content_map[row[0]] = content or ""
        
        # 第三步：组装结果
        for unit_id in unit_id_list:
            msg_ids = unit_msg_map.get(unit_id, [])
            contents = [msg_content_map.get(mid, "") for mid in msg_ids]
            result_map[unit_id] = " ".join(contents)
        
        return result_map
    
    def _get_speech_unit_content(self, speech_unit_id: int) -> str:
        """
        获取发言单元的内容
        
        Args:
            speech_unit_id: 发言单元ID
        
        Returns:
            内容文本
        """
        # 先获取发言单元的 message_ids
        cursor = get_db().execute("""
            SELECT message_ids FROM speech_units WHERE id = ?
        """, (speech_unit_id,))
        
        row = cursor.fetchone()
        if not row:
            return ""
        
        # 解析 message_ids (JSON 格式)
        import json
        try:
            message_ids = json.loads(row[0])
        except:
            return ""
        
        if not message_ids:
            return ""
        
        # 从 messages 表查询内容
        placeholders = ','.join('?' * len(message_ids))
        cursor = get_db().execute(f"""
            SELECT content FROM messages WHERE id IN ({placeholders})
        """, message_ids)
        
        contents = []
        for row in cursor.fetchall():
            content = row[0]
            # 处理 bytes 类型
            if isinstance(content, bytes):
                try:
                    content = content.decode('utf-8', errors='replace')
                except:
                    content = ""
            contents.append(content or "")
        
        return " ".join(contents)
    
    def _count_messages_with_keywords(
        self,
        conversation_id: int,
        keywords: List[str]
    ) -> int:
        """
        统计包含关键词的消息数
        
        Args:
            conversation_id: 会话ID
            keywords: 关键词列表
        
        Returns:
            消息数量
        """
        cursor = get_db().execute("""
            SELECT content FROM messages 
            WHERE conversation_id = ? AND message_type = 1
        """, (conversation_id,))
        
        count = 0
        for row in cursor.fetchall():
            content = row[0] or ""
            if self.keyword_lib.check_keywords_in_text(content, keywords):
                count += 1
        
        return count
    
    def _contains_keywords(self, text: str, keywords: List[str]) -> bool:
        """
        检查文本是否包含关键词
        
        Args:
            text: 文本
            keywords: 关键词列表
        
        Returns:
            是否包含
        """
        if not text or not keywords:
            return False
        
        return self.keyword_lib.check_keywords_in_text(text, keywords)
