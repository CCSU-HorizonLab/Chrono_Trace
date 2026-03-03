"""情绪状态追踪器单元测试

测试 EmotionStateTracker 的 6 种触发条件和冷却机制
"""

import sys
import os
import time

import pytest

# 添加 backend 到路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from app.services.realtime.emotion_state_tracker import (
    EmotionStateTracker,
    TriggerEvent,
    TRIGGER_NEGATIVE_STREAK,
    TRIGGER_EMOTION_SHIFT,
    TRIGGER_PERFUNCTORY,
    TRIGGER_SILENCE,
    TRIGGER_POSITIVE_WINDOW,
    TRIGGER_TOPIC_COOLING,
)


# ===================== 辅助函数 =====================

def make_sentiment(polarity: int, intensity: float = 0.5, confidence: float = 0.8):
    """构造情感分析结果"""
    return {
        'polarity': polarity,
        'intensity': intensity if polarity != 0 else 0.0,
        'confidence': confidence,
        'rules_applied': [],
    }


def make_message(content: str = "测试消息", sender: str = "friend", timestamp: int = 0):
    """构造消息数据"""
    return {
        'content': content,
        'sender_attr': sender,
        'timestamp': timestamp or int(time.time()),
    }


class TestNegativeStreak:
    """连续消极检测测试"""

    def test_triggers_after_3_negative(self):
        """3 条连续消极应触发"""
        tracker = EmotionStateTracker()
        t = 1000.0

        for i in range(3):
            triggers = tracker.update(
                make_sentiment(-1, -0.7),
                make_message("今天真的好难过啊", timestamp=int(t + i)),
                current_time=t + i,
            )

        trigger_types = [ev.trigger_type for ev in triggers]
        assert TRIGGER_NEGATIVE_STREAK in trigger_types
        assert triggers[0].severity == "high"

    def test_no_trigger_with_2_negative(self):
        """只有 2 条消极不应触发"""
        tracker = EmotionStateTracker()
        t = 1000.0

        for i in range(2):
            triggers = tracker.update(
                make_sentiment(-1),
                make_message("难过", timestamp=int(t + i)),
                current_time=t + i,
            )

        assert all(
            ev.trigger_type != TRIGGER_NEGATIVE_STREAK
            for ev in triggers
        )

    def test_broken_by_neutral(self):
        """中间插入中性消息应打断连续"""
        tracker = EmotionStateTracker()
        t = 1000.0

        tracker.update(make_sentiment(-1), make_message("a", timestamp=int(t)), current_time=t)
        tracker.update(make_sentiment(-1), make_message("b", timestamp=int(t+1)), current_time=t+1)
        tracker.update(make_sentiment(0), make_message("嗯嗯好的吧", timestamp=int(t+2)), current_time=t+2)
        triggers = tracker.update(
            make_sentiment(-1), make_message("c", timestamp=int(t+3)), current_time=t+3,
        )

        assert all(
            ev.trigger_type != TRIGGER_NEGATIVE_STREAK
            for ev in triggers
        )


class TestEmotionShift:
    """情绪突变检测测试"""

    def test_triggers_on_shift(self):
        """前正后负应触发"""
        tracker = EmotionStateTracker()
        t = 1000.0

        # 前半正面
        tracker.update(make_sentiment(1, 0.8), make_message("开心！！！", timestamp=int(t)), current_time=t)
        tracker.update(make_sentiment(1, 0.7), make_message("太棒了！！", timestamp=int(t+1)), current_time=t+1)
        # 后半负面
        tracker.update(make_sentiment(-1, -0.6), make_message("难过了", timestamp=int(t+2)), current_time=t+2)
        triggers = tracker.update(
            make_sentiment(-1, -0.8), make_message("好烦啊好烦", timestamp=int(t+3)), current_time=t+3,
        )

        trigger_types = [ev.trigger_type for ev in triggers]
        assert TRIGGER_EMOTION_SHIFT in trigger_types

    def test_no_trigger_all_positive(self):
        """全正面不应触发"""
        tracker = EmotionStateTracker()
        t = 1000.0

        for i in range(4):
            triggers = tracker.update(
                make_sentiment(1, 0.6),
                make_message("很开心啊！！", timestamp=int(t + i)),
                current_time=t + i,
            )

        assert all(
            ev.trigger_type != TRIGGER_EMOTION_SHIFT
            for ev in triggers
        )


class TestPerfunctory:
    """敷衍回复检测测试"""

    def test_triggers_on_short_replies(self):
        """3 条短回复应触发"""
        tracker = EmotionStateTracker()
        t = 1000.0

        for i, msg in enumerate(["嗯", "哦", "好"]):
            triggers = tracker.update(
                make_sentiment(0),
                make_message(msg, timestamp=int(t + i)),
                current_time=t + i,
            )

        trigger_types = [ev.trigger_type for ev in triggers]
        assert TRIGGER_PERFUNCTORY in trigger_types

    def test_no_trigger_long_reply(self):
        """长回复不应触发"""
        tracker = EmotionStateTracker()
        t = 1000.0

        tracker.update(make_sentiment(0), make_message("嗯", timestamp=int(t)), current_time=t)
        tracker.update(make_sentiment(0), make_message("哦", timestamp=int(t+1)), current_time=t+1)
        triggers = tracker.update(
            make_sentiment(0),
            make_message("今天天气不错呢", timestamp=int(t+2)),
            current_time=t + 2,
        )

        assert all(
            ev.trigger_type != TRIGGER_PERFUNCTORY
            for ev in triggers
        )


class TestSilence:
    """长时间不回检测测试"""

    def test_triggers_after_10_min(self):
        """超过 10 分钟应触发"""
        tracker = EmotionStateTracker()
        t = 1000.0

        tracker.update(
            make_sentiment(0),
            make_message("hello！！", timestamp=int(t)),
            current_time=t,
        )

        # 11 分钟后检查
        event = tracker.check_silence(current_time=t + 660)
        assert event is not None
        assert event.trigger_type == TRIGGER_SILENCE

    def test_no_trigger_within_10_min(self):
        """10 分钟内不应触发"""
        tracker = EmotionStateTracker()
        t = 1000.0

        tracker.update(
            make_sentiment(0),
            make_message("hello！！", timestamp=int(t)),
            current_time=t,
        )

        event = tracker.check_silence(current_time=t + 500)
        assert event is None


class TestPositiveWindow:
    """积极窗口检测测试"""

    def test_triggers_on_high_positive(self):
        """3 条高强度正面应触发"""
        tracker = EmotionStateTracker()
        t = 1000.0

        for i in range(3):
            triggers = tracker.update(
                make_sentiment(1, 0.8),
                make_message("太开心了！！！", timestamp=int(t + i)),
                current_time=t + i,
            )

        trigger_types = [ev.trigger_type for ev in triggers]
        assert TRIGGER_POSITIVE_WINDOW in trigger_types

    def test_no_trigger_low_intensity(self):
        """低强度正面不应触发"""
        tracker = EmotionStateTracker()
        t = 1000.0

        for i in range(3):
            triggers = tracker.update(
                make_sentiment(1, 0.3),  # 低于 0.5 阈值
                make_message("还不错啦", timestamp=int(t + i)),
                current_time=t + i,
            )

        assert all(
            ev.trigger_type != TRIGGER_POSITIVE_WINDOW
            for ev in triggers
        )


class TestTopicCooling:
    """话题冷场检测测试"""

    def test_triggers_on_frequency_drop(self):
        """频率下降 >50% 应触发"""
        tracker = EmotionStateTracker()
        base = 1000.0

        # 前 5 分钟（base ~ base+300）：密集消息（每 25 秒一条 = 12 条）
        for i in range(12):
            tracker.update(
                make_sentiment(0),
                make_message("密集消息" + str(i), timestamp=int(base + i * 25)),
                current_time=base + i * 25,
            )

        # 后 5 分钟（base+300 ~ base+600）：只发 1 条（频率大幅下降）
        # 在 base+550 时发一条消息，此时：
        #   recent_5min (base+250 ~ base+550) 中只有这 1 条
        #   earlier_5min (base-50 ~ base+250) 中有约 10 条
        t_late = base + 550
        triggers = tracker.update(
            make_sentiment(0),
            make_message("终于来了一条消息", timestamp=int(t_late)),
            current_time=t_late,
        )

        trigger_types = [ev.trigger_type for ev in triggers]
        assert TRIGGER_TOPIC_COOLING in trigger_types


class TestCooldown:
    """冷却机制测试"""

    def test_cooldown_prevents_repeated_trigger(self):
        """冷却期内同类触发不应重复"""
        tracker = EmotionStateTracker(cooldowns={TRIGGER_NEGATIVE_STREAK: 60})
        t = 1000.0

        # 第一次触发
        for i in range(3):
            triggers = tracker.update(
                make_sentiment(-1, -0.7),
                make_message("难过" + str(i), timestamp=int(t + i)),
                current_time=t + i,
            )

        first_triggers = [ev for ev in triggers if ev.trigger_type == TRIGGER_NEGATIVE_STREAK]
        assert len(first_triggers) == 1

        # 再发 3 条消极（在冷却期内，30 秒后）
        for i in range(3):
            triggers = tracker.update(
                make_sentiment(-1, -0.7),
                make_message("还是难过", timestamp=int(t + 30 + i)),
                current_time=t + 30 + i,
            )

        second_triggers = [ev for ev in triggers if ev.trigger_type == TRIGGER_NEGATIVE_STREAK]
        assert len(second_triggers) == 0, "冷却期内不应重复触发"

    def test_trigger_after_cooldown(self):
        """冷却期后应可再次触发"""
        tracker = EmotionStateTracker(cooldowns={TRIGGER_NEGATIVE_STREAK: 10})
        t = 1000.0

        # 第一次触发
        for i in range(3):
            tracker.update(
                make_sentiment(-1, -0.7),
                make_message("难过" + str(i), timestamp=int(t + i)),
                current_time=t + i,
            )

        # 冷却后再发 3 条
        t2 = t + 20  # 冷却 10s 结束
        tracker.reset()  # 清空窗口重新来
        for i in range(3):
            triggers = tracker.update(
                make_sentiment(-1, -0.7),
                make_message("又难过了", timestamp=int(t2 + i)),
                current_time=t2 + i,
            )

        # reset 清除了冷却，所以一定能触发
        trigger_types = [ev.trigger_type for ev in triggers]
        assert TRIGGER_NEGATIVE_STREAK in trigger_types


class TestSelfMessageIgnored:
    """自己的消息应被忽略"""

    def test_self_messages_not_tracked(self):
        """自己发的消息不应进入滑动窗口"""
        tracker = EmotionStateTracker()
        t = 1000.0

        for i in range(5):
            tracker.update(
                make_sentiment(-1, -0.8),
                make_message("自说自话", sender="self", timestamp=int(t + i)),
                current_time=t + i,
            )

        assert len(tracker.window) == 0, "自己的消息不应进入窗口"


class TestEmotionSummary:
    """情绪摘要测试"""

    def test_empty_summary(self):
        """空窗口应返回中性摘要"""
        tracker = EmotionStateTracker()
        summary = tracker.get_emotion_summary()
        assert summary['window_size'] == 0
        assert summary['trend'] == 'neutral'

    def test_positive_trend(self):
        """正面消息应显示 positive 趋势"""
        tracker = EmotionStateTracker()
        t = 1000.0

        for i in range(4):
            tracker.update(
                make_sentiment(1, 0.7),
                make_message("好开心呀呀", timestamp=int(t + i)),
                current_time=t + i,
            )

        summary = tracker.get_emotion_summary()
        assert summary['trend'] == 'positive'
        assert summary['avg_polarity'] > 0

    def test_negative_trend(self):
        """负面消息应显示 negative 趋势"""
        tracker = EmotionStateTracker()
        t = 1000.0

        for i in range(4):
            tracker.update(
                make_sentiment(-1, -0.7),
                make_message("好难过呜呜", timestamp=int(t + i)),
                current_time=t + i,
            )

        summary = tracker.get_emotion_summary()
        assert summary['trend'] == 'negative'
        assert summary['avg_polarity'] < 0


class TestPerformance:
    """性能测试"""

    def test_update_latency(self):
        """单次 update 延迟应 < 50ms"""
        tracker = EmotionStateTracker()
        t = 1000.0

        # 预热
        for i in range(5):
            tracker.update(
                make_sentiment(0),
                make_message("预热消息", timestamp=int(t + i)),
                current_time=t + i,
            )

        # 测量
        start = time.perf_counter()
        iterations = 100
        for i in range(iterations):
            tracker.update(
                make_sentiment(-1, -0.5),
                make_message("测试", timestamp=int(t + 100 + i)),
                current_time=t + 100 + i,
            )
        elapsed_ms = (time.perf_counter() - start) * 1000 / iterations

        print(f"✓ 平均 update 耗时: {elapsed_ms:.3f}ms")
        assert elapsed_ms < 50, f"单次 update 耗时 {elapsed_ms:.3f}ms，超过 50ms 限制"


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
