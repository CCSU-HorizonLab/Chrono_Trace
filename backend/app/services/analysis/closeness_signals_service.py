"""亲近信号维度：称谓演变、时段亲近、活跃覆盖与投入方向标记。

亲密度信号的重组深化版：回应对称性迁出至互动投入，吸收态度倾向的
亲近类加分（隐私分享/节日互动/语音视频），并新增三个投入方向标记：
- 早晚安发起——日常仪式感的发起归属；
- 主动破冰——长时间沉默后谁先开口（>24h 沉默的恢复方）；
- 共同体表达——对方用「我们/咱们」指称两人事项的倾向。

六个子项各 0-100 分，子权重 30/15/10/15/15/15；加分项封顶 15。
"""

from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import Any, Dict, Tuple

from ...db.connection import get_db
from .affinity_debug_logger import affinity_debug_log
from .engagement_metrics import EngagementMetrics
from .keyword_libraries import KeywordLibraries, get_shared_keyword_libraries
from .preprocessing_orchestrator import PreprocessedStatistics

logger = logging.getLogger(__name__)

# 职务/正式称谓（Tier1）：姓氏或姓名 + 称谓后缀，或泛称
FORMAL_ADDRESS_RE = re.compile(
    r"(?:[一-龥]{1,3}?(?:总|哥|姐|老师|医生|教授|工|经理|主任|局长|处长)|"
    r"老板|师傅|领导|同学|同事)",
)

# 子项权重
SUB_WEIGHTS = {
    "address_term_evolution": 0.30,
    "late_night_engagement": 0.15,
    "active_coverage": 0.10,
    "greeting_initiation": 0.15,
    "icebreaking": 0.15,
    "community_expression": 0.15,
}

# 深夜窗口（23:00-05:00）
LATE_NIGHT_HOURS = {23, 0, 1, 2, 3, 4}

# 称谓满档线：后半段 5% 的消息含昵称即触达满分档
ADDRESS_FULL_RATE = 0.05
# 非工作时段主动发起满档线：30% 即满分档
OFFHOURS_INITIATION_FULL_RATE = 0.30
# 深夜消息占比满档线
LATE_NIGHT_MESSAGE_FULL_RATE = 0.10
# 共同体表达满档线：对方第一人称指称中 30% 为「我们」类即满分
COMMUNITY_FULL_RATE = 0.30

# 加分项上限（自态度倾向迁入）
PRIVACY_BONUS_MAX = 5.0
HOLIDAY_BONUS_MAX = 7.0
VIDEO_BONUS_MAX = 5.0
VOICE_BONUS_MAX = 10.0
TOTAL_BONUS_CAP = 15.0


class ClosenessSignalsService:
    """亲近信号维度评分服务。"""

    def __init__(self):
        self.keyword_libraries = get_shared_keyword_libraries()

    # ---------- 编排 ----------

    def calculate_overall_closeness(
        self,
        conversation_id: int,
        stats: PreprocessedStatistics,
        metrics: EngagementMetrics,
    ) -> Dict[str, Any]:
        address_score, address_meta = self._calculate_address_term_evolution(
            conversation_id
        )
        late_score, late_meta = self._calculate_late_night_engagement(conversation_id)
        coverage_score, coverage_meta = self._calculate_active_coverage(
            conversation_id, stats
        )
        greeting_score, greeting_meta = self._calculate_greeting_initiation(metrics)
        icebreak_score, icebreak_meta = self._calculate_icebreaking(metrics)
        community_score, community_meta = self._calculate_community_expression(metrics)

        sub_scores = {
            "address_term_evolution": round(address_score, 2),
            "late_night_engagement": round(late_score, 2),
            "active_coverage": round(coverage_score, 2),
            "greeting_initiation": round(greeting_score, 2),
            "icebreaking": round(icebreak_score, 2),
            "community_expression": round(community_score, 2),
        }
        overall_base = (
            address_score * SUB_WEIGHTS["address_term_evolution"]
            + late_score * SUB_WEIGHTS["late_night_engagement"]
            + coverage_score * SUB_WEIGHTS["active_coverage"]
            + greeting_score * SUB_WEIGHTS["greeting_initiation"]
            + icebreak_score * SUB_WEIGHTS["icebreaking"]
            + community_score * SUB_WEIGHTS["community_expression"]
        )

        bonus_scores = self._calculate_bonus_scores(conversation_id, stats)
        overall = min(100.0, overall_base + bonus_scores["total_bonus"])

        interpretation = self._generate_interpretation(
            overall, address_meta, late_meta, icebreak_meta, greeting_meta
        )
        confidence_meta: Dict[str, Any] = {}
        for meta in (address_meta, late_meta, coverage_meta, greeting_meta,
                     icebreak_meta, community_meta):
            confidence_meta.update(meta)

        affinity_debug_log(
            f"[亲近信号] 会话 {conversation_id}: 称谓={address_score:.1f} "
            f"深夜={late_score:.1f} 覆盖={coverage_score:.1f} "
            f"早晚安={greeting_score:.1f} 破冰={icebreak_score:.1f} "
            f"共同体={community_score:.1f} → 总={overall:.1f}"
        )
        return {
            "overall_score": round(max(0.0, min(100.0, overall)), 2),
            "interpretation": interpretation,
            "sub_scores": sub_scores,
            "bonus_scores": bonus_scores,
            "confidence_meta": confidence_meta,
        }

    def _generate_interpretation(
        self,
        overall: float,
        address_meta: Dict,
        late_meta: Dict,
        icebreak_meta: Dict,
        greeting_meta: Dict,
    ) -> str:
        if address_meta.get("address_term_low_confidence"):
            address_note = "未检测到明显称谓变化，按中性计"
        elif address_meta.get("address_warming"):
            address_note = "称谓随时间明显变得亲近"
        elif address_meta.get("address_cooling"):
            address_note = "称谓趋于正式，或有距离感"
        else:
            address_note = "称谓保持稳定"

        notes = []
        if late_meta.get("offhours_engaged"):
            notes.append("对方愿意在深夜/周末等私人时段投入聊天")
        if icebreak_meta.get("icebreak_other_led"):
            notes.append("长时间沉默后多为对方先开口")
        elif icebreak_meta.get("icebreak_self_led"):
            notes.append("长时间沉默后多为我方先开口")
        if greeting_meta.get("greeting_other_led"):
            notes.append("早晚安多为对方发起")

        if overall >= 70:
            lead = "亲近信号较强"
        elif overall >= 45:
            lead = "亲近信号中等"
        else:
            lead = "亲近信号偏弱"
        if notes:
            return f"{lead}：{address_note}；{'；'.join(notes)}"
        return f"{lead}：{address_note}"

    # ---------- 子项 1：称谓演变 ----------

    def _calculate_address_term_evolution(
        self, conversation_id: int
    ) -> Tuple[float, Dict[str, Any]]:
        """前后半段对照称谓强度：昵称（Tier2）直接计亲密，正式称谓
        （Tier1）只作演变参照与在场证据——全程"X总"应是中等偏低分。
        """
        rows = get_db().execute(
            """
            SELECT m.timestamp, mp.cleaned_content
            FROM messages m
            JOIN message_preprocessed mp ON mp.message_id = m.id
            WHERE m.conversation_id = ?
              AND m.is_sender = 0
              AND m.message_type = 1
              AND mp.is_valid = 1
            ORDER BY m.timestamp ASC
            """,
            (conversation_id,),
        ).fetchall()
        meta: Dict[str, Any] = {
            "address_samples": len(rows),
            "address_early_rate": 0.0,
            "address_late_rate": 0.0,
        }
        if not rows:
            meta["address_term_low_confidence"] = True
            return 50.0, meta

        nickname_words = [
            w for w in (self.keyword_libraries.get_keywords(KeywordLibraries.NICKNAME) or [])
            if w
        ]

        def _tier(content: str) -> int:
            if any(word in content for word in nickname_words):
                return 2
            if FORMAL_ADDRESS_RE.search(content):
                return 1
            return 0

        half = len(rows) // 2
        segments = (rows[:half] or rows), (rows[half:] or rows[-1:])

        def _rates(segment) -> Tuple[float, float]:
            """返回 (昵称率, 综合强度=昵称率+0.5×正式率)。"""
            if not segment:
                return 0.0, 0.0
            tier2 = sum(
                1 for r in segment if _tier(str(r["cleaned_content"] or "")) == 2
            )
            tier1 = sum(
                1 for r in segment if _tier(str(r["cleaned_content"] or "")) == 1
            )
            count = len(segment)
            return tier2 / count, tier2 / count + 0.5 * tier1 / count

        (early_nick, early_intensity) = _rates(segments[0])
        (late_nick, late_intensity) = _rates(segments[-1])
        meta["address_early_rate"] = round(early_intensity, 4)
        meta["address_late_rate"] = round(late_intensity, 4)

        if early_intensity <= 0 and late_intensity <= 0:
            meta["address_term_low_confidence"] = True
            return 50.0, meta

        # 基础分只由昵称率驱动；正式称谓仅保 40 分在场档
        score = 40.0 + 60.0 * min(1.0, late_nick / ADDRESS_FULL_RATE)
        # 演变修正（±8）：强度（含正式→昵称迁移）前后对照
        if late_intensity > early_intensity * 1.25 and late_intensity >= 0.1:
            score += 8.0
            meta["address_warming"] = True
        elif early_intensity >= 0.1 and late_intensity < early_intensity * 0.8:
            score -= 8.0
            meta["address_cooling"] = True
        return max(0.0, min(100.0, score)), meta

    # ---------- 子项 2：深夜时段 ----------

    def _calculate_late_night_engagement(
        self, conversation_id: int
    ) -> Tuple[float, Dict[str, Any]]:
        """对方深夜消息占比与非工作时段主动发起。"""
        meta: Dict[str, Any] = {"time_low_confidence": False}

        sessions = get_db().execute(
            """
            SELECT start_time, initiator FROM sessions
            WHERE conversation_id = ?
            """,
            (conversation_id,),
        ).fetchall()
        other_initiated = [r for r in sessions if r["initiator"] == "other"]
        if not sessions or not other_initiated:
            # 没有对方发起的会话：无法谈"主动投入"，中性偏保守
            meta["time_low_confidence"] = True
            offhours_score = 50.0
        else:
            def _is_offhours(ts: int) -> bool:
                dt = datetime.fromtimestamp(int(ts or 0))
                return dt.hour in LATE_NIGHT_HOURS or dt.weekday() >= 5

            offhours_count = sum(
                1 for r in other_initiated if _is_offhours(r["start_time"])
            )
            offhours_rate = offhours_count / len(other_initiated)
            offhours_score = min(1.0, offhours_rate / OFFHOURS_INITIATION_FULL_RATE) * 100
            meta["offhours_initiation_rate"] = round(offhours_rate, 4)
            meta["offhours_engaged"] = offhours_rate >= OFFHOURS_INITIATION_FULL_RATE / 2

        # 深夜消息占比（对方消息）
        rows = get_db().execute(
            """
            SELECT timestamp FROM messages
            WHERE conversation_id = ? AND is_sender = 0
            """,
            (conversation_id,),
        ).fetchall()
        if rows:
            late_count = sum(
                1
                for r in rows
                if datetime.fromtimestamp(int(r["timestamp"] or 0)).hour
                in LATE_NIGHT_HOURS
            )
            late_rate = late_count / len(rows)
            late_night_score = min(1.0, late_rate / LATE_NIGHT_MESSAGE_FULL_RATE) * 100
            meta["late_night_message_rate"] = round(late_rate, 4)
        else:
            late_night_score = 50.0

        score = offhours_score * 0.55 + late_night_score * 0.45
        return max(0.0, min(100.0, score)), meta

    # ---------- 子项 3：活跃覆盖 ----------

    def _calculate_active_coverage(
        self, conversation_id: int, stats: PreprocessedStatistics
    ) -> Tuple[float, Dict[str, Any]]:
        """活跃天数覆盖（会话时间跨度内聊天的天数比例）。"""
        meta: Dict[str, Any] = {}
        day_rows = get_db().execute(
            """
            SELECT MIN(timestamp) AS first_ts, MAX(timestamp) AS last_ts
            FROM messages WHERE conversation_id = ?
            """,
            (conversation_id,),
        ).fetchone()
        coverage_score = 50.0
        if day_rows and day_rows["first_ts"] and day_rows["last_ts"]:
            span_days = max(
                1,
                (int(day_rows["last_ts"]) - int(day_rows["first_ts"])) // 86400 + 1,
            )
            coverage = min(1.0, (stats.chat_days_count or 0) / (span_days / 2))
            coverage_score = coverage * 100
            meta["active_day_coverage"] = round(
                (stats.chat_days_count or 0) / span_days, 4
            )
        return max(0.0, min(100.0, coverage_score)), meta

    # ---------- 子项 4-6：投入方向标记（engagement_metrics） ----------

    @staticmethod
    def _calculate_greeting_initiation(
        metrics: EngagementMetrics,
    ) -> Tuple[float, Dict[str, Any]]:
        """早晚安发起：对方发起占比越高分越高，无早晚安互动记中性。"""
        meta: Dict[str, Any] = {}
        other = metrics.morning_greeting_other + metrics.night_greeting_other
        total = other + metrics.morning_greeting_self + metrics.night_greeting_self
        if total <= 0:
            return 50.0, meta
        share = other / total
        meta["greeting_other_share"] = round(share, 4)
        meta["greeting_other_led"] = share >= 0.6
        return max(0.0, min(100.0, 40.0 + 60.0 * share)), meta

    @staticmethod
    def _calculate_icebreaking(
        metrics: EngagementMetrics,
    ) -> Tuple[float, Dict[str, Any]]:
        """主动破冰：>24h 沉默后恢复对话的发起归属。"""
        meta: Dict[str, Any] = {}
        if metrics.icebreak_total <= 0:
            return 50.0, meta
        share = metrics.icebreak_other / metrics.icebreak_total
        meta["icebreak_other_share"] = round(share, 4)
        meta["icebreak_other_led"] = share >= 0.6
        meta["icebreak_self_led"] = share <= 0.4
        return max(0.0, min(100.0, 40.0 + 60.0 * share)), meta

    @staticmethod
    def _calculate_community_expression(
        metrics: EngagementMetrics,
    ) -> Tuple[float, Dict[str, Any]]:
        """共同体表达：对方第一人称指称中「我们」类的占比。"""
        meta: Dict[str, Any] = {}
        ratio = metrics.community_ratio_other
        if ratio is None:
            return 50.0, meta
        meta["community_ratio_other"] = ratio
        return max(0.0, min(100.0, ratio / COMMUNITY_FULL_RATE * 100.0)), meta

    # ---------- 加分项（自态度倾向迁入） ----------

    def _calculate_bonus_scores(
        self, conversation_id: int, stats: PreprocessedStatistics
    ) -> Dict[str, float]:
        # 隐私分享：对方向我披露隐私/心声的计数（深夜隐私倾诉口径）
        privacy_bonus = min(PRIVACY_BONUS_MAX, float(stats.privacy_message_count or 0))

        # 节日互动
        holiday_bonus = self._calculate_holiday_greeting(stats)

        # 语音视频（月均通话频率，阈值随关系类型）
        multimedia_bonus = self._calculate_multimedia_usage(conversation_id, stats)

        total_bonus = min(
            TOTAL_BONUS_CAP, privacy_bonus + holiday_bonus + multimedia_bonus
        )
        return {
            "privacy_bonus": round(privacy_bonus, 2),
            "holiday_bonus": round(holiday_bonus, 2),
            "multimedia_bonus": round(multimedia_bonus, 2),
            "total_bonus": round(total_bonus, 2),
        }

    @staticmethod
    def _calculate_holiday_greeting(stats: PreprocessedStatistics) -> float:
        """节日祝福附加分（自态度倾向迁入，口径不变）。"""
        from .holiday_library import HolidayLibrary

        total_holidays = (
            len(HolidayLibrary.FIXED_HOLIDAYS)
            + len(HolidayLibrary.LUNAR_HOLIDAYS_RANGE)
            + len(HolidayLibrary.FLOATING_HOLIDAYS)
        )
        if total_holidays == 0:
            return 0.0
        frequency_ratio = (stats.holidays_sent_count or 0) / total_holidays
        return min(HOLIDAY_BONUS_MAX, frequency_ratio * HOLIDAY_BONUS_MAX * 3)

    def _calculate_multimedia_usage(
        self, conversation_id: int, stats: PreprocessedStatistics
    ) -> float:
        """语音/视频通话附加分（自态度倾向迁入，阈值随关系类型）。"""
        if (stats.total_message_count or 0) == 0:
            return 0.0
        from .relationship_context_service import RelationshipContextService

        thresholds = RelationshipContextService().get_multimedia_thresholds(
            conversation_id
        )
        total_months = max(1.0, (stats.chat_days_count or 0) / 30.0)
        video_calls_per_month = (stats.video_message_count or 0) / total_months
        voice_calls_per_month = (stats.voice_message_count or 0) / total_months
        video_bonus = min(
            VIDEO_BONUS_MAX,
            (video_calls_per_month / max(thresholds["video"], 1e-6)) * VIDEO_BONUS_MAX,
        )
        voice_bonus = min(
            VOICE_BONUS_MAX,
            (voice_calls_per_month / max(thresholds["voice"], 1e-6)) * VOICE_BONUS_MAX,
        )
        return min(VIDEO_BONUS_MAX + VOICE_BONUS_MAX, video_bonus + voice_bonus)
