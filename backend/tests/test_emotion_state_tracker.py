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


def make_message(
    content: str = "测试消息",
    sender: str = "friend",
    timestamp: int = 0,
    message_type: int = 1,
):
    """构造消息数据"""
    return {
        'content': content,
        'sender_attr': sender,
        'timestamp': timestamp or int(time.time()),
        'message_type': message_type,
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

    def test_negative_streak_keeps_decline_intent_in_context(self):
        """连续消极若伴随明确拒绝，应保留 intent 供下游建议收敛语气"""
        tracker = EmotionStateTracker()
        t = 1000.0

        tracker.update(make_sentiment(-1, -0.8), make_message("烦", timestamp=int(t)), current_time=t)
        tracker.update(make_sentiment(-1, -0.7), make_message("不想搞了", timestamp=int(t+1)), current_time=t+1)
        triggers = tracker.update(
            make_sentiment(-1, -0.8),
            make_message("算了吧", timestamp=int(t+2)),
            current_time=t+2,
        )

        streak_events = [ev for ev in triggers if ev.trigger_type == TRIGGER_NEGATIVE_STREAK]
        assert len(streak_events) == 1
        assert streak_events[0].context["interaction_intent"] == "decline"


class TestEmotionShift:
    """情绪突变检测测试"""

    def test_triggers_on_shift(self):
        """近期基线偏正，最新一条明确转负应触发"""
        tracker = EmotionStateTracker()
        t = 1000.0

        tracker.update(make_sentiment(1, 0.8), make_message("开心！！！", timestamp=int(t)), current_time=t)
        tracker.update(make_sentiment(1, 0.7), make_message("太棒了！！", timestamp=int(t+1)), current_time=t+1)
        tracker.update(make_sentiment(1, 0.5), make_message("今天还挺顺", timestamp=int(t+2)), current_time=t+2)
        triggers = tracker.update(
            make_sentiment(-1, -0.8, confidence=0.92),
            make_message("好烦啊好烦", timestamp=int(t+3)),
            current_time=t+3,
        )

        shift_events = [ev for ev in triggers if ev.trigger_type == TRIGGER_EMOTION_SHIFT]
        assert len(shift_events) == 1
        assert shift_events[0].context["baseline_positive_count"] == 3
        assert shift_events[0].context["latest_intensity"] == -0.8

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

    def test_no_trigger_when_latest_message_is_neutral(self):
        """最新消息是中性/表情时不应误判为情绪突变"""
        tracker = EmotionStateTracker()
        t = 1000.0

        tracker.update(make_sentiment(1, 0.8), make_message("哈哈哈哈", timestamp=int(t)), current_time=t)
        tracker.update(make_sentiment(1, 0.7), make_message("今天真不错", timestamp=int(t+1)), current_time=t+1)
        tracker.update(make_sentiment(1, 0.4), make_message("还挺开心", timestamp=int(t+2)), current_time=t+2)
        triggers = tracker.update(
            make_sentiment(0, confidence=0.9),
            make_message("动画表情", timestamp=int(t+3)),
            current_time=t+3,
        )

        assert all(
            ev.trigger_type != TRIGGER_EMOTION_SHIFT
            for ev in triggers
        )

    def test_no_trigger_when_latest_confidence_is_low(self):
        """最新负面消息置信度过低时不应触发"""
        tracker = EmotionStateTracker()
        t = 1000.0

        tracker.update(make_sentiment(1, 0.9), make_message("爽", timestamp=int(t)), current_time=t)
        tracker.update(make_sentiment(1, 0.7), make_message("很开心", timestamp=int(t+1)), current_time=t+1)
        tracker.update(make_sentiment(1, 0.4), make_message("还不错", timestamp=int(t+2)), current_time=t+2)
        triggers = tracker.update(
            make_sentiment(-1, -0.8, confidence=0.45),
            make_message("烦死了", timestamp=int(t+3)),
            current_time=t+3,
        )

        assert all(
            ev.trigger_type != TRIGGER_EMOTION_SHIFT
            for ev in triggers
        )

    def test_no_trigger_when_latest_negative_is_too_mild(self):
        """轻微负面应降级为观察，不触发情绪突变建议"""
        tracker = EmotionStateTracker()
        t = 1000.0

        tracker.update(make_sentiment(1, 0.9), make_message("今天真开心", timestamp=int(t)), current_time=t)
        tracker.update(make_sentiment(1, 0.7), make_message("事情很顺", timestamp=int(t+1)), current_time=t+1)
        tracker.update(make_sentiment(1, 0.5), make_message("还不错", timestamp=int(t+2)), current_time=t+2)
        triggers = tracker.update(
            make_sentiment(-1, -0.45, confidence=0.95),
            make_message("有点烦", timestamp=int(t+3)),
            current_time=t+3,
        )

        assert all(
            ev.trigger_type != TRIGGER_EMOTION_SHIFT
            for ev in triggers
        )

    def test_no_trigger_when_latest_message_is_decline_boundary(self):
        """明确拒绝/收口更像边界感，不应误判为情绪坠落"""
        tracker = EmotionStateTracker()
        t = 1000.0

        tracker.update(make_sentiment(1, 0.8), make_message("哈哈还挺开心", timestamp=int(t)), current_time=t)
        tracker.update(make_sentiment(1, 0.7), make_message("今天挺顺", timestamp=int(t+1)), current_time=t+1)
        tracker.update(make_sentiment(1, 0.6), make_message("感觉不错", timestamp=int(t+2)), current_time=t+2)
        triggers = tracker.update(
            make_sentiment(-1, -0.8, confidence=0.95),
            make_message("不了 你和wwj去吧", timestamp=int(t+3)),
            current_time=t+3,
        )

        assert all(
            ev.trigger_type != TRIGGER_EMOTION_SHIFT
            for ev in triggers
        )
        summary = tracker.get_emotion_summary()
        assert summary["latest_intent"] == "decline"

    def test_no_trigger_when_reference_is_too_old(self):
        """跨度过长时不应用很久以前的正面情绪做参照"""
        tracker = EmotionStateTracker()
        t = 1000.0

        tracker.update(make_sentiment(1, 0.8), make_message("开心", timestamp=int(t)), current_time=t)
        tracker.update(make_sentiment(1, 0.8), make_message("很爽", timestamp=int(t+30)), current_time=t+30)
        tracker.update(make_sentiment(1, 0.5), make_message("还行", timestamp=int(t+60)), current_time=t+60)
        triggers = tracker.update(
            make_sentiment(-1, -0.9, confidence=0.95),
            make_message("突然好烦", timestamp=int(t+250)),
            current_time=t+250,
        )

        assert all(
            ev.trigger_type != TRIGGER_EMOTION_SHIFT
            for ev in triggers
        )

    def test_negative_streak_suppresses_emotion_shift_when_both_exist(self, monkeypatch):
        """如果两者同时命中，应优先保留连续消极"""
        tracker = EmotionStateTracker()
        t = 1000.0

        monkeypatch.setattr(
            tracker,
            "_check_negative_streak",
            lambda now: TriggerEvent(TRIGGER_NEGATIVE_STREAK, now, "high"),
        )
        monkeypatch.setattr(
            tracker,
            "_check_emotion_shift",
            lambda now: TriggerEvent(TRIGGER_EMOTION_SHIFT, now, "high"),
        )
        monkeypatch.setattr(tracker, "_check_perfunctory", lambda now: None)
        monkeypatch.setattr(tracker, "_check_positive_window", lambda now: None)
        monkeypatch.setattr(tracker, "_check_topic_cooling", lambda now: None)

        triggers = tracker.update(
            make_sentiment(-1, -0.8),
            make_message("烦", timestamp=int(t)),
            current_time=t,
        )

        assert [ev.trigger_type for ev in triggers] == [TRIGGER_NEGATIVE_STREAK]


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

    def test_no_trigger_when_short_replies_are_explicit_boundary(self):
        """明确拒绝/收口不应被误判成单纯敷衍"""
        tracker = EmotionStateTracker()
        t = 1000.0

        tracker.update(make_sentiment(0), make_message("嗯", timestamp=int(t)), current_time=t)
        tracker.update(make_sentiment(0), make_message("不了", timestamp=int(t+1)), current_time=t+1)
        triggers = tracker.update(
            make_sentiment(0),
            make_message("算了吧", timestamp=int(t+2)),
            current_time=t + 2,
        )

        assert all(
            ev.trigger_type != TRIGGER_PERFUNCTORY
            for ev in triggers
        )

    def test_no_trigger_on_weak_agreement_cluster(self):
        """只有弱确认词时先观察，避免把正常顺手确认判成敷衍"""
        tracker = EmotionStateTracker()
        t = 1000.0

        for i, msg in enumerate(["行", "好", "可以"]):
            triggers = tracker.update(
                make_sentiment(0),
                make_message(msg, timestamp=int(t + i)),
                current_time=t + i,
            )

        assert all(
            ev.trigger_type != TRIGGER_PERFUNCTORY
            for ev in triggers
        )

    def test_no_trigger_when_latest_short_reply_is_non_text(self):
        """图片/语音等非文本短消息不应拼成 perfunctory"""
        tracker = EmotionStateTracker()
        t = 1000.0

        tracker.update(make_sentiment(0), make_message("嗯", timestamp=int(t)), current_time=t)
        tracker.update(make_sentiment(0), make_message("哦", timestamp=int(t+1)), current_time=t+1)
        triggers = tracker.update(
            make_sentiment(0),
            make_message("好", timestamp=int(t+2), message_type=34),
            current_time=t + 2,
        )

        assert all(
            ev.trigger_type != TRIGGER_PERFUNCTORY
            for ev in triggers
        )

    def test_no_trigger_when_short_replies_span_too_long(self):
        """跨时段零散确认不应被拼成一次敷衍窗口"""
        tracker = EmotionStateTracker()
        t = 1000.0

        tracker.update(make_sentiment(0), make_message("嗯", timestamp=int(t)), current_time=t)
        tracker.update(make_sentiment(0), make_message("哦", timestamp=int(t+120)), current_time=t+120)
        triggers = tracker.update(
            make_sentiment(0),
            make_message("好", timestamp=int(t+240)),
            current_time=t + 240,
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

    def test_no_trigger_when_latest_message_contains_new_plan(self):
        """即使频率变慢，只要对方还在给新计划，就不应判为冷场"""
        tracker = EmotionStateTracker()
        base = 1000.0

        for i in range(12):
            tracker.update(
                make_sentiment(0),
                make_message("密集消息" + str(i), timestamp=int(base + i * 25)),
                current_time=base + i * 25,
            )

        t_late = base + 550
        triggers = tracker.update(
            make_sentiment(0),
            make_message("看能不能去香港留学", timestamp=int(t_late)),
            current_time=t_late,
        )

        assert all(
            ev.trigger_type != TRIGGER_TOPIC_COOLING
            for ev in triggers
        )

    def test_no_trigger_when_recent_messages_still_have_substantive_content(self):
        """最近消息仍有具体信息时，不应被机械判成冷场"""
        tracker = EmotionStateTracker()
        base = 1000.0

        for i in range(12):
            tracker.update(
                make_sentiment(0),
                make_message("密集消息" + str(i), timestamp=int(base + i * 25)),
                current_time=base + i * 25,
            )

        t1 = base + 520
        tracker.update(
            make_sentiment(0),
            make_message("我作业都还没动", timestamp=int(t1)),
            current_time=t1,
        )
        t2 = base + 550
        triggers = tracker.update(
            make_sentiment(0),
            make_message("写完了", timestamp=int(t2)),
            current_time=t2,
        )

        assert all(
            ev.trigger_type != TRIGGER_TOPIC_COOLING
            for ev in triggers
        )


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
