"""Emotional resonance scoring service."""

import json
import math
from datetime import datetime
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

    CORE_BIDIRECTIONAL_WEIGHT = 0.50
    CORE_POLARITY_WEIGHT = 0.30
    CORE_INTENSITY_WEIGHT = 0.20
    EMPATHY_BONUS_RATIO = 0.10
    NEGATIVE_RESOLUTION_BONUS_RATIO = 0.10
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
    AMBIGUOUS_OPPORTUNITY_WEIGHT = 0.35
    TO_OTHERS_OPPORTUNITY_WEIGHT = 0.0
    MIN_OPPORTUNITY_WEIGHT = 0.15
    NEGATIVE_EPISODE_DECAY = 0.55
    NEGATIVE_EPISODE_MIN_FACTOR = 0.35
    NEGATIVE_EPISODE_UNIT_GAP = 3
    NEUTRAL_RESONANCE_BASELINE = 50.0
    BIDIRECTIONAL_CONFIDENCE_TARGET = 8
    PAIR_CONFIDENCE_TARGET = 10
    RELATIONSHIP_DEPTH_LOW_CONFIDENCE_THRESHOLD = 0.55
    DEPTH_PAIR_COUNT_TARGET = 12
    DEPTH_POSITIVE_PAIR_TARGET = 8
    DEPTH_ACTIVE_DAY_TARGET = 7
    DEPTH_SPAN_DAY_TARGET = 14

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
    SUPPORTIVE_ACKNOWLEDGEMENT_KEYWORDS = (
        "辛苦了",
        "太难了",
        "太惨了",
        "好惨",
        "确实",
        "确实很烦",
        "确实挺烦",
        "真的不容易",
        "能理解",
        "可以理解",
        "理解你",
        "我懂",
        "我懂你",
        "我在",
        "我在呢",
        "抱抱",
        "摸摸",
        "心疼你",
        "太委屈了",
        "太烦了",
    )
    SUPPORTIVE_NEUTRAL_KEYWORDS = (
        "先缓缓",
        "先休息",
        "先别想了",
        "慢慢来",
        "别着急",
        "别担心",
        "会好的",
        "没关系",
        "没事的",
        "会过去的",
        "喝点水",
        "早点休息",
        "休息一下",
        "缓一缓",
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
        prior_confidence = min(
            1.0, len(positive_initiated_pairs) / self.BIDIRECTIONAL_CONFIDENCE_PAIR_COUNT
        )
        smoothed_rate = raw_rate * prior_confidence + self.BIDIRECTIONAL_POSITIVE_PRIOR * (
            1 - prior_confidence
        )
        base_rate = (raw_rate if raw_rate >= 0.95 else smoothed_rate) * 100
        confidence = self._calculate_sample_confidence(
            len(positive_initiated_pairs), self.BIDIRECTIONAL_CONFIDENCE_TARGET
        )
        rate = self._apply_confidence_shrinkage(
            base_rate,
            confidence,
            self.NEUTRAL_RESONANCE_BASELINE,
        )

        debug_log("\n[情感共振调试] --- 1. 双向积极情感响应率(权重20%) ---")
        debug_log(
            f"有效正向发起互动对: {len(positive_initiated_pairs)}, "
            f"强正向回复: {strong_positive_count}, 软正向回复: {soft_positive_count}, "
            f"友好中性回复: {engaged_neutral_count}, 加权响应值: {weighted_positive_response:.2f}"
        )
        debug_log(
            f"原始响应率: {raw_rate*100:.1f}%, 先验平滑后: {base_rate:.1f}%, "
            f"样本置信度: {confidence:.2f}, 收缩后: {rate:.1f}%"
        )

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
        raw_score = (ratio * 0.7 + avg_similarity * 0.3) * 100
        confidence = self._calculate_sample_confidence(
            len(pairs), self.PAIR_CONFIDENCE_TARGET
        )
        score = self._apply_confidence_shrinkage(
            raw_score,
            confidence,
            self.NEUTRAL_RESONANCE_BASELINE,
        )

        debug_log("\n[情感共振调试] --- 2. 情感极性一致性(权重15%) ---")
        debug_log(
            f"同极性交互对数: {len(same_polarity_pairs)} / {len(pairs)} "
            f"(比例: {ratio*100:.1f}%)"
        )
        debug_log(
            f"同极性平均语义相似度: {avg_similarity:.3f} -> 原始一致性: {raw_score:.2f}, "
            f"样本置信度: {confidence:.2f}, 收缩后: {score:.2f}"
        )

        return round(score, 2)

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
        raw_percent = normalized_score * 100
        confidence = self._calculate_sample_confidence(
            len(pairs), self.PAIR_CONFIDENCE_TARGET
        )
        adjusted_score = self._apply_confidence_shrinkage(
            raw_percent,
            confidence,
            self.NEUTRAL_RESONANCE_BASELINE,
        )

        debug_log("\n[情感共振调试] --- 3. 情绪强度匹配度(权重10%) ---")
        debug_log(
            f"平均强度差异(mean_abs_diff): {mean_abs_diff:.3f} -> 原始归一化得分: {raw_percent:.2f}, "
            f"样本置信度: {confidence:.2f}, 收缩后: {adjusted_score:.2f}"
        )

        return round(adjusted_score, 2)

    def calculate_empathy_recognition(self, conversation_id: int) -> float:
        """Score empathy recognition only across actual empathy opportunities."""
        pairs = self._get_interaction_pairs(conversation_id)
        empathy_pairs = self._get_empathy_opportunity_pairs(pairs)
        weighted_pairs = self._build_weighted_opportunities(empathy_pairs)
        if not weighted_pairs:
            debug_log("\n[情感共振调试] --- 4. 共情意图识别率(权重30%) ---")
            debug_log("共情机会样本数为 0，bonus 不加分")
            return 0.0

        empathy_keywords = self._get_empathy_keywords()
        soothing_keywords = self._get_soothing_keywords()

        explicit_hits = 0.0
        supportive_score_sum = 0.0
        timeliness_score_sum = 0.0

        for pair, opportunity_weight in weighted_pairs:
            if self._has_explicit_empathy(pair, empathy_keywords, soothing_keywords):
                explicit_hits += opportunity_weight
            supportive_score_sum += opportunity_weight * self._score_supportive_response_pair(
                pair, empathy_keywords, soothing_keywords
            )
            timeliness_score_sum += opportunity_weight * self._score_empathy_timeliness(pair)

        total_opportunity_weight = sum(weight for _, weight in weighted_pairs)
        explicit_rate = explicit_hits / total_opportunity_weight
        supportive_rate = supportive_score_sum / total_opportunity_weight
        timeliness_rate = timeliness_score_sum / total_opportunity_weight
        main_score = explicit_rate * 0.6 + supportive_rate * 0.4
        rate = ((main_score * 0.85) + (timeliness_rate * 0.15)) * 100

        debug_log("\n[情感共振调试] --- 4. 共情意图识别率(权重30%) ---")
        debug_log(
            f"共情机会样本权重: {total_opportunity_weight:.2f}, 多信号融合后识别率: {rate:.1f}%"
        )

        return round(rate, 2)

    def calculate_negative_resolution(self, conversation_id: int) -> float:
        """Score how well negative emotion receives de-escalating responses."""
        pairs = self._get_interaction_pairs(conversation_id)
        negative_pairs = [pair for pair in pairs if pair["from_polarity"] == -1]
        if not negative_pairs:
            return 0.0

        needs_resolution_pairs = self._get_empathy_opportunity_pairs(negative_pairs)
        weighted_pairs = self._build_weighted_opportunities(needs_resolution_pairs)

        if not weighted_pairs:
            debug_log("\n[情感共振调试] --- 5. 负面情绪协同化解率(权重25%) ---")
            debug_log("需要化解的负面样本数为 0，bonus 不加分")
            return 0.0

        soothing_keywords = self._get_soothing_keywords()
        resolution_scores = [
            weight * self._score_resolution_pair(pair, soothing_keywords)
            for pair, weight in weighted_pairs
        ]
        total_opportunity_weight = sum(weight for _, weight in weighted_pairs)
        rate = (sum(resolution_scores) / total_opportunity_weight) * 100

        debug_log("\n[情感共振调试] --- 5. 负面情绪协同化解率(权重25%) ---")
        debug_log(f"需要化解的负面互动权重(排除'对他人'): {total_opportunity_weight:.2f}")
        debug_log(
            f"化解加权总分: {sum(resolution_scores):.2f} / {total_opportunity_weight:.2f} "
            f"-> 化解率: {rate:.1f}%"
        )

        return round(rate, 2)

    def calculate_overall_resonance(self, conversation_id: int) -> Dict[str, Any]:
        """Calculate overall emotional resonance score."""
        debug_log(f"\n{'*' * 40}")
        debug_log(f"[情感共振率] 开始计算，会话 ID {conversation_id}")
        debug_log("*[说明] 情感共振率现采用“3个基础子维度 + 2个加分项”模型*")

        bidirectional_rate = self.calculate_bidirectional_positive_response(conversation_id)
        polarity_score = self.calculate_polarity_consistency(conversation_id)
        intensity_score = self.calculate_intensity_matching(conversation_id)
        empathy_rate = self.calculate_empathy_recognition(conversation_id)
        resolution_rate = self.calculate_negative_resolution(conversation_id)
        all_pairs = self._get_interaction_pairs(conversation_id)
        positive_pairs = [
            pair for pair in all_pairs if pair["from_polarity"] == 1 and self._is_within_positive_response_window(pair)
        ]
        confidence_meta = self._build_relationship_confidence_meta(
            conversation_id,
            all_pairs,
            positive_pairs,
        )

        base_score = (
            bidirectional_rate * self.CORE_BIDIRECTIONAL_WEIGHT
            + polarity_score * self.CORE_POLARITY_WEIGHT
            + intensity_score * self.CORE_INTENSITY_WEIGHT
        )
        empathy_bonus = empathy_rate * self.EMPATHY_BONUS_RATIO
        resolution_bonus = resolution_rate * self.NEGATIVE_RESOLUTION_BONUS_RATIO
        raw_overall_score = max(
            0.0,
            min(100.0, base_score + empathy_bonus + resolution_bonus),
        )
        overall_score = round(
            self._apply_confidence_shrinkage(
                raw_overall_score,
                confidence_meta["relationship_depth_confidence"],
                self.NEUTRAL_RESONANCE_BASELINE,
            ),
            2,
        )
        base_score = round(base_score, 2)
        empathy_bonus = round(empathy_bonus, 2)
        resolution_bonus = round(resolution_bonus, 2)
        debug_log("\n[情感共振率调试] --- 6. 综合得分（基础分 + 加分项） ---")
        debug_log(
            f"基础分 {base_score:.2f} = 双向积极互动 {bidirectional_rate:.2f} * 50% + "
            f"情绪一致性 {polarity_score:.2f} * 30% + 情绪强度匹配 {intensity_score:.2f} * 20%"
        )
        debug_log(
            f"加分项：共情识别 +{empathy_bonus:.2f}（最高 +10），"
            f"负面情绪化解 +{resolution_bonus:.2f}（最高 +10）"
        )
        debug_log(
            f"关系深度置信度: {confidence_meta['relationship_depth_confidence']:.2f}, "
            f"原始综合得分: {raw_overall_score:.2f}, 最终得分: {overall_score:.2f}"
        )
        if confidence_meta["low_confidence_reason"]:
            debug_log(f"低置信原因: {confidence_meta['low_confidence_reason']}")

        return {
            "overall_score": overall_score,
            "sub_scores": {
                "bidirectional_positive_response": bidirectional_rate,
                "polarity_consistency": polarity_score,
                "intensity_matching": intensity_score,
                "empathy_recognition": empathy_rate,
                "negative_resolution": resolution_rate,
            },
            "bonus_scores": {
                "base_resonance_score": base_score,
                "empathy_recognition_bonus": empathy_bonus,
                "negative_resolution_bonus": resolution_bonus,
            },
            "confidence_meta": confidence_meta,
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

        unit_metadata_map = self._batch_get_speech_unit_metadata(all_unit_ids)
        return [
            {
                "from_speech_unit_id": row[7],
                "to_speech_unit_id": row[6],
                "from_polarity": row[0],
                "to_polarity": row[1],
                "from_intensity": row[2],
                "to_intensity": row[3],
                "semantic_similarity": row[4],
                "time_gap": row[5],
                "to_content": unit_metadata_map.get(row[6], {}).get("content", ""),
                "from_content": unit_metadata_map.get(row[7], {}).get("content", ""),
                "to_timestamp": unit_metadata_map.get(row[6], {}).get("first_timestamp"),
                "from_timestamp": unit_metadata_map.get(row[7], {}).get("first_timestamp"),
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
        has_acknowledgement = self._has_supportive_acknowledgement(to_content)
        has_soft_support = self._has_supportive_neutral_phrase(to_content)
        is_fast = self._is_supportive_fast_response(pair)

        if to_polarity == 1 and has_soothing:
            return 1.0
        if to_polarity == 1 and (has_acknowledgement or has_soft_support):
            return 0.8
        if to_polarity == 1 or has_soothing:
            return 0.6
        if to_polarity == 0 and has_soothing and has_acknowledgement:
            return 0.6 if is_fast else 0.52
        if to_polarity == 0 and (has_acknowledgement or has_soft_support):
            return 0.52 if is_fast else 0.42
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

    def _build_weighted_opportunities(
        self, pairs: Sequence[Dict[str, Any]]
    ) -> List[tuple[Dict[str, Any], float]]:
        weighted_pairs: List[tuple[Dict[str, Any], float]] = []
        sorted_pairs = sorted(
            pairs,
            key=lambda pair: (
                int(pair.get("from_speech_unit_id") or 0),
                int(pair.get("to_speech_unit_id") or 0),
            ),
        )
        previous_pair: Dict[str, Any] | None = None
        episode_depth = 0

        for pair in sorted_pairs:
            weight = self._score_empathy_opportunity_weight(pair)
            if previous_pair and self._is_same_negative_episode(previous_pair, pair):
                episode_depth += 1
                decay_factor = max(
                    self.NEGATIVE_EPISODE_MIN_FACTOR,
                    self.NEGATIVE_EPISODE_DECAY ** episode_depth,
                )
                weight *= decay_factor
            else:
                episode_depth = 0
            if weight >= self.MIN_OPPORTUNITY_WEIGHT:
                weighted_pairs.append((pair, round(weight, 4)))
            previous_pair = pair
        return weighted_pairs

    def _score_empathy_opportunity_weight(self, pair: Dict[str, Any]) -> float:
        from_content = (pair.get("from_content", "") or "").strip()
        if not from_content:
            return self.AMBIGUOUS_OPPORTUNITY_WEIGHT

        direction_result = self.direction_service.classify(from_content)
        direction = getattr(direction_result, "direction", "ambiguous")
        confidence = float(getattr(direction_result, "confidence", 0.0) or 0.0)

        if direction == "to_others":
            return self.TO_OTHERS_OPPORTUNITY_WEIGHT
        if direction == "to_me":
            direction_weight = 1.0
        else:
            direction_weight = self.AMBIGUOUS_OPPORTUNITY_WEIGHT + confidence * 0.15

        severity_weight = self._score_negative_distress_weight(from_content)
        return round(max(self.MIN_OPPORTUNITY_WEIGHT, direction_weight * severity_weight), 4)

    def _score_negative_distress_weight(self, text: str) -> float:
        if not text:
            return 0.5

        strong_distress_terms = (
            "难受", "伤心", "委屈", "崩溃", "焦虑", "害怕", "想哭", "失眠",
            "不舒服", "头疼", "生病", "痛苦", "撑不住", "受不了", "emo",
        )
        medium_distress_terms = (
            "累", "烦", "压力", "难过", "低落", "心烦", "糟糕", "烦躁", "沮丧",
            "好惨", "太惨", "无助", "紧张",
        )
        complaint_terms = (
            "无语", "生气", "过分", "无聊", "骂人", "气死", "服了", "离谱",
            "真烦", "讨厌", "恶心",
        )
        self_signal_terms = ("我", "自己", "今天", "最近", "刚刚")

        if any(term in text for term in strong_distress_terms):
            return 1.0
        if any(term in text for term in medium_distress_terms):
            return 0.75 if any(term in text for term in self_signal_terms) else 0.65
        if any(term in text for term in complaint_terms):
            return 0.45 if any(term in text for term in self_signal_terms) else 0.35
        return 0.55

    def _is_same_negative_episode(
        self, previous_pair: Dict[str, Any], current_pair: Dict[str, Any]
    ) -> bool:
        previous_from_id = int(previous_pair.get("from_speech_unit_id") or 0)
        current_from_id = int(current_pair.get("from_speech_unit_id") or 0)
        if not previous_from_id or not current_from_id:
            return False
        if current_from_id <= previous_from_id:
            return False
        if (current_from_id - previous_from_id) > self.NEGATIVE_EPISODE_UNIT_GAP:
            return False

        previous_tags = self._extract_negative_signal_tags(previous_pair.get("from_content", ""))
        current_tags = self._extract_negative_signal_tags(current_pair.get("from_content", ""))
        if previous_tags and current_tags:
            return bool(previous_tags & current_tags)

        previous_text = (previous_pair.get("from_content", "") or "").strip()
        current_text = (current_pair.get("from_content", "") or "").strip()
        if not previous_text or not current_text:
            return False
        return previous_text == current_text

    def _extract_negative_signal_tags(self, text: str) -> set[str]:
        normalized = text or ""
        tag_map = {
            "distress": ("难受", "伤心", "委屈", "崩溃", "想哭", "emo"),
            "fatigue": ("累", "疲惫", "撑不住"),
            "stress": ("压力", "焦虑", "紧张", "烦躁"),
            "complaint": ("无语", "生气", "过分", "离谱", "太烦", "讨厌"),
            "health": ("不舒服", "头疼", "生病"),
        }
        tags = set()
        for tag, terms in tag_map.items():
            if any(term in normalized for term in terms):
                tags.add(tag)
        return tags

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

    def _has_supportive_acknowledgement(self, text: str) -> bool:
        return self._contains_keywords(
            text,
            self._merge_keywords(
                self.keyword_lib.get_keywords("empathy"),
                list(self.SUPPORTIVE_ACKNOWLEDGEMENT_KEYWORDS),
            ),
        )

    def _has_supportive_neutral_phrase(self, text: str) -> bool:
        return self._contains_keywords(
            text,
            self._merge_keywords(
                self.keyword_lib.get_keywords("soothing"),
                list(self.SUPPORTIVE_NEUTRAL_KEYWORDS),
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
        has_acknowledgement = self._has_supportive_acknowledgement(to_content)
        has_soft_support = self._has_supportive_neutral_phrase(to_content)
        is_detailed_reply = len(to_content.strip()) >= self.DETAILED_RESPONSE_LENGTH_THRESHOLD
        is_engaged = (
            semantic_similarity >= self.SEMANTIC_SIMILARITY_THRESHOLD
            or has_question
            or is_detailed_reply
            or has_acknowledgement
        )

        if to_polarity == 1 and has_explicit_empathy:
            return 1.0
        if to_polarity == 1 and has_acknowledgement and is_engaged:
            return 0.85
        if to_polarity == 1 and has_soft_support:
            return 0.78
        if to_polarity == 1 and is_engaged:
            return 0.7
        if to_polarity == 0 and has_explicit_empathy:
            return 0.6
        if to_polarity == 0 and has_acknowledgement and is_engaged:
            return 0.72
        if to_polarity == 0 and has_soft_support and is_engaged:
            return 0.62
        if to_polarity == 0 and has_acknowledgement:
            return 0.55
        if to_polarity == 0 and has_soft_support:
            return 0.5
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

    def _batch_get_speech_unit_metadata(self, unit_ids: set) -> Dict[int, Dict[str, Any]]:
        if not unit_ids:
            return {}

        result_map: Dict[int, Dict[str, Any]] = {}
        unit_id_list = list(unit_ids)
        placeholders = ",".join("?" * len(unit_id_list))
        cursor = get_db().execute(
            (
                f"SELECT id, message_ids, first_message_timestamp "
                f"FROM speech_units WHERE id IN ({placeholders})"
            ),
            unit_id_list,
        )

        unit_msg_map: Dict[int, List[int]] = {}
        unit_ts_map: Dict[int, int] = {}
        all_msg_ids = set()
        for row in cursor.fetchall():
            try:
                msg_ids = json.loads(row[1])
            except Exception:
                msg_ids = []
            if msg_ids:
                unit_msg_map[row[0]] = msg_ids
                all_msg_ids.update(msg_ids)
            unit_ts_map[row[0]] = row[2] or 0

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
            result_map[unit_id] = {
                "content": " ".join(msg_content_map.get(mid, "") for mid in msg_ids),
                "first_timestamp": unit_ts_map.get(unit_id, 0),
            }

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
    def _calculate_sample_confidence(sample_count: int, target_count: int) -> float:
        if target_count <= 0:
            return 1.0
        return max(0.0, min(1.0, sample_count / target_count))

    @staticmethod
    def _apply_confidence_shrinkage(
        raw_score: float, confidence: float, neutral_score: float
    ) -> float:
        adjusted = raw_score * confidence + neutral_score * (1 - confidence)
        return max(0.0, min(100.0, adjusted))

    def _build_relationship_confidence_meta(
        self,
        conversation_id: int,
        pairs: Sequence[Dict[str, Any]],
        positive_pairs: Sequence[Dict[str, Any]],
    ) -> Dict[str, Any]:
        active_day_count, span_day_count = self._get_pair_activity_day_stats(conversation_id, pairs)
        pair_confidence = self._calculate_sample_confidence(
            len(pairs), self.DEPTH_PAIR_COUNT_TARGET
        )
        positive_confidence = self._calculate_sample_confidence(
            len(positive_pairs), self.DEPTH_POSITIVE_PAIR_TARGET
        )
        active_day_confidence = self._calculate_sample_confidence(
            active_day_count, self.DEPTH_ACTIVE_DAY_TARGET
        )
        span_confidence = self._calculate_sample_confidence(
            span_day_count, self.DEPTH_SPAN_DAY_TARGET
        )
        relationship_depth_confidence = round(
            pair_confidence * 0.4
            + positive_confidence * 0.3
            + active_day_confidence * 0.2
            + span_confidence * 0.1,
            4,
        )
        low_confidence_reason = self._build_low_confidence_reason(
            len(pairs),
            len(positive_pairs),
            active_day_count,
            span_day_count,
            relationship_depth_confidence,
        )
        return {
            "relationship_depth_confidence": relationship_depth_confidence,
            "interaction_pair_count": len(pairs),
            "positive_pair_count": len(positive_pairs),
            "active_day_count": active_day_count,
            "low_confidence_reason": low_confidence_reason,
        }

    def _get_pair_activity_day_stats(
        self, conversation_id: int, pairs: Sequence[Dict[str, Any]]
    ) -> tuple[int, int]:
        unit_ids = set()
        for pair in pairs:
            from_id = pair.get("from_speech_unit_id")
            to_id = pair.get("to_speech_unit_id")
            if from_id:
                unit_ids.add(int(from_id))
            if to_id:
                unit_ids.add(int(to_id))

        if not unit_ids:
            cursor = get_db().execute(
                """
                SELECT COUNT(DISTINCT DATE(timestamp, 'unixepoch', 'localtime')) AS active_days,
                       MIN(timestamp) AS first_ts,
                       MAX(timestamp) AS last_ts
                FROM messages
                WHERE conversation_id = ?
                """,
                (conversation_id,),
            )
            row = cursor.fetchone()
            active_days = int((row[0] or 0) if row else 0)
            first_ts = int((row[1] or 0) if row else 0)
            last_ts = int((row[2] or 0) if row else 0)
            if not first_ts or not last_ts:
                return active_days, 0
            span_days = max(1, (last_ts - first_ts) // 86400 + 1)
            return active_days, span_days

        unit_id_list = list(unit_ids)
        placeholders = ",".join("?" * len(unit_id_list))
        cursor = get_db().execute(
            (
                f"SELECT first_message_timestamp FROM speech_units "
                f"WHERE conversation_id = ? AND id IN ({placeholders})"
            ),
            [conversation_id, *unit_id_list],
        )
        timestamps = [int(row[0] or 0) for row in cursor.fetchall() if row[0]]
        if not timestamps:
            return 0, 0
        active_days = len(
            {
                datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d")
                for timestamp in timestamps
            }
        )
        span_days = max(1, (max(timestamps) - min(timestamps)) // 86400 + 1)
        return active_days, span_days

    def _build_low_confidence_reason(
        self,
        pair_count: int,
        positive_pair_count: int,
        active_day_count: int,
        span_day_count: int,
        relationship_depth_confidence: float,
    ) -> str:
        if relationship_depth_confidence >= self.RELATIONSHIP_DEPTH_LOW_CONFIDENCE_THRESHOLD:
            return ""

        reasons: List[str] = []
        if pair_count < self.DEPTH_PAIR_COUNT_TARGET:
            reasons.append("互动轮次偏少")
        if positive_pair_count < self.DEPTH_POSITIVE_PAIR_TARGET:
            reasons.append("稳定积极回应样本不足")
        if active_day_count < self.DEPTH_ACTIVE_DAY_TARGET:
            reasons.append("活跃天数较少")
        if span_day_count < self.DEPTH_SPAN_DAY_TARGET:
            reasons.append("跨时间分布不足")
        return "、".join(reasons)

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
