"""互动投入服务 - 计算互动投入维度

聊天积极度的重组升级版：吸收亲密度信号的回复对称性子项，并新增两个
投入方向特征（长时未回应、连发未回，数据来自 engagement_metrics）。

包含 7 个子维度：
1. 消息频率 (10%)
2. 回复及时性 (20%)
3. 话题延续性 (20%)
4. 主动发起 (20%)
5. 回应对称性 (10%，自亲密度信号迁入)
6. 长时未回应 (10%，反向：对方越少长时沉默越高)
7. 连发未回 (10%，方向差：对方追着连发加分、我方连发不获回应减分)

包含 1 个加分项：
- 长文本占比 (最高加 10 分)
"""

import logging
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from ...db.connection import get_db
from .engagement_metrics import EngagementMetrics
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
class InteractionInvestmentResult:
    """互动投入计算结果"""

    # 子维度分数 (0-100)
    daily_message_score: float = 0.0
    reply_timeliness_score: float = 0.0
    topic_continuity_score: float = 0.0
    active_initiation_score: float = 0.0
    reply_symmetry_score: float = 0.0
    long_unanswered_score: float = 0.0
    burst_unanswered_score: float = 0.0

    # 加分项
    long_text_bonus: float = 0.0

    # 综合评分 (0-100)
    overall_score: float = 0.0

    # 解释文本
    interpretation: str = ""

    # 原始值 (用于调试和展示)
    daily_message_count: float = 0.0
    reply_timeliness_rate: float = 0.0
    topic_continuity_avg: float = 0.0
    active_initiation_rate: float = 0.0
    char_balance: float = 0.5
    long_unanswered_other_per_100: float = 0.0
    burst_other_per_100: float = 0.0
    burst_self_per_100: float = 0.0

    # 元信息（回应对称性预警等）
    confidence_meta: Optional[Dict] = None


class InteractionInvestmentService:
    """互动投入服务 - 计算互动投入维度"""

    # 子维度权重
    WEIGHT_DAILY_MESSAGE = 0.10
    WEIGHT_REPLY_TIMELINESS = 0.20
    WEIGHT_TOPIC_CONTINUITY = 0.20
    WEIGHT_ACTIVE_INITIATION = 0.20
    WEIGHT_REPLY_SYMMETRY = 0.10
    WEIGHT_LONG_UNANSWERED = 0.10
    WEIGHT_BURST_UNANSWERED = 0.10

    # 评分标准化参数
    DAILY_MESSAGE_BASELINE = 10.0  # 日均 10 条消息为满分基准
    LONG_TEXT_THRESHOLD = 50       # 长文本阈值 (字符数)
    # 对方每百条消息 6.7 次长时未回应 → 该子项归零
    LONG_UNANSWERED_ZERO_POINT_PER_100 = 6.7
    # 连发方向差换算：每百条消息差 5 次连发 → ±100 分摆幅
    BURST_DIRECTION_FACTOR = 20.0
    NEUTRAL_POSITIVITY_BASELINE = 38.0
    SESSION_CONFIDENCE_TARGET = 20
    ACTIVE_DAY_CONFIDENCE_TARGET = 25
    CONFIDENCE_SHRINKAGE_POWER = 1.5

    def __init__(self, timeliness_threshold_seconds: int = 300, long_text_threshold: int = 100):
        """
        初始化互动投入服务

        Args:
            timeliness_threshold_seconds: 回复及时阈值 (秒)，默认 5 分钟
            long_text_threshold: 长消息判定字数阈值，默认 100（与 affinity_config 默认一致）
        """
        self.timeliness_threshold = timeliness_threshold_seconds
        self.long_text_threshold = long_text_threshold
        self._pair_service = None
        self._sentiment_service = None

    def calculate_scores(
        self,
        conversation_id: int,
        stats: PreprocessedStatistics,
        metrics: EngagementMetrics,
    ) -> InteractionInvestmentResult:
        """
        计算所有子维度分数并返回综合评分

        Args:
            conversation_id: 会话 ID
            stats: 预处理统计数据
            metrics: 会话投入特征（engagement_metrics 一遍扫描产物）

        Returns:
            InteractionInvestmentResult: 包含所有分数和解释的结果
        """
        result = InteractionInvestmentResult()

        debug_log(f"\n{'*'*40}")
        debug_log(f"【互动投入】开始计分 (会话 ID {conversation_id})")

        # 1. 消息频率 (10%)
        result.daily_message_count = self._calculate_daily_message_count_raw(stats)
        result.daily_message_score = self.calculate_daily_message_score(
            stats, raw_count=result.daily_message_count
        )

        # 2. 回复及时性 (20%)
        result.reply_timeliness_rate = self._calculate_reply_timeliness_raw(conversation_id)
        result.reply_timeliness_score = self.calculate_reply_timeliness_score(
            conversation_id, raw_rate=result.reply_timeliness_rate
        )

        # 3. 话题延续性 (20%)
        result.topic_continuity_avg = self._calculate_topic_continuity_raw(conversation_id)
        result.topic_continuity_score = self.calculate_topic_continuity_score(
            conversation_id, raw_avg=result.topic_continuity_avg
        )

        # 4. 主动发起 (20%)
        result.active_initiation_rate = self._calculate_active_initiation_raw(stats)
        result.active_initiation_score = self.calculate_active_initiation_score(
            stats, raw_rate=result.active_initiation_rate
        )

        # 5. 回应对称性 (10%，自亲密度信号迁入)
        result.reply_symmetry_score, symmetry_meta = self._calculate_reply_symmetry(
            conversation_id, self.long_text_threshold
        )
        result.char_balance = symmetry_meta.get("char_balance", 0.5)

        # 6. 长时未回应 (10%，反向)
        result.long_unanswered_other_per_100 = self._per_100(
            metrics.long_unanswered_other, metrics.text_message_count
        )
        result.long_unanswered_score = self._calculate_long_unanswered_score(
            result.long_unanswered_other_per_100
        )

        # 7. 连发未回 (10%，方向差)
        result.burst_other_per_100 = self._per_100(
            metrics.burst_unanswered_other, metrics.text_message_count
        )
        result.burst_self_per_100 = self._per_100(
            metrics.burst_unanswered_self, metrics.text_message_count
        )
        result.burst_unanswered_score = self._calculate_burst_unanswered_score(
            result.burst_other_per_100, result.burst_self_per_100
        )

        # 加分项: 长文本占比 (最高 10 分)
        result.long_text_bonus = self.calculate_long_text_bonus(conversation_id, stats)

        confidence_meta = dict(symmetry_meta)

        # 综合评分
        raw_overall_score = self._calculate_overall_score(result)
        relationship_confidence = self._calculate_relationship_confidence(stats)
        result.overall_score = self._apply_confidence_shrinkage(
            raw_overall_score,
            relationship_confidence,
            self.NEUTRAL_POSITIVITY_BASELINE,
        )
        result.confidence_meta = confidence_meta

        # 生成解释
        result.interpretation = self.generate_interpretation(result)

        logger.info(f"互动投入计算完成: {result.overall_score:.1f} 分 (会话 {conversation_id})")
        return result

    # ========================================
    # 子维度分数计算方法
    # ========================================

    @staticmethod
    def _per_100(events: int, total_messages: int) -> float:
        """事件数折算为每百条消息频次。"""
        if total_messages <= 0:
            return 0.0
        return events / total_messages * 100.0

    def calculate_daily_message_score(
        self, stats: PreprocessedStatistics, raw_count: Optional[float] = None
    ) -> float:
        """
        计算消息频率得分 (0-100)

        公式: min(日均消息数 / 基准值 * 100, 100)
        基准值: 10 条/天
        """
        daily_count = (
            raw_count
            if raw_count is not None
            else self._calculate_daily_message_count_raw(stats)
        )
        score = min((daily_count / self.DAILY_MESSAGE_BASELINE) * 100, 100)
        return round(score, 2)

    def _calculate_daily_message_count_raw(self, stats: PreprocessedStatistics) -> float:
        """计算日均消息数原始值"""
        if stats.conversation_duration_days <= 0:
            return 0.0
        return stats.total_message_count / max(stats.conversation_duration_days, 1.0)

    def calculate_reply_timeliness_score(
        self, conversation_id: int, raw_rate: Optional[float] = None
    ) -> float:
        """
        计算回复及时性得分 (0-100)

        公式: (及时回复交互对数 / 总交互对数) × 100 × 交互对数量衰减
        及时: 回复时间 <= timeliness_threshold
        """
        timeliness_rate = (
            raw_rate
            if raw_rate is not None
            else self._calculate_reply_timeliness_raw(conversation_id)
        )

        try:
            cursor = get_db().execute(
                """
                SELECT COUNT(*)
                FROM interaction_pairs
                WHERE conversation_id = ?
                """,
                (conversation_id,),
            )
            pair_count = cursor.fetchone()[0] or 0
        except Exception as e:
            logger.error(f"获取交互对数量失败: {e}")
            pair_count = 0

        pair_dampening = min(1.0, pair_count / 15.0)
        return round(timeliness_rate * 100 * pair_dampening, 2)

    def _calculate_reply_timeliness_raw(self, conversation_id: int) -> float:
        """
        计算回复及时率原始值 (0-1)

        从交互对表中统计在阈值时间内回复的比例
        """
        try:
            cursor = get_db().execute("""
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
            cursor = get_db().execute("""
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

    def calculate_topic_continuity_score(
        self, conversation_id: int, raw_avg: Optional[float] = None
    ) -> float:
        """
        计算话题延续性得分 (0-100)

        公式: min((平均语义相似度 / 0.5) * 100, 100)
        """
        continuity = (
            raw_avg
            if raw_avg is not None
            else self._calculate_topic_continuity_raw(conversation_id)
        )
        score = min((continuity / 0.5) * 100, 100)
        return round(score, 2)

    def _calculate_topic_continuity_raw(self, conversation_id: int) -> float:
        """
        计算话题延续性原始值 (0-1)

        使用交互对的语义相似度平均值
        """
        try:
            cursor = get_db().execute("""
                SELECT COUNT(semantic_similarity), AVG(semantic_similarity)
                FROM interaction_pairs
                WHERE conversation_id = ?
                    AND semantic_similarity IS NOT NULL
            """, (conversation_id,))

            row = cursor.fetchone()
            similarity_count = row[0] or 0
            avg_similarity = row[1] if row[1] is not None else 0.0

            if similarity_count > 0:
                return max(0.0, min(1.0, avg_similarity))

            return self._calculate_topic_continuity_from_sessions(conversation_id)

        except Exception as e:
            logger.error(f"计算话题延续性失败: {e}")
            return 0.0

    def _calculate_topic_continuity_from_sessions(self, conversation_id: int) -> float:
        """历史数据兜底: 按会话重建连续性分数."""
        try:
            cursor = get_db().execute("""
                SELECT start_time, end_time
                FROM sessions
                WHERE conversation_id = ?
                ORDER BY start_time ASC
            """, (conversation_id,))
            session_ranges = cursor.fetchall()

            if not session_ranges:
                return 0.0

            session_scores: List[float] = []
            for start_time, end_time in session_ranges:
                messages = self._load_messages_for_time_range(
                    conversation_id,
                    start_time,
                    end_time
                )
                speech_units = self._get_pair_service().build_speech_units(messages)
                session_similarity = self._calculate_session_similarity(speech_units)
                if session_similarity is not None:
                    session_scores.append(session_similarity)

            if not session_scores:
                return 0.0

            return round(sum(session_scores) / len(session_scores), 4)

        except Exception as e:
            logger.warning(f"话题连续性会话兜底计算失败: {e}")
            return 0.0

    def _load_messages_for_time_range(
        self,
        conversation_id: int,
        start_time: int,
        end_time: int
    ) -> List[Dict[str, object]]:
        """加载指定时间窗内的文本消息."""
        cursor = get_db().execute("""
            SELECT id, content, is_sender, timestamp
            FROM messages
            WHERE conversation_id = ?
              AND message_type = 1
              AND timestamp >= ?
              AND timestamp <= ?
            ORDER BY timestamp ASC
        """, (conversation_id, start_time, end_time))

        messages: List[Dict[str, object]] = []
        for row in cursor.fetchall():
            content = row[1] if row[1] is not None else ""
            if isinstance(content, bytes):
                content = content.decode("utf-8", errors="replace")
            messages.append({
                "id": row[0],
                "content": content,
                "is_sender": row[2],
                "timestamp": row[3],
            })

        return messages

    def _calculate_session_similarity(
        self,
        speech_units: List[Dict[str, object]]
    ) -> Optional[float]:
        """计算单个会话内相邻发言单元的平均相似度."""
        if len(speech_units) < 2:
            return None

        texts = [(unit.get("content") or "").strip() for unit in speech_units]
        if len([text for text in texts if text]) < 2:
            return None

        try:
            sentiment_service = self._get_sentiment_service()
            sentiment_service._load_embedding_model()
            if sentiment_service._embedding_model is None:
                return None

            # 走缓存版批量编码（L1+L2），与主链路共享向量——直调 encode
            # 会绕过持久缓存（本兜底路径多为重复文本，命中率极高）
            embeddings = sentiment_service._get_embeddings_batch(texts, batch_size=32)

            import numpy as np

            similarities: List[float] = []
            for idx in range(len(embeddings) - 1):
                similarity = float(np.dot(embeddings[idx], embeddings[idx + 1]))
                similarities.append(max(0.0, min(1.0, similarity)))

            if not similarities:
                return None

            return sum(similarities) / len(similarities)

        except Exception as e:
            logger.warning(f"会话相似度计算失败: {e}")
            return None

    def _get_pair_service(self):
        if self._pair_service is None:
            from .preprocessing import PairPreprocessingService
            self._pair_service = PairPreprocessingService()
        return self._pair_service

    def _get_sentiment_service(self):
        if self._sentiment_service is None:
            from .sentiment_service import SentimentService
            self._sentiment_service = SentimentService()
        return self._sentiment_service

    def calculate_active_initiation_score(
        self, stats: PreprocessedStatistics, raw_rate: Optional[float] = None
    ) -> float:
        """
        计算主动发起得分 (0-100)

        公式: min((对方发起会话数 / 总会话数 / 0.5) * 100, 100)
        """
        rate = (
            raw_rate
            if raw_rate is not None
            else self._calculate_active_initiation_raw(stats)
        )
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

        return stats.contact_initiated_count / total_sessions

    # ========================================
    # 回应对称性（自亲密度信号迁入）
    # ========================================

    def _calculate_reply_symmetry(
        self, conversation_id: int, long_text_threshold: int = 100
    ) -> Tuple[float, Dict]:
        """双方字数投入、长消息占比差与表情包互动的均衡度。"""
        meta: Dict = {}

        # 字数均衡（message_preprocessed 按发送方汇总）
        char_rows = get_db().execute(
            """
            SELECT m.is_sender, SUM(mp.char_count) AS chars, COUNT(*) AS msgs
            FROM messages m
            JOIN message_preprocessed mp ON mp.message_id = m.id
            WHERE m.conversation_id = ? AND mp.is_valid = 1
            GROUP BY m.is_sender
            """,
            (conversation_id,),
        ).fetchall()
        other_chars = user_chars = 0
        for r in char_rows:
            if int(r[0] or 0) == 0:
                other_chars = int(r[1] or 0)
            else:
                user_chars = int(r[1] or 0)
        total_chars = other_chars + user_chars
        if total_chars <= 0:
            balance_score = 50.0
            balance = 0.5
        else:
            balance = other_chars / total_chars
            # 每偏离均衡 10 个百分点扣 8 分
            balance_score = max(0.0, 100.0 - abs(balance - 0.5) * 100 * 0.8)
        meta["char_balance"] = round(balance, 4)

        # 长消息占比差
        long_rows = get_db().execute(
            """
            SELECT m.is_sender,
                   SUM(CASE WHEN mp.char_count >= ? THEN 1 ELSE 0 END) AS long_msgs,
                   COUNT(*) AS msgs
            FROM messages m
            JOIN message_preprocessed mp ON mp.message_id = m.id
            WHERE m.conversation_id = ? AND mp.is_valid = 1
            GROUP BY m.is_sender
            """,
            (int(long_text_threshold), conversation_id),
        ).fetchall()
        other_share = user_share = 0.0
        for r in long_rows:
            msgs = int(r[2] or 0)
            if msgs <= 0:
                continue
            share = int(r[1] or 0) / msgs
            if int(r[0] or 0) == 0:
                other_share = share
            else:
                user_share = share
        long_diff_score = max(0.0, 100.0 - min(100.0, abs(other_share - user_share) * 250))
        meta["long_share_other"] = round(other_share, 4)
        meta["long_share_user"] = round(user_share, 4)

        # 表情包互动（type=47 计数；内容在预处理中被清洗，仅计数可用）
        sticker_rows = get_db().execute(
            """
            SELECT is_sender, COUNT(*) AS n FROM messages
            WHERE conversation_id = ? AND message_type = 47
            GROUP BY is_sender
            """,
            (conversation_id,),
        ).fetchall()
        other_total = get_db().execute(
            "SELECT COUNT(*) FROM messages WHERE conversation_id = ? AND is_sender = 0",
            (conversation_id,),
        ).fetchone()[0]
        other_stickers = 0
        for r in sticker_rows:
            if int(r[0] or 0) == 0:
                other_stickers = int(r[1] or 0)
        sticker_rate = (other_stickers / other_total) if other_total else 0.0
        sticker_score = min(1.0, sticker_rate / 0.05) * 100
        meta["other_sticker_rate"] = round(sticker_rate, 4)

        score = balance_score * 0.40 + long_diff_score * 0.35 + sticker_score * 0.25
        if balance < 0.35 and (other_share - user_share) < -0.15:
            meta["asymmetry_warning"] = True
        elif 0.4 <= balance <= 0.6:
            meta["well_balanced"] = True
        return max(0.0, min(100.0, score)), meta

    # ========================================
    # 投入方向特征（engagement_metrics）
    # ========================================

    @classmethod
    def _calculate_long_unanswered_score(cls, per_100_other: float) -> float:
        """长时未回应得分：对方每百条消息的长时未回应次数越少越高。"""
        score = 100.0 - min(100.0, per_100_other / cls.LONG_UNANSWERED_ZERO_POINT_PER_100 * 100.0)
        return round(max(0.0, min(100.0, score)), 2)

    @classmethod
    def _calculate_burst_unanswered_score(
        cls, per_100_other: float, per_100_self: float
    ) -> float:
        """连发未回得分：对方连发未获回应（追着聊）加分，我方连发不获回应减分。"""
        if per_100_other <= 0 and per_100_self <= 0:
            return 60.0
        score = 50.0 + (per_100_other - per_100_self) * cls.BURST_DIRECTION_FACTOR
        return round(max(0.0, min(100.0, score)), 2)

    # ========================================
    # 综合评分和解释
    # ========================================

    def _calculate_overall_score(self, result: InteractionInvestmentResult) -> float:
        """
        计算综合评分 (加权平均)

        权重:
        - 消息频率: 10%
        - 回复及时性: 20%
        - 话题延续性: 20%
        - 主动发起: 20%
        - 回应对称性: 10%
        - 长时未回应: 10%
        - 连发未回: 10%
        加分:
        - 长文本占比加分 (最高10分)
        """
        overall = (
            result.daily_message_score * self.WEIGHT_DAILY_MESSAGE +
            result.reply_timeliness_score * self.WEIGHT_REPLY_TIMELINESS +
            result.topic_continuity_score * self.WEIGHT_TOPIC_CONTINUITY +
            result.active_initiation_score * self.WEIGHT_ACTIVE_INITIATION +
            result.reply_symmetry_score * self.WEIGHT_REPLY_SYMMETRY +
            result.long_unanswered_score * self.WEIGHT_LONG_UNANSWERED +
            result.burst_unanswered_score * self.WEIGHT_BURST_UNANSWERED
        )
        overall += result.long_text_bonus
        return min(round(overall, 2), 100.0)

    def _calculate_relationship_confidence(self, stats: PreprocessedStatistics) -> float:
        session_confidence = min(
            1.0, (stats.total_sessions or 0) / self.SESSION_CONFIDENCE_TARGET
        )
        active_day_confidence = min(
            1.0, (stats.chat_days_count or 0) / self.ACTIVE_DAY_CONFIDENCE_TARGET
        )
        return round(session_confidence * 0.55 + active_day_confidence * 0.45, 4)

    @staticmethod
    def _apply_confidence_shrinkage(
        raw_score: float, confidence: float, neutral_score: float
    ) -> float:
        effective_confidence = (
            max(0.0, min(1.0, confidence))
            ** InteractionInvestmentService.CONFIDENCE_SHRINKAGE_POWER
        )
        adjusted = raw_score * effective_confidence + neutral_score * (1 - effective_confidence)
        return round(max(0.0, min(100.0, adjusted)), 2)

    def generate_interpretation(self, result: InteractionInvestmentResult) -> str:
        """根据综合分与方向特征生成解释文本"""
        if result.overall_score >= 80:
            lead = "对方互动投入非常高，回复及时且主动发起话题，对这段关系非常投入"
        elif result.overall_score >= 60:
            lead = "对方互动投入较高，愿意投入时间和精力维持对话"
        elif result.overall_score >= 40:
            lead = "对方互动投入一般，偶尔主动但不够热情"
        elif result.overall_score >= 20:
            lead = "对方互动投入较低，回复较慢且较少主动发起话题"
        else:
            lead = "对方互动投入很低，可能对这段关系兴趣不大"

        notes = []
        if result.long_unanswered_other_per_100 >= 5.0:
            notes.append("对方长时未回应偏多")
        if result.burst_self_per_100 >= 5.0 and result.burst_self_per_100 > result.burst_other_per_100 * 2:
            notes.append("我方连发常未获回应")
        if result.confidence_meta and result.confidence_meta.get("asymmetry_warning"):
            notes.append("双方投入明显不对称")
        if notes:
            return f"{lead}（{('；'.join(notes))}）"
        return lead
