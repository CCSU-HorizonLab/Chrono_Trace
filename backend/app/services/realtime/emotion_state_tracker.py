"""
情绪状态追踪器

基于滑动窗口追踪对方最近 N 条消息的情感走势，
检测 6 种触发条件并执行冷却机制，避免重复触发。
"""

import time
from collections import deque
from dataclasses import dataclass, field
from typing import Optional


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

TEXT_MESSAGE_TYPE = 1

EMOTION_SHIFT_MIN_MESSAGES = 4
EMOTION_SHIFT_BASELINE_SIZE = 3
EMOTION_SHIFT_MIN_BASELINE_POSITIVE = 2
EMOTION_SHIFT_MIN_BASELINE_INTENSITY = 0.25
EMOTION_SHIFT_LATEST_MAX_INTENSITY = -0.50
EMOTION_SHIFT_MIN_CONFIDENCE = 0.60
EMOTION_SHIFT_MIN_DELTA = 0.70
EMOTION_SHIFT_MAX_SPAN_SECONDS = 180
TOPIC_COOLING_SIGNAL_LOOKBACK = 2
TOPIC_COOLING_SIGNAL_MAX_AGE_SECONDS = 120
TOPIC_COOLING_MIN_SUBSTANTIVE_LENGTH = 10
TOPIC_COOLING_PLAN_KEYWORDS = (
    "打算",
    "准备",
    "想",
    "考虑",
    "计划",
    "看能不能",
    "不然就",
    "毕业",
    "工作",
    "留学",
    "兼职",
    "大学",
    "高中",
    "专业",
)
TOPIC_COOLING_DETAIL_KEYWORDS = (
    "高数",
    "工资",
    "生活费",
    "省钱",
    "香港",
    "游戏",
    "steam",
    "钱",
    "包",
    "买",
)
TOPIC_COOLING_QUESTION_MARKERS = (
    "?",
    "？",
    "吗",
    "么",
    "呢",
    "咋",
    "怎么",
    "为什么",
    "要不要",
)
NONVERBAL_CONTENT_MARKERS = (
    "动画表情",
    "图片",
    "表情",
    "[图片]",
)
PERFUNCTORY_MAX_SPAN_SECONDS = 180
PERFUNCTORY_MAX_CONTENT_LENGTH = 4
PERFUNCTORY_MAX_ABS_INTENSITY = 0.25
PERFUNCTORY_ACK_MARKERS = {
    "嗯",
    "嗯嗯",
    "哦",
    "哦哦",
    "好",
    "好的",
    "好吧",
    "好哦",
    "行",
    "行吧",
    "可",
    "可以",
    "收到",
    "知道了",
    "知道啦",
    "对",
    "对的",
    "ok",
    "okay",
}
PERFUNCTORY_STRONG_ACK_MARKERS = {
    "嗯",
    "嗯嗯",
    "哦",
    "哦哦",
    "好的",
    "好吧",
    "好哦",
    "收到",
    "知道了",
    "知道啦",
    "ok",
    "okay",
}
PERFUNCTORY_MIN_STRONG_ACKS = 2
DECLINE_EXACT_MARKERS = (
    "不了",
    "别了",
    "不聊了",
    "先算了",
    "还是算了",
    "就算了",
    "算了吧",
    "去不了",
    "约不了",
    "发不了",
    "安排不了",
)
DECLINE_CONTAINS_MARKERS = (
    "你去吧",
    "你们去吧",
    "我就不去了",
    "先不聊了",
    "不想去了",
)
IMPATIENCE_MARKERS = (
    "别问了",
    "别说了",
    "别搞了",
    "别催了",
    "不想聊",
    "懒得说",
    "懒得聊",
    "随便吧",
    "随便你",
    "你随便",
    "懒得理",
    "受不了你",
)
BOUNDARY_INTENTS = {"decline", "impatience"}

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
        message_type = message_data.get('message_type', message_data.get('type', TEXT_MESSAGE_TYPE))
        interaction_intent, intent_markers = self._detect_interaction_intent(content)

        # 更新滑动窗口
        self.window.append({
            'timestamp': msg_time,
            'polarity': polarity,
            'intensity': intensity,
            'confidence': confidence,
            'content_length': content_length,
            'content': content,
            'message_type': message_type,
            'interaction_intent': interaction_intent,
            'intent_markers': intent_markers,
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

        negative_streak = self._check_negative_streak(now)
        if negative_streak and self._can_trigger(negative_streak.trigger_type, now):
            self._last_trigger_times[negative_streak.trigger_type] = now
            triggers.append(negative_streak)

        emotion_shift = self._check_emotion_shift(now)
        if (
            emotion_shift
            and not negative_streak
            and self._can_trigger(emotion_shift.trigger_type, now)
        ):
            self._last_trigger_times[emotion_shift.trigger_type] = now
            triggers.append(emotion_shift)

        for check_fn in (
            self._check_perfunctory,
            self._check_positive_window,
            self._check_topic_cooling,
        ):
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
            'latest_intent': entries[-1].get('interaction_intent'),
            'recent_intents': [e.get('interaction_intent') for e in entries if e.get('interaction_intent')],
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
            latest = recent[-1]
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
                    **self._build_intent_context(latest),
                }
            )
        return None

    def _check_emotion_shift(self, now: float) -> TriggerEvent | None:
        """
        检测情绪突变：近期基线偏正面，且最新一条明确转为负面。

        这是一种“高精度预警”：
        - 至少 4 条对方消息
        - 基线取最新消息之前的最近 3 条
        - 基线里至少 2 条正面，且平均强度足够正
        - 最新消息必须明确负面且置信度足够高
        - 从基线到最新消息的时间跨度不能过长
        """
        if len(self.window) < EMOTION_SHIFT_MIN_MESSAGES:
            return None

        entries = list(self.window)
        latest = entries[-1]
        baseline = entries[-(EMOTION_SHIFT_BASELINE_SIZE + 1):-1]

        if len(baseline) < EMOTION_SHIFT_BASELINE_SIZE:
            return None

        if latest['polarity'] != -1:
            return None

        if latest.get('interaction_intent') in BOUNDARY_INTENTS:
            return None

        if latest['intensity'] > EMOTION_SHIFT_LATEST_MAX_INTENSITY:
            return None

        if latest['confidence'] < EMOTION_SHIFT_MIN_CONFIDENCE:
            return None

        positive_count = sum(1 for entry in baseline if entry['polarity'] == 1)
        if positive_count < EMOTION_SHIFT_MIN_BASELINE_POSITIVE:
            return None

        baseline_avg_polarity = (
            sum(entry['polarity'] for entry in baseline) / len(baseline)
        )
        if baseline_avg_polarity < 0.45:
            return None

        baseline_avg_intensity = (
            sum(entry['intensity'] for entry in baseline) / len(baseline)
        )
        if baseline_avg_intensity < EMOTION_SHIFT_MIN_BASELINE_INTENSITY:
            return None

        span_seconds = latest['timestamp'] - baseline[0]['timestamp']
        if span_seconds > EMOTION_SHIFT_MAX_SPAN_SECONDS:
            return None

        shift_magnitude = baseline_avg_intensity - latest['intensity']
        if shift_magnitude < EMOTION_SHIFT_MIN_DELTA:
            return None

        return TriggerEvent(
            trigger_type=TRIGGER_EMOTION_SHIFT,
            timestamp=now,
            severity=TRIGGER_SEVERITY[TRIGGER_EMOTION_SHIFT],
            context={
                'baseline_avg_intensity': round(baseline_avg_intensity, 3),
                'baseline_avg_polarity': round(baseline_avg_polarity, 3),
                'baseline_positive_count': positive_count,
                'latest_intensity': round(latest['intensity'], 3),
                'latest_confidence': round(latest['confidence'], 3),
                'shift_magnitude': round(shift_magnitude, 3),
                'window_span_seconds': round(span_seconds, 1),
            }
        )
        return None

    def _check_perfunctory(self, now: float) -> TriggerEvent | None:
        """
        检测敷衍回复：对方在短时间内连续发送 ≥3 条低信息确认式短回复
        """
        if len(self.window) < 3:
            return None

        entries = list(self.window)
        recent = entries[-3:]

        if any(entry.get('interaction_intent') in BOUNDARY_INTENTS for entry in recent):
            return None

        span_seconds = recent[-1]['timestamp'] - recent[0]['timestamp']
        if span_seconds > PERFUNCTORY_MAX_SPAN_SECONDS:
            return None

        if all(self._is_perfunctory_reply_candidate(entry) for entry in recent):
            strong_ack_count = sum(
                1 for entry in recent
                if self._is_strong_perfunctory_ack(entry)
            )
            if strong_ack_count < PERFUNCTORY_MIN_STRONG_ACKS:
                return None
            return TriggerEvent(
                trigger_type=TRIGGER_PERFUNCTORY,
                timestamp=now,
                severity=TRIGGER_SEVERITY[TRIGGER_PERFUNCTORY],
                context={
                    'lengths': [e['content_length'] for e in recent],
                    'span_seconds': round(span_seconds, 1),
                    'strong_ack_count': strong_ack_count,
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
            if self._has_recent_topic_continuation_signal():
                return None

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

    def _has_recent_topic_continuation_signal(self) -> bool:
        """
        判断最近 1-2 条对方消息是否仍在推进话题。

        设计目标偏高精度：只要最近消息看起来还在提供信息、
        提计划、提问题或给出较完整表达，就不应当被视为冷场。
        """
        recent_entries = list(self.window)[-TOPIC_COOLING_SIGNAL_LOOKBACK:]
        if not recent_entries:
            return False

        if recent_entries[-1].get('interaction_intent') in BOUNDARY_INTENTS:
            return True

        latest_ts = recent_entries[-1].get('timestamp', 0)
        return any(
            latest_ts - entry.get('timestamp', latest_ts) <= TOPIC_COOLING_SIGNAL_MAX_AGE_SECONDS
            and self._is_substantive_friend_message(entry.get('content', ''))
            for entry in recent_entries
        )

    def _is_substantive_friend_message(self, content: str) -> bool:
        """判断单条对方消息是否提供了足够的新信息或延续信号。"""
        normalized = (content or '').strip()
        if not normalized:
            return False

        compact = normalized.replace(" ", "")
        if compact in NONVERBAL_CONTENT_MARKERS:
            return False

        if any(marker in normalized for marker in TOPIC_COOLING_QUESTION_MARKERS):
            return True

        if any(keyword in normalized for keyword in TOPIC_COOLING_PLAN_KEYWORDS):
            return True

        if any(keyword in normalized for keyword in TOPIC_COOLING_DETAIL_KEYWORDS):
            return True

        if any(ch.isdigit() for ch in normalized) and len(compact) >= 4:
            return True

        alpha_count = sum(ch.isalpha() and ch.isascii() for ch in normalized)
        if alpha_count >= 2 and len(compact) >= 4:
            return True

        if len(compact) >= TOPIC_COOLING_MIN_SUBSTANTIVE_LENGTH:
            return True

        if len(compact) >= 6 and any(punct in normalized for punct in ("，", ",", "。", "！", "!", "；", ";")):
            return True

        return False

    def _is_perfunctory_reply_candidate(self, entry: dict) -> bool:
        """Conservative perfunctory detector for low-information acknowledgements only."""
        message_type = entry.get('message_type', TEXT_MESSAGE_TYPE)
        try:
            message_type = int(message_type)
        except (TypeError, ValueError):
            message_type = TEXT_MESSAGE_TYPE
        if message_type != TEXT_MESSAGE_TYPE:
            return False

        normalized = (entry.get('content') or '').strip()
        if not normalized:
            return False

        compact = normalized.replace(" ", "")
        if compact in NONVERBAL_CONTENT_MARKERS:
            return False

        if entry.get('content_length', 0) > PERFUNCTORY_MAX_CONTENT_LENGTH:
            return False

        if self._is_substantive_short_reply(normalized):
            return False

        if entry.get('polarity') != 0:
            return False

        if abs(entry.get('intensity', 0.0)) > PERFUNCTORY_MAX_ABS_INTENSITY:
            return False

        return compact.casefold() in PERFUNCTORY_ACK_MARKERS

    def _is_substantive_short_reply(self, content: str) -> bool:
        """Short messages can still be meaningful when they contain clear task or topic signals."""
        normalized = (content or '').strip()
        if not normalized:
            return False

        compact = normalized.replace(" ", "")
        if any(marker in normalized for marker in TOPIC_COOLING_QUESTION_MARKERS):
            return True

        if any(keyword in normalized for keyword in TOPIC_COOLING_PLAN_KEYWORDS):
            return True

        if any(keyword in normalized for keyword in TOPIC_COOLING_DETAIL_KEYWORDS):
            return True

        if len(compact) >= 6:
            return True

        if any(ch.isdigit() for ch in normalized):
            return True

        if any(punct in normalized for punct in ("，", ",", "。", "！", "!", "；", ";", "：", ":")):
            return True

        return False

    def _is_strong_perfunctory_ack(self, entry: dict) -> bool:
        normalized = (entry.get('content') or '').strip()
        if not normalized:
            return False
        compact = normalized.replace(" ", "")
        return compact.casefold() in PERFUNCTORY_STRONG_ACK_MARKERS

    def _build_intent_context(self, entry: dict) -> dict:
        """Attach high-value intent markers to trigger context when present."""
        interaction_intent = entry.get('interaction_intent')
        if not interaction_intent:
            return {}
        return {
            'interaction_intent': interaction_intent,
            'intent_markers': entry.get('intent_markers', []),
        }

    def _detect_interaction_intent(self, content: str) -> tuple[Optional[str], list[str]]:
        """Detect explicit decline / impatience cues to avoid reading too much into them."""
        normalized = (content or '').strip()
        if not normalized:
            return None, []

        compact = normalized.replace(" ", "")
        if compact in NONVERBAL_CONTENT_MARKERS:
            return None, []

        decline_markers: list[str] = []
        for marker in DECLINE_EXACT_MARKERS:
            if compact.startswith(marker) or compact.endswith(marker):
                decline_markers.append(marker)

        for marker in DECLINE_CONTAINS_MARKERS:
            if marker in compact:
                decline_markers.append(marker)

        if "你和" in compact and compact.endswith("去吧"):
            decline_markers.append("你和...去吧")

        if "算了" in compact and "算了一下" not in compact and "算一算" not in compact:
            decline_markers.append("算了")

        if decline_markers:
            return "decline", list(dict.fromkeys(decline_markers))

        impatience_markers = [
            marker for marker in IMPATIENCE_MARKERS
            if marker in compact
        ]
        if impatience_markers:
            return "impatience", impatience_markers

        return None, []
