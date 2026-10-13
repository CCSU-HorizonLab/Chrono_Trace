"""会话投入特征统计 — 一遍扫描产出双向互动的基础指标。

为互动投入 / 情感共鸣 / 亲近信号维度与风险预警提供共用数据：
全部为纯计算，不落库、不依赖模型（情绪极性直接读 sentiment_cache，
缺缓存时极性计数缺席，其余指标不受影响）。

指标命名沿用本项目语言（调研原始词 → 定名）：
- 连发未回（轰炸检测）：同方连发 >= 3 条文本未获对方任何回应
- 长时未回应（已读不回）：跨方相邻消息间隔 > 2h 且不跨深夜时段
- 主动破冰（修复尝试）：> 24h 沉默后恢复对话的发起方
- 早晚安发起：早晚安词表按「天 × 方向」去重计数
- 共同体表达（代词比）：「我们/咱们」类占第一人称指称的比例
- 敷衍回复：复用 realtime.sentiment_rules.is_perfunctory
- 撤回频次：type=10000 系统消息按「你撤回/昵称撤回」分方
- 日消息量波动（消息密度 CV）：活跃日日量的变异系数
"""

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

from ...db.connection import get_db

logger = logging.getLogger(__name__)

# ===== 阈值常量（不进用户配置，避免扩大 config fingerprint 面） =====
BURST_MIN_MESSAGES = 3          # 连发未回的最少连发条数
LONG_GAP_SECONDS = 2 * 3600     # 长时未回应判定间隔
ICEBREAK_GAP_SECONDS = 24 * 3600  # 主动破冰判定间隔
DEEP_NIGHT_HOURS = (2, 3, 4, 5, 6)  # 深夜时段：间隔覆盖其中任一小时视为睡眠豁免
_MAX_SLEEP_CHECK_DAYS = 10      # 超过该天数不再逐小时检查（按睡眠/离开豁免处理）

# 早晚安判定：问候起始词 + 短长度约束（问候语不会长，避免「早知道」「晚饭」误命中）
_MORNING_PREFIXES = ("早安", "早上好", "早呀", "早啊")
_MORNING_EXACT = ("早", "早~", "早！", "早!")
_NIGHT_PREFIXES = ("晚安", "睡吧", "早点睡", "好梦")
_GREETING_MAX_LEN = 8


def _is_morning_greeting(text: str) -> bool:
    if len(text) > _GREETING_MAX_LEN:
        return False
    return text in _MORNING_EXACT or text.startswith(_MORNING_PREFIXES)


def _is_night_greeting(text: str) -> bool:
    if len(text) > _GREETING_MAX_LEN:
        return False
    return text.startswith(_NIGHT_PREFIXES)

# 共同体指称与第一人称单数（「我」后接「们」不计单数）
_WE_PATTERN = re.compile(r"我们|咱们|咱俩|我俩|两个人")
_I_PATTERN = re.compile(r"我(?!们)")

# 撤回系统消息（type=10000）内容模式，参考 realtime/recent_window.py
_REVOKE_PATTERN = re.compile(r"^(你|.{1,30}?)撤回了一条(新)?消息")


def _decode(content) -> str:
    """messages.content 可能是 BLOB，统一按 UTF-8 容错解码。"""
    if content is None:
        return ""
    if isinstance(content, bytes):
        return content.decode("utf-8", errors="replace")
    return str(content)


def gap_spans_deep_night(t1: int, t2: int) -> bool:
    """判断 [t1, t2] 间隔是否覆盖深夜时段（视为睡眠/离开，不计长时未回应）。"""
    if t2 - t1 > _MAX_SLEEP_CHECK_DAYS * 86400:
        return True
    day = datetime.fromtimestamp(t1).replace(hour=0, minute=0, second=0, microsecond=0)
    end = datetime.fromtimestamp(t2)
    while day <= end:
        for hour in DEEP_NIGHT_HOURS:
            ts = int(day.replace(hour=hour).timestamp())
            if t1 < ts < t2:
                return True
        day += timedelta(days=1)
    return False


@dataclass
class EngagementMetrics:
    """会话级投入特征（self=本人，other=对方）。"""

    # 文本消息规模
    text_message_count: int = 0
    self_text_count: int = 0
    other_text_count: int = 0
    first_ts: int = 0
    last_ts: int = 0

    # 连发未回事件数（同方连发 >= 3 条未获回应）
    burst_unanswered_self: int = 0
    burst_unanswered_other: int = 0

    # 长时未回应事件数（> 2h 且不跨深夜）
    long_unanswered_self: int = 0
    long_unanswered_other: int = 0

    # 主动破冰（> 24h 沉默后恢复；发起方计数）
    icebreak_total: int = 0
    icebreak_self: int = 0
    icebreak_other: int = 0

    # 早晚安发起（天 × 方向去重）
    morning_greeting_self: int = 0
    morning_greeting_other: int = 0
    night_greeting_self: int = 0
    night_greeting_other: int = 0

    # 共同体表达比例（0-1；无第一人称指称时为 None）
    community_ratio_self: Optional[float] = None
    community_ratio_other: Optional[float] = None

    # 敷衍回复（计数 + 占本方文本比例）
    perfunctory_self: int = 0
    perfunctory_other: int = 0
    perfunctory_rate_self: float = 0.0
    perfunctory_rate_other: float = 0.0

    # 撤回频次（系统消息解析）
    revoke_self: int = 0
    revoke_other: int = 0

    # 日消息量（活跃日 → 条数）与变异系数
    daily_counts: Dict[str, int] = field(default_factory=dict)
    daily_cv_active: Optional[float] = None

    # 情绪极性计数（sentiment_cache 缺席时保持 0）
    positive_self: int = 0
    negative_self: int = 0
    positive_other: int = 0
    negative_other: int = 0

    @property
    def span_days(self) -> float:
        if self.last_ts <= self.first_ts:
            return 0.0
        return (self.last_ts - self.first_ts) / 86400.0

    def to_dict(self) -> Dict[str, object]:
        """扁平化输出（LLM 统计概要注入与调试用）。"""
        return {
            "text_message_count": self.text_message_count,
            "self_text_count": self.self_text_count,
            "other_text_count": self.other_text_count,
            "burst_unanswered": {
                "self": self.burst_unanswered_self,
                "other": self.burst_unanswered_other,
            },
            "long_unanswered": {
                "self": self.long_unanswered_self,
                "other": self.long_unanswered_other,
            },
            "icebreak": {
                "total": self.icebreak_total,
                "self": self.icebreak_self,
                "other": self.icebreak_other,
            },
            "morning_greeting": {
                "self": self.morning_greeting_self,
                "other": self.morning_greeting_other,
            },
            "night_greeting": {
                "self": self.night_greeting_self,
                "other": self.night_greeting_other,
            },
            "community_ratio": {
                "self": self.community_ratio_self,
                "other": self.community_ratio_other,
            },
            "perfunctory": {
                "self": {"count": self.perfunctory_self, "rate": round(self.perfunctory_rate_self, 4)},
                "other": {"count": self.perfunctory_other, "rate": round(self.perfunctory_rate_other, 4)},
            },
            "revoke": {"self": self.revoke_self, "other": self.revoke_other},
            "daily_cv_active": self.daily_cv_active,
            "polarity": {
                "positive": {"self": self.positive_self, "other": self.positive_other},
                "negative": {"self": self.negative_self, "other": self.negative_other},
            },
        }


class EngagementMetricsService:
    """会话投入特征计算（每次分析现算，天然增量安全）。"""

    def compute(self, conversation_id: int) -> EngagementMetrics:
        metrics = EngagementMetrics()
        rows = self._load_text_messages(conversation_id)
        self._scan_messages(rows, metrics)
        self._count_revokes(conversation_id, metrics)
        self._count_polarity(conversation_id, metrics)
        metrics.daily_cv_active = self._active_day_cv(metrics.daily_counts)
        logger.info(
            f"会话投入特征计算完成: {metrics.text_message_count} 条文本 "
            f"(会话 {conversation_id})"
        )
        return metrics

    # ========================================
    # 数据加载
    # ========================================

    def _load_text_messages(self, conversation_id: int) -> List[Tuple[int, str, int]]:
        """拉取会话全部文本消息（is_sender, content, timestamp），按时间升序。"""
        try:
            cursor = get_db().execute(
                """
                SELECT is_sender, content, timestamp
                FROM messages
                WHERE conversation_id = ? AND message_type = 1
                ORDER BY timestamp ASC
                """,
                (conversation_id,),
            )
            return [
                (int(row[0] or 0), _decode(row[1]).strip(), int(row[2] or 0))
                for row in cursor.fetchall()
                if _decode(row[1]).strip()
            ]
        except Exception as e:
            logger.error(f"加载文本消息失败: {e}")
            return []

    def _count_revokes(self, conversation_id: int, metrics: EngagementMetrics) -> None:
        """撤回系统消息计数（type=10000，「你撤回」为本方，带昵称为对方）。"""
        try:
            cursor = get_db().execute(
                """
                SELECT content FROM messages
                WHERE conversation_id = ? AND message_type = 10000
                """,
                (conversation_id,),
            )
            for (content,) in cursor.fetchall():
                text = _decode(content)
                match = _REVOKE_PATTERN.match(text)
                if not match:
                    continue
                if match.group(1) == "你":
                    metrics.revoke_self += 1
                else:
                    metrics.revoke_other += 1
        except Exception as e:
            logger.warning(f"撤回计数失败: {e}")

    def _count_polarity(self, conversation_id: int, metrics: EngagementMetrics) -> None:
        """按方向统计正/负极性消息数（直读 sentiment_cache）。"""
        try:
            cursor = get_db().execute(
                """
                SELECT m.is_sender, sc.polarity, COUNT(*)
                FROM sentiment_cache sc
                JOIN messages m ON sc.message_id = m.id
                WHERE m.conversation_id = ?
                GROUP BY m.is_sender, sc.polarity
                """,
                (conversation_id,),
            )
            for is_sender, polarity, count in cursor.fetchall():
                if polarity == 1:
                    if is_sender:
                        metrics.positive_self += count
                    else:
                        metrics.positive_other += count
                elif polarity == -1:
                    if is_sender:
                        metrics.negative_self += count
                    else:
                        metrics.negative_other += count
        except Exception as e:
            logger.warning(f"极性计数失败: {e}")

    # ========================================
    # 主扫描
    # ========================================

    def _scan_messages(
        self, rows: List[Tuple[int, str, int]], metrics: EngagementMetrics
    ) -> None:
        from ..realtime.sentiment_rules import is_perfunctory

        metrics.text_message_count = len(rows)
        if not rows:
            return
        metrics.first_ts = rows[0][2]
        metrics.last_ts = rows[-1][2]

        # 第一人称指称累计（共同体表达）
        we_counts = {0: 0, 1: 0}   # key: is_sender
        i_counts = {0: 0, 1: 0}
        # 敷衍计数
        perfunctory_counts = {0: 0, 1: 0}
        # 早晚安（天 × 方向去重）
        greeted: set = set()

        prev_sender: Optional[int] = None
        prev_ts = 0
        run_count = 0   # 当前同方连发条数

        for is_sender, content, ts in rows:
            if is_sender:
                metrics.self_text_count += 1
            else:
                metrics.other_text_count += 1

            # --- 连发未回 / 长时未回应 / 主动破冰 ---
            if is_sender != prev_sender and prev_sender is not None:
                # 方向切换：结算上一方连发
                if run_count >= BURST_MIN_MESSAGES:
                    if prev_sender:
                        metrics.burst_unanswered_self += 1
                    else:
                        metrics.burst_unanswered_other += 1
                run_count = 0

                gap = ts - prev_ts
                if gap > ICEBREAK_GAP_SECONDS:
                    metrics.icebreak_total += 1
                    if is_sender:
                        metrics.icebreak_self += 1
                    else:
                        metrics.icebreak_other += 1
                elif gap > LONG_GAP_SECONDS and not gap_spans_deep_night(prev_ts, ts):
                    # 恢复方此前长时间未回应
                    if is_sender:
                        metrics.long_unanswered_self += 1
                    else:
                        metrics.long_unanswered_other += 1

            # 同方连发期间中间消息不重复触发展开结算
            run_count += 1
            prev_sender = is_sender
            prev_ts = ts

            # --- 文本类指标 ---
            we_counts[is_sender] += len(_WE_PATTERN.findall(content))
            i_counts[is_sender] += len(_I_PATTERN.findall(content))
            if is_perfunctory(content):
                perfunctory_counts[is_sender] += 1

            day = datetime.fromtimestamp(ts).strftime("%Y-%m-%d")
            metrics.daily_counts[day] = metrics.daily_counts.get(day, 0) + 1
            if (day, is_sender, "m") not in greeted and _is_morning_greeting(content):
                greeted.add((day, is_sender, "m"))
                if is_sender:
                    metrics.morning_greeting_self += 1
                else:
                    metrics.morning_greeting_other += 1
            elif (day, is_sender, "n") not in greeted and _is_night_greeting(content):
                greeted.add((day, is_sender, "n"))
                if is_sender:
                    metrics.night_greeting_self += 1
                else:
                    metrics.night_greeting_other += 1

        # 尾部连发（对话结束在连发上）：只结算不区分是否获得回应，仍按未回处理
        if run_count >= BURST_MIN_MESSAGES:
            if prev_sender:
                metrics.burst_unanswered_self += 1
            else:
                metrics.burst_unanswered_other += 1

        for side, key_self in ((1, "self"), (0, "other")):
            we, single = we_counts[side], i_counts[side]
            total_refs = we + single
            ratio = we / total_refs if total_refs > 0 else None
            if key_self == "self":
                metrics.community_ratio_self = (
                    round(ratio, 4) if ratio is not None else None
                )
            else:
                metrics.community_ratio_other = (
                    round(ratio, 4) if ratio is not None else None
                )

        total_side = {1: metrics.self_text_count, 0: metrics.other_text_count}
        metrics.perfunctory_self = perfunctory_counts[1]
        metrics.perfunctory_other = perfunctory_counts[0]
        metrics.perfunctory_rate_self = (
            perfunctory_counts[1] / total_side[1] if total_side[1] else 0.0
        )
        metrics.perfunctory_rate_other = (
            perfunctory_counts[0] / total_side[0] if total_side[0] else 0.0
        )

    @staticmethod
    def _active_day_cv(daily_counts: Dict[str, int]) -> Optional[float]:
        """活跃日日量的变异系数（std/mean，总体口径）；活跃日不足 2 天为 None。"""
        if len(daily_counts) < 2:
            return None
        values = list(daily_counts.values())
        mean = sum(values) / len(values)
        if mean <= 0:
            return None
        variance = sum((v - mean) ** 2 for v in values) / len(values)
        return round((variance ** 0.5) / mean, 4)
