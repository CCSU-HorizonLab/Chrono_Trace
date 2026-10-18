"""时光深度聚合（分桶情绪序列/覆盖率/拐点/词云演变/里程碑）测试。

真形表内存库范式：deep 服务与被复用的 analysis_service 各自的 get_db
绑定都要替换（两模块都是 `from ...connection import get_db` 顶层绑定）。
"""
import os
import sqlite3
import sys
from datetime import datetime

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import app.services.analysis.analysis_service as analysismod
import app.services.analysis.deep_analysis_service as deepmod
from app.services.analysis.deep_analysis_service import (
    DEEP_WORDCLOUD_SEGMENTS_DEFAULT,
    DeepAnalysisService,
    split_window_evenly,
)


def ts(year, month, day, hour=12):
    """本地时间戳（与 SQL 里的 'localtime' 修饰一致；取正午避开日界漂移）"""
    return int(datetime(year, month, day, hour).timestamp())


@pytest.fixture
def db(monkeypatch):
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        "CREATE TABLE messages (id INTEGER PRIMARY KEY, conversation_id INT, "
        "is_sender INT, message_type INT DEFAULT 1, content TEXT, timestamp INT)"
    )
    conn.execute(
        "CREATE TABLE sentiment_cache (message_id INTEGER UNIQUE, polarity INT, "
        "intensity REAL, created_at INT)"
    )
    conn.execute(
        "CREATE TABLE message_preprocessed (message_id INTEGER PRIMARY KEY, "
        "conversation_id INT, cleaned_content TEXT, is_valid INT DEFAULT 1, created_at INT)"
    )
    conn.execute(
        "CREATE TABLE affinity_scores (id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "conversation_id INT, analysis_version INT, overall_score REAL, created_at INT)"
    )
    monkeypatch.setattr(deepmod, "get_db", lambda: conn)
    monkeypatch.setattr(analysismod, "get_db", lambda: conn)
    yield conn
    conn.close()


_mid = iter(range(1, 100000))


def msg(db, t, is_sender=0, content="今晚吃什么", with_sentiment=True, polarity=1, intensity=0.3, message_type=1):
    mid = next(_mid)
    db.execute(
        "INSERT INTO messages (id, conversation_id, is_sender, message_type, content, timestamp)"
        " VALUES (?, 1, ?, ?, ?, ?)",
        (mid, is_sender, message_type, content, int(t)),
    )
    if with_sentiment:
        db.execute(
            "INSERT INTO sentiment_cache (message_id, polarity, intensity, created_at)"
            " VALUES (?, ?, ?, 1)",
            (mid, polarity, intensity),
        )
    return mid


def preprocessed(db, mid, cleaned):
    db.execute(
        "INSERT INTO message_preprocessed (message_id, conversation_id, cleaned_content, is_valid, created_at)"
        " VALUES (?, 1, ?, 1, 1)",
        (mid, cleaned),
    )


class TestBucketSeries:
    def test_week_bucket_spans_year_boundary(self, db):
        """ISO 周（周一首日）：2025-12-29(一)~2026-01-04(日) 归同一桶。"""
        for day in ((2025, 12, 29), (2025, 12, 31), (2026, 1, 1), (2026, 1, 4)):
            msg(db, ts(*day))
        msg(db, ts(2026, 1, 5))  # 下周一，新桶

        result = DeepAnalysisService().get_deep_analysis(
            1, ts(2025, 12, 20), ts(2026, 1, 10), bucket="week"
        )
        labels = [item["ts"] for item in result["buckets"]]
        assert labels == ["2025-12-29", "2026-01-05"]
        assert result["buckets"][0]["msgCount"] == 4

    def test_month_and_year_bucket_labels(self, db):
        msg(db, ts(2025, 11, 3))
        msg(db, ts(2025, 12, 5))
        msg(db, ts(2026, 1, 7))
        service = DeepAnalysisService()
        monthly = service.get_deep_analysis(1, ts(2025, 1, 1), ts(2026, 6, 1), bucket="month")
        yearly = service.get_deep_analysis(1, ts(2025, 1, 1), ts(2026, 6, 1), bucket="year")
        assert [item["ts"] for item in monthly["buckets"]] == ["2025-11", "2025-12", "2026-01"]
        assert [item["ts"] for item in yearly["buckets"]] == ["2025", "2026"]

    def test_dual_party_avg_split(self, db):
        """userScore/otherScore 按 is_sender 各自均值；单侧无消息为 null；
        userCount/otherCount 为每侧已缓存计数（滚动平滑的加权权重）。"""
        base = ts(2026, 3, 10)
        msg(db, base + 1, is_sender=1, intensity=0.5)
        msg(db, base + 2, is_sender=1, intensity=0.1)
        msg(db, base + 3, is_sender=0, intensity=-0.3)
        msg(db, ts(2026, 3, 11), is_sender=0, intensity=-0.2)  # 次日（桶内只有对方）
        msg(db, ts(2026, 3, 11), is_sender=1, with_sentiment=False)  # 未缓存：不进分子分母

        result = DeepAnalysisService().get_deep_analysis(
            1, ts(2026, 3, 9), ts(2026, 3, 12), bucket="day"
        )
        first, second = result["buckets"]
        assert first["userScore"] == pytest.approx(0.3)
        assert first["otherScore"] == pytest.approx(-0.3)
        assert first["userCount"] == 2
        assert first["otherCount"] == 1
        assert second["userScore"] is None
        assert second["otherScore"] == pytest.approx(-0.2)
        assert second["userCount"] == 0  # 未缓存消息不计入每侧计数
        assert second["otherCount"] == 1

    def test_side_message_counts_full_volume(self, db):
        """userMsgCount/otherMsgCount 为分侧全量计数（不依赖情感缓存），
        两侧之和等于合计 msgCount——互动量双柱数据源；缺覆盖桶分侧同样全量。"""
        base = ts(2026, 3, 10)
        msg(db, base + 1, is_sender=1)
        msg(db, base + 2, is_sender=1, with_sentiment=False)  # 未缓存仍计入全量
        msg(db, base + 3, is_sender=0)
        msg(db, ts(2026, 3, 11), is_sender=0, with_sentiment=False)  # 次日缺覆盖桶

        result = DeepAnalysisService().get_deep_analysis(
            1, ts(2026, 3, 9), ts(2026, 3, 12), bucket="day"
        )
        first, second = result["buckets"]
        assert (first["userMsgCount"], first["otherMsgCount"]) == (2, 1)
        assert first["msgCount"] == first["userMsgCount"] + first["otherMsgCount"]
        assert (second["userMsgCount"], second["otherMsgCount"]) == (0, 1)
        assert second["msgCount"] == second["userMsgCount"] + second["otherMsgCount"]
        assert result["version"] == 3

    def test_uncovered_bucket_keeps_full_count(self, db):
        """缺情感数据的桶：coverage=0、score=None、lowConfidence，msgCount 仍全量。"""
        msg(db, ts(2026, 3, 1))
        msg(db, ts(2026, 3, 2), with_sentiment=False)
        msg(db, ts(2026, 3, 2), with_sentiment=False)
        msg(db, ts(2026, 3, 3))

        result = DeepAnalysisService().get_deep_analysis(
            1, ts(2026, 2, 25), ts(2026, 3, 8), bucket="day"
        )
        middle = result["buckets"][1]
        assert middle["ts"] == "2026-03-02"
        assert middle["msgCount"] == 2
        assert middle["cachedCount"] == 0
        assert middle["coverage"] == 0.0
        assert middle["score"] is None
        assert middle["lowConfidence"] is True
        # 全覆盖桶不标低置信
        assert result["buckets"][0]["lowConfidence"] is False

    def test_invalid_bucket_rejected(self, db):
        result = DeepAnalysisService().get_deep_analysis(1, 0, 100, bucket="quarter")
        assert result["ok"] is False


class TestTurningPoints:
    def test_max_drop_and_rise_with_threshold(self, db):
        """相邻桶最大涨/跌幅；样本不足（<30 条）的桶不参与。"""
        weeks = [
            (ts(2026, 2, 2), 35, 0.2),    # 第 1 周：涨势起点
            (ts(2026, 2, 9), 35, 0.5),    # +0.3 rise
            (ts(2026, 2, 16), 35, 0.4),
            (ts(2026, 2, 23), 35, -0.2),  # -0.6 drop
            (ts(2026, 3, 2), 5, 1.0),     # 小样本桶，不参与
        ]
        for week_ts, count, intensity in weeks:
            for i in range(count):
                msg(db, week_ts + i * 60, intensity=intensity)

        result = DeepAnalysisService().get_deep_analysis(
            1, ts(2026, 1, 30), ts(2026, 3, 10), bucket="week"
        )
        turning = result["turning_points"]
        by_direction = {item["direction"]: item for item in turning}
        assert by_direction["rise"]["delta"] == pytest.approx(0.3)
        assert by_direction["drop"]["delta"] == pytest.approx(-0.6)
        # 小样本桶不进入任何拐点
        assert all(item["to_ts"] != "2026-03-02" for item in turning)


class TestMilestones:
    def test_first_message_global_and_window_scope(self, db):
        msg(db, ts(2024, 5, 1))
        msg(db, ts(2026, 3, 5))

        result = DeepAnalysisService().get_deep_analysis(
            1, ts(2026, 1, 1), ts(2026, 3, 31), bucket="month"
        )
        firsts = [e for e in result["milestones"] if e["kind"] == "first_message"]
        scopes = {e["scope"] for e in firsts}
        assert scopes == {"global", "window"}

    def test_count_marks_injected(self, db):
        for i in range(6):
            msg(db, ts(2026, 3, 1) + i * 3600)

        result = DeepAnalysisService().get_deep_analysis(
            1, ts(2026, 1, 1), ts(2026, 3, 31), bucket="month", marks=(3, 5, 50)
        )
        marks = {e["mark"]: e for e in result["milestones"] if e["kind"] == "count_mark"}
        assert set(marks) == {3, 5}  # 50 未达到，不出现
        # 第 3 条消息的时间戳（按时间升序）
        assert marks[3]["ts"] == ts(2026, 3, 1) + 2 * 3600

    def test_longest_silence_days(self, db):
        msg(db, ts(2026, 3, 1))
        msg(db, ts(2026, 3, 4))   # 3 天间隔
        msg(db, ts(2026, 3, 4, 13))

        result = DeepAnalysisService().get_deep_analysis(
            1, ts(2026, 2, 25), ts(2026, 3, 10), bucket="week"
        )
        silence = [e for e in result["milestones"] if e["kind"] == "longest_silence"]
        assert len(silence) == 1
        assert silence[0]["days"] == pytest.approx(3.0)

    def test_non_text_excluded_from_marks_and_silence(self, db):
        """里程碑与其他深度面板同口径只数文本消息：图片/系统消息不算
        「第 N 条」关口，也不打断真实的人际沉默。"""
        msg(db, ts(2026, 3, 1), content="第一条文本")
        msg(db, ts(2026, 3, 3), content="[图片]", message_type=3)      # 沉默期中间，不计数
        msg(db, ts(2026, 3, 6), content="第二条文本")
        msg(db, ts(2026, 3, 7), content="第三条文本")

        result = DeepAnalysisService().get_deep_analysis(
            1, ts(2026, 2, 25), ts(2026, 3, 10), bucket="week", marks=(3,)
        )
        milestones = result["milestones"]
        # 第 3 条文本消息是 03-07（无过滤时会把图片算进去落到 03-06）
        mark = next(e for e in milestones if e["kind"] == "count_mark")
        assert mark["ts"] == ts(2026, 3, 7)
        # 沉默期跨过中间的图片：03-01 → 03-06 共 5 天（无过滤时被图片打成 3 天）
        silence = next(e for e in milestones if e["kind"] == "longest_silence")
        assert silence["days"] == pytest.approx(5.0)
        # 全局首条也只认文本
        first = next(e for e in milestones if e["kind"] == "first_message")
        assert first["ts"] == ts(2026, 3, 1)


class TestWindowSplit:
    def test_two_segments_match_legacy_halves_formula(self):
        """N=2 与历史 mid_ts=(from+to)//2 前后切分逐点一致。"""
        assert split_window_evenly(1000, 2001, 2) == [(1000, 1499), (1500, 2001)]
        assert split_window_evenly(1000, 2000, 2) == [(1000, 1499), (1500, 2000)]

    def test_four_segments_even(self):
        t0, day = 1000, 86400
        # 前三段 [b_i, b_{i+1}-1]，末段含终点 to_ts
        expected = [(t0 + i * day, t0 + (i + 1) * day - 1) for i in range(3)]
        expected.append((t0 + 3 * day, t0 + 4 * day))
        assert split_window_evenly(t0, t0 + 4 * day, 4) == expected

    def test_short_window_yields_empty_segment(self):
        """窗口秒数小于段数时产出空段（end < start），由调用方守卫。"""
        parts = split_window_evenly(1000, 1002, 4)
        assert any(end < start for start, end in parts)


class TestSegmentTextSampling:
    def test_sampling_returns_exactly_limit_rows(self, db):
        """Bresenham 等距抽样取恰 limit 行：1001/500 不再因步长取模欠采到 333 行。"""
        base = ts(2026, 3, 1)
        for i in range(1001):
            msg(db, base + i * 60, content=f"m{i}", with_sentiment=False)

        rows, total = DeepAnalysisService._load_segment_texts(
            1, base, base + 1001 * 60, False, limit=500
        )

        assert total == 1001
        assert len(rows) == 500
        # 等距且保尾：末条消息必入选（关系后期的语言在场）
        assert rows[-1][1] == "m1000"


class TestWordcloudEvolution:
    @staticmethod
    def _only_segment_with_words(evo):
        segs = [s for s in evo["segments"] if s["words"]["all"]]
        assert len(segs) == 1
        return segs[0]

    def test_default_is_four_segments(self, db):
        """默认 4 段，段边界与切窗工具一致。"""
        base = ts(2026, 3, 1)
        for i in range(4):
            msg(db, base + i * 60, content="火锅火锅火锅", with_sentiment=False)

        result = DeepAnalysisService().get_deep_analysis(
            1, ts(2026, 3, 1), ts(2026, 3, 5), bucket="week"
        )
        segs = result["wordcloud_evolution"]["segments"]
        assert len(segs) == DEEP_WORDCLOUD_SEGMENTS_DEFAULT == 4
        assert [(s["from_ts"], s["to_ts"]) for s in segs] == split_window_evenly(
            ts(2026, 3, 1), ts(2026, 3, 5), 4
        )

    def test_cleaned_caliber_when_fully_preprocessed(self, db):
        """覆盖率 ≥90%：用清洗缓存文本，原始噪声词不出现。"""
        base = ts(2026, 3, 3, 8)  # 上午：落默认 4 段中的第 2 段
        for i in range(4):
            mid = msg(db, base + i * 60, is_sender=i % 2, content="火锅火锅火锅", with_sentiment=False)
            preprocessed(db, mid, "旅行计划讨论")

        result = DeepAnalysisService().get_deep_analysis(
            1, ts(2026, 3, 1), ts(2026, 3, 5), bucket="week"
        )
        evo = result["wordcloud_evolution"]
        assert evo["caliber"] == "cleaned"
        words = {w["word"] for w in self._only_segment_with_words(evo)["words"]["all"]}
        assert "旅行" in words
        assert "火锅" not in words

    def test_raw_caliber_when_coverage_low(self, db):
        """覆盖率 <90%：统一回退原始 content，不与其他段缓存混口径。"""
        base = ts(2026, 3, 3, 8)
        for i in range(4):
            mid = msg(db, base + i * 60, content="火锅火锅火锅", with_sentiment=False)
            if i == 0:
                preprocessed(db, mid, "旅行计划讨论")  # 只有 1/4 有缓存

        result = DeepAnalysisService().get_deep_analysis(
            1, ts(2026, 3, 1), ts(2026, 3, 5), bucket="week"
        )
        evo = result["wordcloud_evolution"]
        assert evo["caliber"] == "raw"
        words = {w["word"] for w in self._only_segment_with_words(evo)["words"]["all"]}
        assert "火锅" in words

    def test_party_split_across_segments(self, db):
        """me/other 分视角；默认 4 段各段词集互不串段。"""
        base = ts(2026, 3, 3)  # 正午：默认 4 段的边界在每日正午，03-03 属第 3 段
        # 第 3 段（03-03 12:00 起）：我谈旅行，对方谈加班
        for i in range(3):
            msg(db, base + i * 60, is_sender=1, content="旅行旅行旅行", with_sentiment=False)
            msg(db, base + i * 60 + 30, is_sender=0, content="加班加班加班", with_sentiment=False)
        # 第 4 段（03-04 12:00 起）
        late = ts(2026, 3, 4, 18)
        for i in range(3):
            msg(db, late + i * 60, is_sender=1, content="健身健身健身", with_sentiment=False)
            msg(db, late + i * 60 + 30, is_sender=0, content="考试考试考试", with_sentiment=False)

        result = DeepAnalysisService().get_deep_analysis(
            1, ts(2026, 3, 1), ts(2026, 3, 5), bucket="week"
        )
        segs = result["wordcloud_evolution"]["segments"]
        assert len(segs) == 4
        third, fourth = segs[2], segs[3]
        third_all = {w["word"] for w in third["words"]["all"]}
        assert {"旅行", "加班"} <= third_all
        assert {w["word"] for w in third["words"]["me"]} == {"旅行"}
        assert {w["word"] for w in third["words"]["other"]} == {"加班"}
        assert {"健身", "考试"} <= {w["word"] for w in fourth["words"]["all"]}

    def test_two_segments_reproduce_halves_boundary(self, db):
        """segments=2 复现历史前后半窗边界：中点无缝相接，前后词集按半窗落段。"""
        base = ts(2026, 3, 3)
        for i in range(3):
            msg(db, base + i * 60, is_sender=1, content="旅行旅行旅行", with_sentiment=False)
            msg(db, base + i * 60 + 30, is_sender=0, content="加班加班加班", with_sentiment=False)
        late = ts(2026, 3, 4, 18)  # 窗口正中点之后，归后半窗
        for i in range(3):
            msg(db, late + i * 60, is_sender=1, content="健身健身健身", with_sentiment=False)

        result = DeepAnalysisService().get_deep_analysis(
            1, ts(2026, 3, 3), ts(2026, 3, 5), bucket="week", word_segments=2
        )
        segs = result["wordcloud_evolution"]["segments"]
        assert len(segs) == 2
        assert segs[0]["to_ts"] + 1 == segs[1]["from_ts"]
        assert {w["word"] for w in segs[0]["words"]["me"]} == {"旅行"}
        assert {w["word"] for w in segs[1]["words"]["me"]} == {"健身"}

    def test_segments_out_of_range_rejected(self, db):
        result = DeepAnalysisService().get_deep_analysis(
            1, ts(2026, 3, 1), ts(2026, 3, 5), bucket="week", word_segments=7
        )
        assert result["ok"] is False
        assert "分段" in result["error"]

    def test_short_window_returns_error_not_crash(self, db):
        """窗口切不出 4 段：返回空段+error，不抛异常。"""
        msg(db, 1000, content="火锅火锅火锅", with_sentiment=False)

        evo = DeepAnalysisService()._wordcloud_evolution(1, 1000, 1002, 4)
        assert evo["segments"] == []
        assert evo["error"]

    def test_empty_window(self, db):
        result = DeepAnalysisService().get_deep_analysis(
            1, ts(2026, 1, 1), ts(2026, 1, 31), bucket="week"
        )
        assert result["ok"] is True
        assert result["buckets"] == []
        assert result["wordcloud_evolution"]["segments"] == []
        assert result["milestones"] == []


class TestAffinityHistory:
    def test_only_current_caliber_rows(self, db):
        from app.services.analysis.affinity_analysis_service import AffinityAnalysisService

        caliber = AffinityAnalysisService.CALIBER_VERSION
        db.executemany(
            "INSERT INTO affinity_scores (conversation_id, analysis_version, overall_score, created_at)"
            " VALUES (1, ?, ?, ?)",
            [
                (caliber - 1, 88.0, ts(2026, 3, 1)),  # 旧口径，过滤
                (caliber, 72.0, ts(2026, 3, 2)),
                (caliber, 80.0, ts(2026, 3, 3)),
            ],
        )

        result = DeepAnalysisService().get_deep_analysis(
            1, ts(2026, 3, 1), ts(2026, 3, 31), bucket="week"
        )
        points = result["affinity_history"]["points"]
        assert [p["score"] for p in points] == [72.0, 80.0]
        assert result["affinity_history"]["caliber_version"] == caliber
