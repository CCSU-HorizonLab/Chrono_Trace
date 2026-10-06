"""亲密度信号维度：称谓演变、时段与投入、回复对称性。

比词性更直接的亲密关系证据：
- 称谓演变——称呼从正式（X总/X老师）走向随意（昵称/名字）是关系升温
  最直接的文本轨迹；
- 时段与投入——深夜/周末聊天占比与非工作时段的主动发起衡量"愿意为
  你占用私人时间"；
- 回复对称性——双方字数投入与表情包互动的均衡度衡量关系的相互性。

三个子项各 0-100 分，子权重 40/35/25；纯规则零模型依赖，输出结构与
情感共振率服务同构（overall_score/interpretation/sub_scores/confidence_meta）。
"""

from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import Any, Dict, List, Tuple

from ...db.connection import get_db
from .affinity_debug_logger import affinity_debug_log
from .keyword_libraries import KeywordLibraries
from .preprocessing_orchestrator import PreprocessedStatistics

logger = logging.getLogger(__name__)

# 职务/正式称谓（Tier1）：姓氏或姓名 + 称谓后缀，或泛称
FORMAL_ADDRESS_RE = re.compile(
    r"(?:[一-龥]{1,3}?(?:总|哥|姐|老师|医生|教授|工|经理|主任|局长|处长)|"
    r"老板|师傅|领导|同学|同事)",
)

# 子项权重（与文档口径一致）
SUB_WEIGHTS = {
    "address_term_evolution": 0.40,
    "time_investment": 0.35,
    "reply_asymmetry": 0.25,
}

# 深夜窗口（与 attitude_tendency_service 的深夜口径对齐：23:00-05:00）
LATE_NIGHT_HOURS = {23, 0, 1, 2, 3, 4}

# 称谓满档线：后半段 5% 的消息含昵称即触达满分档（正式称谓只作
# 演变参照与在场证据，不直接贡献亲密度——"李老师"全程出现不该高分）
ADDRESS_FULL_RATE = 0.05
# 非工作时段主动发起满档线：30% 即满分档
OFFHOURS_INITIATION_FULL_RATE = 0.30
# 深夜消息占比满档线
LATE_NIGHT_MESSAGE_FULL_RATE = 0.10
# 对方表情包频率满档线（对方每条消息里 5% 是表情包即满分档）
STICKER_FULL_RATE = 0.05


class IntimacySignalsService:
    """亲密度信号维度评分服务。"""

    def __init__(self):
        self.keyword_libraries = KeywordLibraries()

    # ---------- 编排 ----------

    def calculate_overall_intimacy(
        self,
        conversation_id: int,
        stats: PreprocessedStatistics,
        long_text_threshold: int = 100,
    ) -> Dict[str, Any]:
        address_score, address_meta = self._calculate_address_term_evolution(
            conversation_id
        )
        time_score, time_meta = self._calculate_time_investment(conversation_id, stats)
        reply_score, reply_meta = self._calculate_reply_asymmetry(
            conversation_id, long_text_threshold
        )

        sub_scores = {
            "address_term_evolution": round(address_score, 2),
            "time_investment": round(time_score, 2),
            "reply_asymmetry": round(reply_score, 2),
        }
        overall = (
            address_score * SUB_WEIGHTS["address_term_evolution"]
            + time_score * SUB_WEIGHTS["time_investment"]
            + reply_score * SUB_WEIGHTS["reply_asymmetry"]
        )
        interpretation = self._generate_interpretation(
            overall, address_meta, time_meta, reply_meta
        )
        confidence_meta: Dict[str, Any] = {}
        confidence_meta.update(address_meta)
        confidence_meta.update(time_meta)
        confidence_meta.update(reply_meta)

        affinity_debug_log(
            f"[亲密度信号] 会话 {conversation_id}: 称谓={address_score:.1f} "
            f"时段={time_score:.1f} 对称={reply_score:.1f} → 总={overall:.1f}"
        )
        return {
            "overall_score": round(max(0.0, min(100.0, overall)), 2),
            "interpretation": interpretation,
            "sub_scores": sub_scores,
            "confidence_meta": confidence_meta,
        }

    def _generate_interpretation(
        self, overall: float, address_meta: Dict, time_meta: Dict, reply_meta: Dict
    ) -> str:
        if address_meta.get("address_term_low_confidence"):
            address_note = "未检测到明显称谓变化，按中性计"
        elif address_meta.get("address_warming"):
            address_note = "称谓随时间明显变得亲近"
        elif address_meta.get("address_cooling"):
            address_note = "称谓趋于正式，或有距离感"
        else:
            address_note = "称谓保持稳定"

        if time_meta.get("time_low_confidence"):
            time_note = "会话样本不足，时段投入按中性计"
        elif time_meta.get("offhours_engaged"):
            time_note = "对方愿意在深夜/周末等私人时段投入聊天"
        else:
            time_note = "聊天主要发生在常规时段"

        if reply_meta.get("asymmetry_warning"):
            time_note += "；回复不对称明显，对方文字投入偏低"
        elif reply_meta.get("well_balanced"):
            time_note += "；双方文字投入均衡"

        if overall >= 70:
            lead = "亲密度信号较强"
        elif overall >= 45:
            lead = "亲密度信号中等"
        else:
            lead = "亲密度信号偏弱"
        return f"{lead}：{address_note}；{time_note}"

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

    # ---------- 子项 2：时段与投入 ----------

    def _calculate_time_investment(
        self, conversation_id: int, stats: PreprocessedStatistics
    ) -> Tuple[float, Dict[str, Any]]:
        meta: Dict[str, Any] = {"time_low_confidence": False}

        # 会话数据（对方发起的时段分布）
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
            late_night_score = 50.0
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

        # 活跃天数覆盖（会话时间跨度内聊天的天数比例）
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

        score = offhours_score * 0.40 + late_night_score * 0.35 + coverage_score * 0.25
        return max(0.0, min(100.0, score)), meta

    # ---------- 子项 3：回复对称性 ----------

    def _calculate_reply_asymmetry(
        self, conversation_id: int, long_text_threshold: int = 100
    ) -> Tuple[float, Dict[str, Any]]:
        meta: Dict[str, Any] = {}

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
            if int(r["is_sender"] or 0) == 0:
                other_chars = int(r["chars"] or 0)
            else:
                user_chars = int(r["chars"] or 0)
        total_chars = other_chars + user_chars
        if total_chars <= 0:
            balance_score = 50.0
            balance = 0.5
        else:
            balance = other_chars / total_chars
            # 每偏离均衡 10% 扣 8 分
            balance_score = max(0.0, 100.0 - abs(balance - 0.5) * 200 * 0.8)
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
            msgs = int(r["msgs"] or 0)
            if msgs <= 0:
                continue
            share = int(r["long_msgs"] or 0) / msgs
            if int(r["is_sender"] or 0) == 0:
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
            if int(r["is_sender"] or 0) == 0:
                other_stickers = int(r["n"] or 0)
        sticker_rate = (other_stickers / other_total) if other_total else 0.0
        sticker_score = min(1.0, sticker_rate / STICKER_FULL_RATE) * 100
        meta["other_sticker_rate"] = round(sticker_rate, 4)

        score = balance_score * 0.40 + long_diff_score * 0.35 + sticker_score * 0.25
        if balance < 0.35 and (other_share - user_share) < -0.15:
            meta["asymmetry_warning"] = True
        elif 0.4 <= balance <= 0.6:
            meta["well_balanced"] = True
        return max(0.0, min(100.0, score)), meta
