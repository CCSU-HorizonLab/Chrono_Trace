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


class EmotionalResonanceService:
    """情感共振率服务"""

    POSITIVE_RESPONSE_TIME_WINDOW = 1800
    SOFT_POSITIVE_INTENSITY_THRESHOLD = 0.12
    BIDIRECTIONAL_POSITIVE_PRIOR = 0.60
    BIDIRECTIONAL_CONFIDENCE_PAIR_COUNT = 6
    SEMANTIC_SIMILARITY_THRESHOLD = 0.45
    FAST_RESPONSE_THRESHOLD = 300
    SOFT_POSITIVE_KEYWORDS = (
        "哈哈", "哈哈哈", "嘿嘿", "嗯", "嗯嗯", "好呀", "好啊", "好哦", "好呢",
        "可以", "行呀", "行啊", "收到", "收到啦", "好的", "好的呀", "没问题",
        "真好", "太好了", "好耶", "ok", "okay"
    )
    ENGAGED_REPLY_KEYWORDS = (
        "哈哈", "哈哈哈", "嘿嘿", "嗯", "嗯嗯", "对呀", "对啊", "是呀", "是啊",
        "好呀", "好啊", "好哦", "好呢", "可以", "行呀", "行啊", "收到", "好的",
        "没问题", "真好", "太好了", "好耶", "真的呀", "真的耶", "那当然", "必须的",
        "ok", "okay"
    )

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

        公式: 对正向发起后的回复做连续型评分，再结合样本量做轻量平滑。
        """
        pairs = self._get_interaction_pairs(conversation_id)

        positive_initiated_pairs = [
            pair for pair in pairs
            if pair['from_polarity'] == 1 and self._is_within_positive_response_window(pair)
        ]

        if not positive_initiated_pairs:
            return 0.0

        strong_positive_count = 0
        soft_positive_count = 0
        engaged_neutral_count = 0
        weighted_positive_response = 0.0

        for pair in positive_initiated_pairs:
            pair_score = self._score_positive_response_pair(pair)
            weighted_positive_response += pair_score

            if pair['to_polarity'] == 1:
                strong_positive_count += 1
            elif pair_score >= 0.45:
                soft_positive_count += 1
            elif pair_score > 0:
                engaged_neutral_count += 1

        raw_rate = weighted_positive_response / len(positive_initiated_pairs)
        confidence = min(
            1.0,
            len(positive_initiated_pairs) / self.BIDIRECTIONAL_CONFIDENCE_PAIR_COUNT
        )
        smoothed_rate = (
            raw_rate * confidence +
            self.BIDIRECTIONAL_POSITIVE_PRIOR * (1 - confidence)
        )
        rate = (raw_rate if raw_rate >= 0.95 else smoothed_rate) * 100

        debug_log(f"\n[情感共振调试] --- 1. 双向积极情感响应率 (权重20%) ---")
        debug_log(
            f"有效正向发起交互对: {len(positive_initiated_pairs)}, "
            f"强正向回应: {strong_positive_count}, 弱正向回应: {soft_positive_count}, "
            f"友好中性回应: {engaged_neutral_count}, 加权回应值: {weighted_positive_response:.2f}"
        )
        debug_log(f"原始响应率: {raw_rate*100:.1f}%, 平滑后响应率: {rate:.1f}%")

        return round(rate, 2)

    def calculate_polarity_consistency(
        self,
        conversation_id: int
    ) -> float:
        """
        计算情感极性一致性 (15%权重)

        公式: (同极性交互对比例) × (同极性对的平均语义相似度)
        """
        pairs = self._get_interaction_pairs(conversation_id)

        if not pairs:
            return 0.0

        same_polarity_pairs = [
            pair for pair in pairs
            if pair['from_polarity'] == pair['to_polarity']
        ]

        if not same_polarity_pairs:
            return 0.0

        ratio = len(same_polarity_pairs) / len(pairs)
        avg_similarity = sum(
            pair['semantic_similarity'] or 0.0
            for pair in same_polarity_pairs
        ) / len(same_polarity_pairs)

        score = ratio * avg_similarity

        debug_log(f"\n[情感共振调试] --- 2. 情感极性一致性 (权重15%) ---")
        debug_log(f"同极性交互对数: {len(same_polarity_pairs)} / 交互对总数: {len(pairs)} (比例: {ratio*100:.1f}%)")
        debug_log(f"同极性平均语义相似度: {avg_similarity:.3f} -> 一致性得分: {score*100:.2f}")

        return round(score * 100, 2)

    def calculate_intensity_matching(
        self,
        conversation_id: int
    ) -> float:
        """
        计算情绪强度匹配度 (10%权重)

        公式: 1 / (mean_abs_diff + 0.1), 使用tanh归一化到0-1
        """
        pairs = self._get_interaction_pairs(conversation_id)

        if not pairs:
            return 0.0

        intensity_diffs = [
            abs(pair['from_intensity'] - pair['to_intensity'])
            for pair in pairs
        ]

        mean_abs_diff = sum(intensity_diffs) / len(intensity_diffs)
        raw_score = 1 / (mean_abs_diff + 0.1)
        normalized_score = math.tanh(raw_score)

        debug_log(f"\n[情感共振调试] --- 3. 情绪强度匹配度 (权重10%) ---")
        debug_log(f"平均强度差异(mean_abs_diff): {mean_abs_diff:.3f} -> 归一化得分: {normalized_score*100:.2f}")

        return round(normalized_score * 100, 2)

    def calculate_empathy_recognition(
        self,
        conversation_id: int
    ) -> float:
        """
        计算共情意图识别率 (30%权重)

        公式: (包含共情关键词的消息数 / 总消息数) × 100%
        """
        stats = self.orchestrator.get_preprocessed_statistics(conversation_id)
        total_messages = stats.total_message_count

        if total_messages == 0:
            return 0.0

        empathy_keywords = self.keyword_lib.get_keywords('empathy')
        if not empathy_keywords:
            return 0.0

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
        """
        pairs = self._get_interaction_pairs(conversation_id)

        negative_pairs = [
            pair for pair in pairs
            if pair['from_polarity'] == -1
        ]

        if not negative_pairs:
            return 0.0

        needs_resolution_pairs = []
        for pair in negative_pairs:
            from_content = pair.get('from_content', '')
            if from_content:
                direction_result = self.direction_service.classify(from_content)
                if direction_result.direction != "to_others":
                    needs_resolution_pairs.append(pair)
            else:
                needs_resolution_pairs.append(pair)

        if not needs_resolution_pairs:
            return 100.0

        soothing_keywords = self.keyword_lib.get_keywords('soothing')
        if not soothing_keywords:
            return 0.0

        empathetic_count = 0
        for pair in needs_resolution_pairs:
            if pair['to_polarity'] == 1 and self._contains_keywords(pair['to_content'], soothing_keywords):
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
        """计算情感共振率总分。"""
        debug_log(f"\n{'*'*40}")
        debug_log(f"【情感共振率】开始计分 (会话 ID {conversation_id})")
        debug_log(f"*[注] 该项占总分30%权重，自身包含5个子维度*")

        bidirectional_rate = self.calculate_bidirectional_positive_response(conversation_id)
        polarity_score = self.calculate_polarity_consistency(conversation_id)
        intensity_score = self.calculate_intensity_matching(conversation_id)
        empathy_rate = self.calculate_empathy_recognition(conversation_id)
        resolution_rate = self.calculate_negative_resolution(conversation_id)

        overall_score = (
            bidirectional_rate * 0.20 +
            polarity_score * 0.15 +
            intensity_score * 0.10 +
            empathy_rate * 0.30 +
            resolution_rate * 0.25
        )

        overall_score = max(0.0, min(100.0, overall_score))
        overall_score = round(overall_score, 2)
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
        """生成解释文本。"""
        if score >= 80:
            return "情感共振强烈,双方情绪高度同步"
        if score >= 60:
            return "情感共振良好,双方理解较深"
        if score >= 40:
            return "情感共振一般,存在改善空间"
        if score >= 20:
            return "情感共振较弱,需要加强沟通"
        return "情感共振很弱,缺乏情感连接"

    # ===== 辅助方法 =====

    def _get_interaction_pairs(
        self,
        conversation_id: int
    ) -> List[Dict[str, Any]]:
        """获取交互对数据。"""
        cursor = get_db().execute("""
            SELECT
                from_polarity,
                to_polarity,
                from_intensity,
                to_intensity,
                semantic_similarity,
                time_gap,
                to_speech_unit_id,
                from_speech_unit_id
            FROM interaction_pairs
            WHERE conversation_id = ?
        """, (conversation_id,))

        rows = cursor.fetchall()

        all_unit_ids = set()
        for row in rows:
            if row[6]:
                all_unit_ids.add(row[6])
            if row[7]:
                all_unit_ids.add(row[7])

        unit_content_map = self._batch_get_speech_unit_contents(all_unit_ids)

        pairs = []
        for row in rows:
            pairs.append({
                'from_polarity': row[0],
                'to_polarity': row[1],
                'from_intensity': row[2],
                'to_intensity': row[3],
                'semantic_similarity': row[4],
                'time_gap': row[5],
                'to_content': unit_content_map.get(row[6], ""),
                'from_content': unit_content_map.get(row[7], ""),
            })

        return pairs

    def _is_within_positive_response_window(self, pair: Dict[str, Any]) -> bool:
        """只统计有效时间窗内的正向回应。"""
        time_gap = pair.get('time_gap')
        if time_gap is None:
            return True
        return time_gap <= self.POSITIVE_RESPONSE_TIME_WINDOW

    def _is_soft_positive_response(self, pair: Dict[str, Any]) -> bool:
        """识别中性但带有友好承接意味的回复。"""
        if pair.get('to_polarity') != 0:
            return False

        to_intensity = pair.get('to_intensity') or 0.0
        if to_intensity >= self.SOFT_POSITIVE_INTENSITY_THRESHOLD:
            return True

        to_content = pair.get('to_content') or ""
        if self._contains_keywords(to_content, list(self.SOFT_POSITIVE_KEYWORDS)):
            return True

        positive_keywords = self.keyword_lib.get_keywords('positive')
        if positive_keywords and self._contains_keywords(to_content, positive_keywords):
            return True

        return False

    def _score_positive_response_pair(self, pair: Dict[str, Any]) -> float:
        """为正向发起后的回复计算连续型得分。"""
        to_polarity = pair.get('to_polarity', 0)
        if to_polarity < 0:
            return 0.0

        to_intensity = pair.get('to_intensity') or 0.0
        semantic_similarity = pair.get('semantic_similarity') or 0.0
        to_content = pair.get('to_content') or ""

        fast_reply_bonus = 0.08 if self._is_fast_positive_response(pair) else 0.0
        semantic_bonus = 0.08 if semantic_similarity >= self.SEMANTIC_SIMILARITY_THRESHOLD else 0.0

        if to_polarity == 1:
            intensity_bonus = min(0.10, max(0.0, to_intensity) * 0.12)
            return min(1.0, 0.86 + intensity_bonus + semantic_bonus + fast_reply_bonus)

        score = 0.0
        if self._is_soft_positive_response(pair):
            score += 0.38
        if semantic_similarity >= self.SEMANTIC_SIMILARITY_THRESHOLD:
            score += 0.14
        if to_intensity >= self.SOFT_POSITIVE_INTENSITY_THRESHOLD:
            score += 0.12
        if self._contains_keywords(to_content, list(self.ENGAGED_REPLY_KEYWORDS)):
            score += 0.14
        if fast_reply_bonus:
            score += fast_reply_bonus

        if score == 0.0 and self._is_fast_positive_response(pair):
            score = 0.12

        return min(0.78, score)

    def _is_fast_positive_response(self, pair: Dict[str, Any]) -> bool:
        """快速回应通常意味着对方接住了情绪。"""
        time_gap = pair.get('time_gap')
        if time_gap is None:
            return False
        return time_gap <= self.FAST_RESPONSE_THRESHOLD

    def _batch_get_speech_unit_contents(self, unit_ids: set) -> dict:
        """批量获取多个发言单元的内容。"""
        import json

        if not unit_ids:
            return {}

        result_map = {}
        unit_id_list = list(unit_ids)

        placeholders = ','.join('?' * len(unit_id_list))
        cursor = get_db().execute(f"""
            SELECT id, message_ids FROM speech_units WHERE id IN ({placeholders})
        """, unit_id_list)

        unit_msg_map = {}
        all_msg_ids = set()

        for row in cursor.fetchall():
            try:
                msg_ids = json.loads(row[1])
                if msg_ids:
                    unit_msg_map[row[0]] = msg_ids
                    all_msg_ids.update(msg_ids)
            except Exception:
                pass

        msg_content_map = {}
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
                    except Exception:
                        content = ""
                msg_content_map[row[0]] = content or ""

        for unit_id in unit_id_list:
            msg_ids = unit_msg_map.get(unit_id, [])
            contents = [msg_content_map.get(mid, "") for mid in msg_ids]
            result_map[unit_id] = " ".join(contents)

        return result_map

    def _get_speech_unit_content(self, speech_unit_id: int) -> str:
        """获取发言单元的内容。"""
        cursor = get_db().execute("""
            SELECT message_ids FROM speech_units WHERE id = ?
        """, (speech_unit_id,))

        row = cursor.fetchone()
        if not row:
            return ""

        import json
        try:
            message_ids = json.loads(row[0])
        except Exception:
            return ""

        if not message_ids:
            return ""

        placeholders = ','.join('?' * len(message_ids))
        cursor = get_db().execute(f"""
            SELECT content FROM messages WHERE id IN ({placeholders})
        """, message_ids)

        contents = []
        for row in cursor.fetchall():
            content = row[0]
            if isinstance(content, bytes):
                try:
                    content = content.decode('utf-8', errors='replace')
                except Exception:
                    content = ""
            contents.append(content or "")

        return " ".join(contents)

    def _count_messages_with_keywords(
        self,
        conversation_id: int,
        keywords: List[str]
    ) -> int:
        """统计包含关键词的消息数。"""
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
        """检查文本是否包含关键词。"""
        if not text or not keywords:
            return False

        return self.keyword_lib.check_keywords_in_text(text, keywords)
