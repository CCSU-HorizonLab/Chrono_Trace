"""Emotional resonance scoring service."""

import json
import math
from typing import Any, Dict, List, Sequence

from ...db.connection import get_db
from .keyword_libraries import KeywordLibraries
from .negative_direction_service import NegativeDirectionService
from .preprocessing_orchestrator import PreprocessingOrchestrator

# Enable detailed tracing for affinity analysis logs.
DEBUG_TRACE = True


def debug_log(msg: str):
    """Write analysis debug messages when tracing is enabled."""
    if DEBUG_TRACE:
        from .affinity_debug_logger import affinity_debug_log

        affinity_debug_log(msg)


class EmotionalResonanceService:
    """Calculate the emotional resonance dimension and its sub-scores."""

    POSITIVE_RESPONSE_TIME_WINDOW = 3600
    SOFT_POSITIVE_INTENSITY_THRESHOLD = 0.12
    BIDIRECTIONAL_POSITIVE_PRIOR = 0.68
    BIDIRECTIONAL_CONFIDENCE_PAIR_COUNT = 4
    SEMANTIC_SIMILARITY_THRESHOLD = 0.45
    FAST_RESPONSE_THRESHOLD = 300
    SUPPORTIVE_RESPONSE_THRESHOLD = 600
    EMPATHY_MID_RESPONSE_THRESHOLD = 1800
    EMPATHY_SLOW_RESPONSE_THRESHOLD = 7200
    DETAILED_RESPONSE_LENGTH_THRESHOLD = 12

    SOFT_POSITIVE_KEYWORDS = (
        "哈哈",
        "嘿嘿",
        "嗯",
        "嗯嗯",
        "好呀",
        "好啊",
        "好哦",
        "好呢",
        "可以",
        "行呀",
        "行啊",
        "收到",
        "好的",
        "没问题",
        "真好",
        "太好了",
        "好耶",
        "ok",
        "okay",
    )
    ENGAGED_REPLY_KEYWORDS = (
        "哈哈",
        "嘿嘿",
        "嗯",
        "嗯嗯",
        "对呀",
        "对啊",
        "是呀",
        "是啊",
        "好呀",
        "好啊",
        "好哦",
        "好呢",
        "可以",
        "行呀",
        "行啊",
        "收到",
        "好的",
        "没问题",
        "真好",
        "太好了",
        "好耶",
        "真的呀",
        "那当然",
        "必须的",
        "ok",
        "okay",
    )
    EXTRA_EMPATHY_KEYWORDS = (
        "你还好吗",
        "没事吧",
        "怎么了",
        "辛苦了",
        "累了吧",
        "抱抱",
        "理解你",
        "支持你",
        "我在",
        "说来听听",
        "没关系",
        "别担心",
        "会好起来的",
        "陪着你",
        "感同身受",
    )
    EXTRA_SOOTHING_KEYWORDS = (
        "加油",
        "没事的",
        "慢慢来",
        "不急",
        "会好的",
        "放心",
        "别想太多",
        "开心点",
        "不要难过",
        "你已经很棒了",
        "我懂你",
        "一切都会好",
    )
    EMPATHY_QUESTION_KEYWORDS = (
        "怎么了",
        "还好吗",
        "没事吧",
        "怎么样了",
        "你还好吗",
        "发生什么",
        "什么情况",
        "要我",
        "需要我",
        "有什么我",
    )

    def __init__(self):
        self.orchestrator = PreprocessingOrchestrator()
        self.keyword_lib = KeywordLibraries()
        self.direction_service = NegativeDirectionService()

    def calculate_bidirectional_positive_response(self, conversation_id: int) -> float:
        """Score how well positive emotion is reciprocated."""
        pairs = self._get_interaction_pairs(conversation_id)
        positive_initiated_pairs = [
            pair
            for pair in pairs
            if pair["from_polarity"] == 1 and self._is_within_positive_response_window(pair)
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

            if pair["to_polarity"] == 1:
                strong_positive_count += 1
            elif pair_score >= 0.45:
                soft_positive_count += 1
            elif pair_score > 0:
                engaged_neutral_count += 1

        raw_rate = weighted_positive_response / len(positive_initiated_pairs)
        confidence = min(
            1.0, len(positive_initiated_pairs) / self.BIDIRECTIONAL_CONFIDENCE_PAIR_COUNT
        )
        smoothed_rate = raw_rate * confidence + self.BIDIRECTIONAL_POSITIVE_PRIOR * (
            1 - confidence
        )
        rate = (raw_rate if raw_rate >= 0.95 else smoothed_rate) * 100

        debug_log("\n[情感共振调试] --- 1. 双向积极情感响应率(权重20%) ---")
        debug_log(
            f"有效正向发起互动对: {len(positive_initiated_pairs)}, "
            f"强正向回复: {strong_positive_count}, 软正向回复: {soft_positive_count}, "
            f"友好中性回复: {engaged_neutral_count}, 加权响应值: {weighted_positive_response:.2f}"
        )
        debug_log(f"原始响应率: {raw_rate*100:.1f}%, 平滑后响应率: {rate:.1f}%")

        return round(rate, 2)

    def calculate_polarity_consistency(self, conversation_id: int) -> float:
        """Score polarity consistency with weighted fusion instead of multiplication."""
        pairs = self._get_interaction_pairs(conversation_id)
        if not pairs:
            return 0.0

        same_polarity_pairs = [
            pair for pair in pairs if pair["from_polarity"] == pair["to_polarity"]
        ]
        if not same_polarity_pairs:
            return 0.0

        ratio = len(same_polarity_pairs) / len(pairs)
        avg_similarity = sum(
            pair.get("semantic_similarity") or 0.0 for pair in same_polarity_pairs
        ) / len(same_polarity_pairs)
        score = ratio * 0.7 + avg_similarity * 0.3

        debug_log("\n[情感共振调试] --- 2. 情感极性一致性(权重15%) ---")
        debug_log(
            f"同极性交互对数: {len(same_polarity_pairs)} / {len(pairs)} "
            f"(比例: {ratio*100:.1f}%)"
        )
        debug_log(f"同极性平均语义相似度: {avg_similarity:.3f} -> 一致性得分: {score*100:.2f}")

        return round(score * 100, 2)

    def calculate_intensity_matching(self, conversation_id: int) -> float:
        """Score emotional intensity matching."""
        pairs = self._get_interaction_pairs(conversation_id)
        if not pairs:
            return 0.0

        intensity_diffs = [
            abs(pair["from_intensity"] - pair["to_intensity"]) for pair in pairs
        ]
        mean_abs_diff = sum(intensity_diffs) / len(intensity_diffs)
        raw_score = 1 / (mean_abs_diff + 0.1)
        normalized_score = math.tanh(raw_score)

        debug_log("\n[情感共振调试] --- 3. 情绪强度匹配度(权重10%) ---")
        debug_log(
            f"平均强度差异(mean_abs_diff): {mean_abs_diff:.3f} -> 归一化得分: {normalized_score*100:.2f}"
        )

        return round(normalized_score * 100, 2)

    def calculate_empathy_recognition(self, conversation_id: int) -> float:
        """Score empathy recognition only across actual empathy opportunities."""
        pairs = self._get_interaction_pairs(conversation_id)
        empathy_pairs = self._get_empathy_opportunity_pairs(pairs)
        if not empathy_pairs:
            return 50.0

        empathy_keywords = self._get_empathy_keywords()
        soothing_keywords = self._get_soothing_keywords()

        explicit_hits = 0
        supportive_score_sum = 0.0
        timeliness_score_sum = 0.0

        for pair in empathy_pairs:
            if self._has_explicit_empathy(pair, empathy_keywords, soothing_keywords):
                explicit_hits += 1
            supportive_score_sum += self._score_supportive_response_pair(
                pair, empathy_keywords, soothing_keywords
            )
            timeliness_score_sum += self._score_empathy_timeliness(pair)

        opportunity_count = len(empathy_pairs)
        explicit_rate = explicit_hits / opportunity_count
        supportive_rate = supportive_score_sum / opportunity_count
        timeliness_rate = timeliness_score_sum / opportunity_count
        main_score = explicit_rate * 0.6 + supportive_rate * 0.4
        rate = ((main_score * 0.85) + (timeliness_rate * 0.15)) * 100
        empathy_count = explicit_hits
        total_messages = opportunity_count
        keyword_rate = explicit_rate
        fast_response_count = sum(
            1
            for pair in empathy_pairs
            if self._score_empathy_timeliness(pair) >= 0.7
        )
        negative_pairs = empathy_pairs
        fast_response_rate = timeliness_rate
        question_count = 0

        debug_log("\n[情感共振调试] --- 4. 共情意图识别率(权重30%) ---")
        debug_log(
            f"共情关键词消息数: {empathy_count} / 总消息数: {total_messages}, "
            f"关键词率: {keyword_rate*100:.1f}%"
        )
        debug_log(
            f"负面消息后快速响应数: {fast_response_count} / {len(negative_pairs)} "
            f"(响应率: {fast_response_rate*100:.1f}%), 关心提问数: {question_count}"
        )
        debug_log(f"多信号融合后识别率: {rate:.1f}%")

        return round(rate, 2)

    def calculate_negative_resolution(self, conversation_id: int) -> float:
        """Score how well negative emotion receives de-escalating responses."""
        pairs = self._get_interaction_pairs(conversation_id)
        negative_pairs = [pair for pair in pairs if pair["from_polarity"] == -1]
        if not negative_pairs:
            return 0.0

        needs_resolution_pairs = []
        for pair in negative_pairs:
            from_content = pair.get("from_content", "")
            if from_content:
                direction_result = self.direction_service.classify(from_content)
                if direction_result.direction != "to_others":
                    needs_resolution_pairs.append(pair)
            else:
                needs_resolution_pairs.append(pair)

        if not needs_resolution_pairs:
            return 100.0

        soothing_keywords = self._get_soothing_keywords()
        resolution_scores = [
            self._score_resolution_pair(pair, soothing_keywords)
            for pair in needs_resolution_pairs
        ]
        rate = (sum(resolution_scores) / len(needs_resolution_pairs)) * 100

        debug_log("\n[情感共振调试] --- 5. 负面情绪协同化解率(权重25%) ---")
        debug_log(f"需要化解的负面互动对数(排除'对他人'): {len(needs_resolution_pairs)}")
        debug_log(
            f"化解加权总分: {sum(resolution_scores):.2f} / {len(needs_resolution_pairs)} "
            f"-> 化解率: {rate:.1f}%"
        )

        return round(rate, 2)

    def calculate_overall_resonance(self, conversation_id: int) -> Dict[str, Any]:
        """Calculate overall emotional resonance score."""
        debug_log(f"\n{'*' * 40}")
        debug_log(f"【情感共振率】开始计算(会话 ID {conversation_id})")
        debug_log("*[注] 该项占总分30%权重，自身包含 5 个子维度*")

        bidirectional_rate = self.calculate_bidirectional_positive_response(conversation_id)
        polarity_score = self.calculate_polarity_consistency(conversation_id)
        intensity_score = self.calculate_intensity_matching(conversation_id)
        empathy_rate = self.calculate_empathy_recognition(conversation_id)
        resolution_rate = self.calculate_negative_resolution(conversation_id)

        overall_score = (
            bidirectional_rate * 0.20
            + polarity_score * 0.15
            + intensity_score * 0.10
            + empathy_rate * 0.30
            + resolution_rate * 0.25
        )
        overall_score = round(max(0.0, min(100.0, overall_score)), 2)

        return {
            "overall_score": overall_score,
            "sub_scores": {
                "bidirectional_positive_response": bidirectional_rate,
                "polarity_consistency": polarity_score,
                "intensity_matching": intensity_score,
                "empathy_recognition": empathy_rate,
                "negative_resolution": resolution_rate,
            },
            "interpretation": self.generate_interpretation(overall_score),
        }

    def generate_interpretation(self, score: float) -> str:
        """Generate a short textual interpretation."""
        if score >= 80:
            return "情感共振强烈，双方情绪高度同步"
        if score >= 60:
            return "情感共振良好，双方理解较深"
        if score >= 40:
            return "情感共振一般，存在改善空间"
        if score >= 20:
            return "情感共振较弱，需要加强沟通"
        return "情感共振很弱，缺乏情感连接"

    def _get_interaction_pairs(self, conversation_id: int) -> List[Dict[str, Any]]:
        """Load interaction pair records for a conversation."""
        cursor = get_db().execute(
            """
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
            """,
            (conversation_id,),
        )
        rows = cursor.fetchall()

        all_unit_ids = set()
        for row in rows:
            if row[6]:
                all_unit_ids.add(row[6])
            if row[7]:
                all_unit_ids.add(row[7])

        unit_content_map = self._batch_get_speech_unit_contents(all_unit_ids)
        return [
            {
                "from_polarity": row[0],
                "to_polarity": row[1],
                "from_intensity": row[2],
                "to_intensity": row[3],
                "semantic_similarity": row[4],
                "time_gap": row[5],
                "to_content": unit_content_map.get(row[6], ""),
                "from_content": unit_content_map.get(row[7], ""),
            }
            for row in rows
        ]

    def _is_within_positive_response_window(self, pair: Dict[str, Any]) -> bool:
        time_gap = pair.get("time_gap")
        return time_gap is None or time_gap <= self.POSITIVE_RESPONSE_TIME_WINDOW

    def _is_soft_positive_response(self, pair: Dict[str, Any]) -> bool:
        if pair.get("to_polarity") != 0:
            return False

        to_intensity = pair.get("to_intensity") or 0.0
        if to_intensity >= self.SOFT_POSITIVE_INTENSITY_THRESHOLD:
            return True

        to_content = pair.get("to_content") or ""
        if self._contains_keywords(to_content, list(self.SOFT_POSITIVE_KEYWORDS)):
            return True

        positive_keywords = self.keyword_lib.get_keywords("positive")
        return bool(
            positive_keywords and self._contains_keywords(to_content, positive_keywords)
        )

    def _score_positive_response_pair(self, pair: Dict[str, Any]) -> float:
        to_polarity = pair.get("to_polarity", 0)
        if to_polarity < 0:
            return 0.0

        to_intensity = pair.get("to_intensity") or 0.0
        semantic_similarity = pair.get("semantic_similarity") or 0.0
        to_content = pair.get("to_content") or ""

        fast_reply_bonus = 0.08 if self._is_fast_positive_response(pair) else 0.0
        semantic_bonus = (
            0.08 if semantic_similarity >= self.SEMANTIC_SIMILARITY_THRESHOLD else 0.0
        )

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

        return min(0.85, score)

    def _is_fast_positive_response(self, pair: Dict[str, Any]) -> bool:
        time_gap = pair.get("time_gap")
        return time_gap is not None and time_gap <= self.FAST_RESPONSE_THRESHOLD

    def _is_supportive_fast_response(self, pair: Dict[str, Any]) -> bool:
        time_gap = pair.get("time_gap")
        return time_gap is not None and time_gap <= self.SUPPORTIVE_RESPONSE_THRESHOLD

    def _score_resolution_pair(
        self, pair: Dict[str, Any], soothing_keywords: Sequence[str]
    ) -> float:
        to_polarity = pair.get("to_polarity", 0)
        to_content = pair.get("to_content", "") or ""
        has_soothing = self._contains_keywords(to_content, list(soothing_keywords))
        is_fast = self._is_supportive_fast_response(pair)

        if to_polarity == 1 and has_soothing:
            return 1.0
        if to_polarity == 1 or has_soothing:
            return 0.6
        if to_polarity == 0 and is_fast:
            return 0.3
        return 0.0

    def _get_empathy_opportunity_pairs(
        self, pairs: Sequence[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        opportunity_pairs = []
        for pair in pairs:
            if pair.get("from_polarity") != -1:
                continue

            from_content = pair.get("from_content", "")
            if from_content:
                direction_result = self.direction_service.classify(from_content)
                if direction_result.direction == "to_others":
                    continue

            opportunity_pairs.append(pair)
        return opportunity_pairs

    def _has_explicit_empathy(
        self,
        pair: Dict[str, Any],
        empathy_keywords: Sequence[str],
        soothing_keywords: Sequence[str],
    ) -> bool:
        to_content = pair.get("to_content", "") or ""
        return self._contains_keywords(
            to_content,
            self._merge_keywords(
                empathy_keywords,
                soothing_keywords,
                self.EXTRA_EMPATHY_KEYWORDS,
            ),
        )

    def _score_supportive_response_pair(
        self,
        pair: Dict[str, Any],
        empathy_keywords: Sequence[str],
        soothing_keywords: Sequence[str],
    ) -> float:
        to_polarity = pair.get("to_polarity", 0)
        to_content = pair.get("to_content", "") or ""
        semantic_similarity = pair.get("semantic_similarity") or 0.0
        has_explicit_empathy = self._has_explicit_empathy(
            pair, empathy_keywords, soothing_keywords
        )
        has_question = self._contains_keywords(
            to_content, list(self.EMPATHY_QUESTION_KEYWORDS)
        )
        is_detailed_reply = len(to_content.strip()) >= self.DETAILED_RESPONSE_LENGTH_THRESHOLD
        is_engaged = (
            semantic_similarity >= self.SEMANTIC_SIMILARITY_THRESHOLD
            or has_question
            or is_detailed_reply
        )

        if to_polarity == 1 and has_explicit_empathy:
            return 1.0
        if to_polarity == 1 and is_engaged:
            return 0.7
        if to_polarity == 0 and has_explicit_empathy:
            return 0.6
        if to_polarity == 0 and is_engaged:
            return 0.4
        return 0.0

    def _score_empathy_timeliness(self, pair: Dict[str, Any]) -> float:
        time_gap = pair.get("time_gap")
        if time_gap is None:
            return 0.1
        if time_gap <= self.FAST_RESPONSE_THRESHOLD:
            return 1.0
        if time_gap <= self.EMPATHY_MID_RESPONSE_THRESHOLD:
            return 0.7
        if time_gap <= self.EMPATHY_SLOW_RESPONSE_THRESHOLD:
            return 0.4
        return 0.1

    def _batch_get_speech_unit_contents(self, unit_ids: set) -> Dict[int, str]:
        if not unit_ids:
            return {}

        result_map: Dict[int, str] = {}
        unit_id_list = list(unit_ids)
        placeholders = ",".join("?" * len(unit_id_list))
        cursor = get_db().execute(
            f"SELECT id, message_ids FROM speech_units WHERE id IN ({placeholders})",
            unit_id_list,
        )

        unit_msg_map: Dict[int, List[int]] = {}
        all_msg_ids = set()
        for row in cursor.fetchall():
            try:
                msg_ids = json.loads(row[1])
            except Exception:
                msg_ids = []
            if msg_ids:
                unit_msg_map[row[0]] = msg_ids
                all_msg_ids.update(msg_ids)

        msg_content_map: Dict[int, str] = {}
        if all_msg_ids:
            msg_id_list = list(all_msg_ids)
            placeholders = ",".join("?" * len(msg_id_list))
            cursor = get_db().execute(
                f"SELECT id, content FROM messages WHERE id IN ({placeholders})",
                msg_id_list,
            )
            for row in cursor.fetchall():
                content = row[1]
                if isinstance(content, bytes):
                    try:
                        content = content.decode("utf-8", errors="replace")
                    except Exception:
                        content = ""
                msg_content_map[row[0]] = content or ""

        for unit_id in unit_id_list:
            msg_ids = unit_msg_map.get(unit_id, [])
            result_map[unit_id] = " ".join(msg_content_map.get(mid, "") for mid in msg_ids)

        return result_map

    def _count_messages_with_keywords(self, conversation_id: int, keywords: List[str]) -> int:
        cursor = get_db().execute(
            """
            SELECT content FROM messages
            WHERE conversation_id = ? AND message_type = 1
            """,
            (conversation_id,),
        )

        count = 0
        for row in cursor.fetchall():
            content = row[0] or ""
            if self.keyword_lib.check_keywords_in_text(content, keywords):
                count += 1
        return count

    def _contains_keywords(self, text: str, keywords: List[str]) -> bool:
        if not text or not keywords:
            return False
        return self.keyword_lib.check_keywords_in_text(text, keywords)

    def _get_empathy_keywords(self) -> List[str]:
        return self._merge_keywords(
            self.keyword_lib.get_keywords("empathy"), list(self.EXTRA_EMPATHY_KEYWORDS)
        )

    def _get_soothing_keywords(self) -> List[str]:
        return self._merge_keywords(
            self.keyword_lib.get_keywords("soothing"), list(self.EXTRA_SOOTHING_KEYWORDS)
        )

    @staticmethod
    def _merge_keywords(*keyword_groups: Sequence[str]) -> List[str]:
        merged: List[str] = []
        seen = set()
        for group in keyword_groups:
            for keyword in group:
                if keyword and keyword not in seen:
                    seen.add(keyword)
                    merged.append(keyword)
        return merged
