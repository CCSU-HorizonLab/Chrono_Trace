"""
情绪状态追踪器

基于滑动窗口追踪对方最近 N 条消息的情感走势，
检测 6 种触发条件并执行冷却机制，避免重复触发。
"""

import time
import logging
from collections import deque
from dataclasses import dataclass, field
from typing import Optional


logger = logging.getLogger(__name__)
@dataclass
class TriggerEvent:
    """触发事件"""
    trigger_type: str       # 触发类型标识
    timestamp: float        # 触发时间戳
    severity: str           # high / medium / low
    context: dict = field(default_factory=dict)  # 附加上下文


# 触发类型常量
TRIGGER_NEGATIVE_STREAK = "negative_streak"      # 连续消极
TRIGGER_EMOTION_SHIFT   = "emotion_shift"         # 情绪突变
TRIGGER_PERFUNCTORY     = "perfunctory"           # 敷衍回复
TRIGGER_SILENCE         = "silence"               # 长时间不回
TRIGGER_POSITIVE_WINDOW = "positive_window"       # 积极窗口
TRIGGER_TOPIC_COOLING   = "topic_cooling"         # 话题冷场

# 默认冷却时间（秒）
DEFAULT_COOLDOWNS = {
    TRIGGER_NEGATIVE_STREAK: 120,
    TRIGGER_EMOTION_SHIFT:   180,
    TRIGGER_PERFUNCTORY:     300,
    TRIGGER_SILENCE:         600,
    TRIGGER_POSITIVE_WINDOW: 300,
    TRIGGER_TOPIC_COOLING:   300,
}

# 默认严重度
TRIGGER_SEVERITY = {
    TRIGGER_NEGATIVE_STREAK: "high",
    TRIGGER_EMOTION_SHIFT:   "high",
    TRIGGER_PERFUNCTORY:     "medium",
    TRIGGER_SILENCE:         "medium",
    TRIGGER_POSITIVE_WINDOW: "low",
    TRIGGER_TOPIC_COOLING:   "medium",
}


class EmotionStateTracker:
    """
    情绪状态追踪器

    维护一个滑动窗口，追踪对方最近 N 条消息的情感结果，
    检测六种触发条件，管理冷却机制。

    使用方式:
        tracker = EmotionStateTracker()
        triggers = tracker.update(sentiment_result, message_data)
        # triggers: list[TriggerEvent]
    """

    def __init__(self, window_size: int = 5, cooldowns: dict | None = None):
        """
        初始化追踪器

        Args:
            window_size: 滑动窗口大小（只计对方消息），默认 5
            cooldowns: 自定义冷却时间（秒），可覆盖默认值
        """
        self.window_size = window_size

        # 滑动窗口：存储 (timestamp, polarity, intensity, confidence, content_length)
        self.window: deque = deque(maxlen=window_size)

        # 冷却时间配置
        self.cooldowns = {**DEFAULT_COOLDOWNS}
        if cooldowns:
            self.cooldowns.update(cooldowns)

        # 冷却状态：记录每种触发的上次触发时间戳
        self._last_trigger_times: dict[str, float] = {}

        # 消息频率追踪：记录最近消息的时间戳列表（用于话题冷场检测）
        self._message_timestamps: list[float] = []

        # 上一次收到消息的时间戳（用于 silence 检测）
        self._last_message_time: float | None = None

        # silence 是否已在当前间隔被检测过
        self._silence_detected = False

    def update(
        self,
        sentiment_result: dict,
        message_data: dict,
        current_time: float | None = None,
    ) -> list[TriggerEvent]:
        """
        更新滑动窗口并检测触发条件

        Args:
            sentiment_result: 情感分析结果
                {
                    'polarity': -1/0/1,
                    'intensity': float (-1.0 ~ 1.0),
                    'confidence': float (0 ~ 1),
                    'rules_applied': list[str]
                }
            message_data: 消息数据
                {
                    'content': str,
                    'sender_attr': str,  # 'self' / 'friend' / 'system'
                    'timestamp': int
                }
            current_time: 当前时间戳（测试注入用），默认 time.time()

        Returns:
            触发的事件列表（可能为空）
        """
        now = current_time or time.time()

        # 只追踪对方消息
        if message_data.get('sender_attr') != 'friend':
            return []

        # 提取数据
        polarity = sentiment_result.get('polarity', 0)
        intensity = sentiment_result.get('intensity', 0.0)
        confidence = sentiment_result.get('confidence', 0.0)
        content = message_data.get('content', '')
        content_length = len(content.strip()) if content else 0
        msg_time = float(message_data.get('timestamp', now))

        # 更新滑动窗口
        self.window.append({
            'timestamp': msg_time,
            'polarity': polarity,
            'intensity': intensity,
            'confidence': confidence,
            'content_length': content_length,
        })

        # 更新消息频率追踪（保留最近 10 分钟的时间戳）
        self._message_timestamps.append(msg_time)
        cutoff = msg_time - 600  # 10 分钟
        self._message_timestamps = [
            ts for ts in self._message_timestamps if ts > cutoff
        ]

        # 更新最后消息时间
        self._last_message_time = msg_time
        self._silence_detected = False  # 收到新消息，重置 silence 标记

        # 执行所有检测
        triggers: list[TriggerEvent] = []

        checks = [
            self._check_negative_streak,
            self._check_emotion_shift,
            self._check_perfunctory,
            self._check_positive_window,
            self._check_topic_cooling,
        ]

        for check_fn in checks:
            event = check_fn(now)
            if event and self._can_trigger(event.trigger_type, now):
                self._last_trigger_times[event.trigger_type] = now
                triggers.append(event)

        return triggers

    def check_silence(self, current_time: float | None = None) -> TriggerEvent | None:
        """
        检测长时间未收到消息（由轮询循环周期性调用）

        Args:
            current_time: 当前时间戳

        Returns:
            TriggerEvent 或 None
        """
        now = current_time or time.time()

        if self._last_message_time is None:
            return None

        if self._silence_detected:
            return None

        elapsed = now - self._last_message_time
        if elapsed > 600:  # 10 分钟
            if self._can_trigger(TRIGGER_SILENCE, now):
                self._silence_detected = True
                self._last_trigger_times[TRIGGER_SILENCE] = now
                return TriggerEvent(
                    trigger_type=TRIGGER_SILENCE,
                    timestamp=now,
                    severity=TRIGGER_SEVERITY[TRIGGER_SILENCE],
                    context={
                        'silent_seconds': round(elapsed, 1),
                        'last_message_time': self._last_message_time,
                    }
                )
        return None

    def get_emotion_summary(self) -> dict:
        """
        获取当前情绪态势摘要（供前端展示用）

        Returns:
            {
                'window_size': int,         # 当前窗口中消息数
                'avg_polarity': float,      # 平均极性
                'avg_intensity': float,     # 平均强度
                'trend': str,               # 'positive' / 'neutral' / 'negative'
                'recent_polarities': list,  # 最近极性序列
            }
        """
        if not self.window:
            return {
                'window_size': 0,
                'avg_polarity': 0.0,
                'avg_intensity': 0.0,
                'trend': 'neutral',
                'recent_polarities': [],
            }

        entries = list(self.window)
        n = len(entries)

        # 加权平均（越近权重越大）
        weights = [(i + 1) for i in range(n)]
        total_weight = sum(weights)

        avg_polarity = sum(
            e['polarity'] * w for e, w in zip(entries, weights)
        ) / total_weight

        avg_intensity = sum(
            e['intensity'] * w for e, w in zip(entries, weights)
        ) / total_weight

        # 判断趋势
        if avg_polarity > 0.3:
            trend = 'positive'
        elif avg_polarity < -0.3:
            trend = 'negative'
        else:
            trend = 'neutral'

        return {
            'window_size': n,
            'avg_polarity': round(avg_polarity, 3),
            'avg_intensity': round(avg_intensity, 3),
            'trend': trend,
            'recent_polarities': [e['polarity'] for e in entries],
        }

    def reset(self):
        """重置追踪器状态"""
        self.window.clear()
        self._last_trigger_times.clear()
        self._message_timestamps.clear()
        self._last_message_time = None
        self._silence_detected = False

    # ===================== 内部检测方法 =====================

    def _can_trigger(self, trigger_type: str, now: float) -> bool:
        """检查某触发类型是否在冷却期外"""
        last_time = self._last_trigger_times.get(trigger_type)
        if last_time is None:
            return True
        cooldown = self.cooldowns.get(trigger_type, 120)
        return (now - last_time) >= cooldown

    def _check_negative_streak(self, now: float) -> TriggerEvent | None:
        """
        检测连续消极：对方连续 ≥3 条 polarity == -1
        """
        if len(self.window) < 3:
            return None

        entries = list(self.window)
        # 检查最近 3 条是否都是消极
        recent = entries[-3:]
        if all(e['polarity'] == -1 for e in recent):
            return TriggerEvent(
                trigger_type=TRIGGER_NEGATIVE_STREAK,
                timestamp=now,
                severity=TRIGGER_SEVERITY[TRIGGER_NEGATIVE_STREAK],
                context={
                    'streak_count': sum(
                        1 for e in reversed(entries)
                        if e['polarity'] == -1
                    ),
                    'avg_intensity': round(
                        sum(e['intensity'] for e in recent) / 3, 3
                    ),
                }
            )
        return None

    def _check_emotion_shift(self, now: float) -> TriggerEvent | None:
        """
        检测情绪突变：窗口前半正面、后半负面
        需要至少 4 条消息
        """
        if len(self.window) < 4:
            return None

        entries = list(self.window)
        mid = len(entries) // 2
        first_half = entries[:mid]
        second_half = entries[mid:]

        # 前半平均极性 > 0 且后半平均极性 < 0
        first_avg = sum(e['polarity'] for e in first_half) / len(first_half)
        second_avg = sum(e['polarity'] for e in second_half) / len(second_half)

        if first_avg > 0 and second_avg < 0:
            return TriggerEvent(
                trigger_type=TRIGGER_EMOTION_SHIFT,
                timestamp=now,
                severity=TRIGGER_SEVERITY[TRIGGER_EMOTION_SHIFT],
                context={
                    'first_half_avg': round(first_avg, 3),
                    'second_half_avg': round(second_avg, 3),
                    'shift_magnitude': round(first_avg - second_avg, 3),
                }
            )
        return None

    def _check_perfunctory(self, now: float) -> TriggerEvent | None:
        """
        检测敷衍回复：对方连续 ≥3 条消息长度 < 5 字
        """
        if len(self.window) < 3:
            return None

        entries = list(self.window)
        recent = entries[-3:]

        if all(e['content_length'] < 5 for e in recent):
            return TriggerEvent(
                trigger_type=TRIGGER_PERFUNCTORY,
                timestamp=now,
                severity=TRIGGER_SEVERITY[TRIGGER_PERFUNCTORY],
                context={
                    'lengths': [e['content_length'] for e in recent],
                }
            )
        return None

    def _check_positive_window(self, now: float) -> TriggerEvent | None:
        """
        检测积极窗口：对方连续 ≥3 条正面且强度 > 0.5
        """
        if len(self.window) < 3:
            return None

        entries = list(self.window)
        recent = entries[-3:]

        if all(
            e['polarity'] == 1 and e['intensity'] > 0.5
            for e in recent
        ):
            return TriggerEvent(
                trigger_type=TRIGGER_POSITIVE_WINDOW,
                timestamp=now,
                severity=TRIGGER_SEVERITY[TRIGGER_POSITIVE_WINDOW],
                context={
                    'avg_intensity': round(
                        sum(e['intensity'] for e in recent) / 3, 3
                    ),
                }
            )
        return None

    def _check_topic_cooling(self, now: float) -> TriggerEvent | None:
        """
        检测话题冷场：最近 5 分钟消息频率下降 > 50%（与前 5 分钟相比）
        """
        if len(self._message_timestamps) < 4:
            return None

        # 当前消息的时间为基准
        ref_time = self._message_timestamps[-1]

        # 最近 5 分钟
        recent_cutoff = ref_time - 300
        # 前 5 分钟
        earlier_start = ref_time - 600
        earlier_end = recent_cutoff

        recent_count = sum(
            1 for ts in self._message_timestamps
            if ts > recent_cutoff
        )
        earlier_count = sum(
            1 for ts in self._message_timestamps
            if earlier_start < ts <= earlier_end
        )

        # 需要前 5 分钟有足够的消息作为基准
        if earlier_count < 2:
            return None

        # 频率下降超过 50%
        if recent_count < earlier_count * 0.5:
            return TriggerEvent(
                trigger_type=TRIGGER_TOPIC_COOLING,
                timestamp=now,
                severity=TRIGGER_SEVERITY[TRIGGER_TOPIC_COOLING],
                context={
                    'recent_5min_count': recent_count,
                    'earlier_5min_count': earlier_count,
                    'drop_ratio': round(
                        1 - recent_count / earlier_count, 3
                    ) if earlier_count > 0 else 1.0,
                }
            )
        return None
