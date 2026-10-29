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
import app.services.analysis.engagement_metrics as emmod
import app.services.analysis.personality_impression_service as bimod
import app.services.analysis.relationship_chapters as chaptersmod
from app.services.analysis.deep_analysis_service import DeepAnalysisService


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
    # big5_evolution 经 PersonalityImpressionService/EngagementMetricsService 取数，
    # 两模块的顶层 get_db 绑定同样要替换（否则测试会摸到真实开发库）
    monkeypatch.setattr(bimod, "get_db", lambda: conn)
    monkeypatch.setattr(emmod, "get_db", lambda: conn)
    # 章节分段（chapter_spans）降级路径直查 messages；检测路径在本测试库缺
    # sessions/response_times 等表会抛错被吞，同样落到降级路径
    monkeypatch.setattr(chaptersmod, "get_db", lambda: conn)
    yield conn
    conn.close()


def use_chapter_spans(monkeypatch, *spans, ok=True):
    """钉住章节分段（C4 统一口径）：deep/画像演变测试不依赖检测内部，
    直接给定 (from_ts, to_ts) 闭区间边界。"""
    monkeypatch.setattr(
        chaptersmod, "chapter_spans",
        lambda cid: {
            "ok": ok, "spans": list(spans),
            "full_from": spans[0][0], "full_to": spans[-1][1],
        },
    )


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
        assert result["version"] == 5

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
    def test_first_message_full_session_scope(self, db):
        """C4 起里程碑全会话口径：日期窗收窄也不漏全局首条，且不再产出
        window 首条（全会话窗恒包含全局首条，窗口径留给海报路径）。"""
        msg(db, ts(2024, 5, 1))
        msg(db, ts(2026, 3, 5))

        result = DeepAnalysisService().get_deep_analysis(
            1, ts(2026, 1, 1), ts(2026, 3, 31), bucket="month"
        )
        firsts = [e for e in result["milestones"] if e["kind"] == "first_message"]
        assert len(firsts) == 1
        assert firsts[0]["scope"] == "global"
        assert firsts[0]["ts"] == ts(2024, 5, 1)

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


class TestChapterSpanDegrade:
    """C4 统一分段：小数据会话检测不出章节 → 全会话单段诚实降级。"""

    def test_small_conversation_degrades_to_single_full_span(self, db):
        base = ts(2026, 3, 1)
        for i in range(4):
            msg(db, base + i * 60, content="火锅火锅火锅", with_sentiment=False)

        result = DeepAnalysisService().get_deep_analysis(
            1, ts(2026, 3, 1), ts(2026, 3, 5), bucket="week"
        )
        # payload 携带章节分段：chapters_ok=False + 单段 [min, max]
        assert result["chapters_ok"] is False
        assert result["chapter_spans"] == [(base, base + 3 * 60)]
        segs = result["wordcloud_evolution"]["segments"]
        assert [(s["from_ts"], s["to_ts"]) for s in segs] == [(base, base + 3 * 60)]

    def test_date_window_no_longer_cuts_wordcloud(self, db):
        """词云/大五/里程碑全会话口径：日期窗收窄不再截掉词云段。"""
        for day in (1, 2, 3, 4, 5):
            msg(db, ts(2026, 3, day), content="火锅火锅火锅", with_sentiment=False)

        narrow = DeepAnalysisService().get_deep_analysis(
            1, ts(2026, 3, 4), ts(2026, 3, 5), bucket="week"
        )
        segs = narrow["wordcloud_evolution"]["segments"]
        assert len(segs) == 1
        assert segs[0]["total"] == 5  # 全会话 5 条都在，不受窗口影响


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

    def test_cleaned_caliber_when_fully_preprocessed(self, db):
        """覆盖率 ≥90%：用清洗缓存文本，原始噪声词不出现。"""
        base = ts(2026, 3, 3, 8)
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

    def test_party_split_across_chapter_spans(self, db, monkeypatch):
        """me/other 分视角；按章节边界切两段，各段词集互不串段。"""
        base = ts(2026, 3, 2)
        boundary = ts(2026, 3, 4)
        use_chapter_spans(monkeypatch, (base, boundary), (boundary + 1, ts(2026, 3, 6)))
        # 第 1 章：我谈旅行，对方谈加班
        for i in range(3):
            msg(db, base + i * 60, is_sender=1, content="旅行旅行旅行", with_sentiment=False)
            msg(db, base + i * 60 + 30, is_sender=0, content="加班加班加班", with_sentiment=False)
        # 第 2 章
        late = ts(2026, 3, 5, 18)
        for i in range(3):
            msg(db, late + i * 60, is_sender=1, content="健身健身健身", with_sentiment=False)
            msg(db, late + i * 60 + 30, is_sender=0, content="考试考试考试", with_sentiment=False)

        result = DeepAnalysisService().get_deep_analysis(
            1, ts(2026, 3, 1), ts(2026, 3, 8), bucket="week"
        )
        segs = result["wordcloud_evolution"]["segments"]
        assert len(segs) == 2
        first, second = segs
        first_all = {w["word"] for w in first["words"]["all"]}
        assert {"旅行", "加班"} <= first_all
        assert {w["word"] for w in first["words"]["me"]} == {"旅行"}
        assert {w["word"] for w in first["words"]["other"]} == {"加班"}
        assert {"健身", "考试"} <= {w["word"] for w in second["words"]["all"]}

    def test_adjacent_spans_split_words_by_boundary(self, db, monkeypatch):
        """章边界两侧消息各归各章：边界无缝相接（to+1=from），词集按章落段。"""
        base = ts(2026, 3, 2)
        mid = base + 86400
        use_chapter_spans(monkeypatch, (base, mid), (mid + 1, mid + 86400))
        for i in range(3):
            msg(db, base + i * 60, is_sender=1, content="旅行旅行旅行", with_sentiment=False)
            msg(db, base + i * 60 + 30, is_sender=0, content="加班加班加班", with_sentiment=False)
        for i in range(3):
            msg(db, mid + 3600 + i * 60, is_sender=1, content="健身健身健身", with_sentiment=False)

        result = DeepAnalysisService().get_deep_analysis(
            1, base, mid + 86400, bucket="week"
        )
        segs = result["wordcloud_evolution"]["segments"]
        assert len(segs) == 2
        assert segs[0]["to_ts"] + 1 == segs[1]["from_ts"]
        assert {w["word"] for w in segs[0]["words"]["me"]} == {"旅行"}
        assert {w["word"] for w in segs[1]["words"]["me"]} == {"健身"}

    def test_no_text_messages_yields_empty_segments(self, db):
        """全会话无文本消息：none 口径空段列表，不抛异常。"""
        evo = DeepAnalysisService()._wordcloud_evolution(1, [(1000, 2000), (2001, 3000)])
        assert evo == {"caliber": "none", "coverage_ratio": 0.0, "segments": []}

    def test_empty_window(self, db):
        result = DeepAnalysisService().get_deep_analysis(
            1, ts(2026, 1, 1), ts(2026, 1, 31), bucket="week"
        )
        assert result["ok"] is True
        assert result["buckets"] == []
        assert result["wordcloud_evolution"]["segments"] == []
        assert result["milestones"] == []
        assert result["chapter_spans"] == []


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


class TestBig5Evolution:
    """deep payload 的 big5_evolution：段随章节边界、薄段 None、空段降级、首开落缓存。"""

    @staticmethod
    def _seed_dense(db, start, n_each=40, step=60, content="消息内容"):
        """双方交替 n_each 条文本，从 start 起每 step 秒一条。"""
        for i in range(n_each):
            for side in (1, 0):
                db.execute(
                    "INSERT INTO messages (conversation_id, is_sender, message_type, content, timestamp)"
                    " VALUES (1, ?, 1, ?, ?)",
                    (side, f"{content}{i}", start + (i * 2 + side) * step),
                )

    def test_series_follow_chapter_spans(self, db, monkeypatch):
        """段数与边界随章节分段（与词云共用分段）；双侧均有画像。"""
        span_a = (ts(2026, 3, 1), ts(2026, 3, 3))
        span_b = (span_a[1] + 1, ts(2026, 3, 5))
        use_chapter_spans(monkeypatch, span_a, span_b)
        self._seed_dense(db, ts(2026, 3, 2, 11))  # 第 1 章足量
        self._seed_dense(db, ts(2026, 3, 4, 11))  # 第 2 章足量

        result = DeepAnalysisService().get_deep_analysis(
            1, ts(2026, 3, 1), ts(2026, 3, 5), bucket="week"
        )
        evo = result["big5_evolution"]
        assert evo["segments"] == 2
        assert evo["min_messages"] == 30
        assert [(s["from_ts"], s["to_ts"]) for s in evo["series"]] == [span_a, span_b]
        for seg in evo["series"]:
            assert seg["me"] is not None and seg["other"] is not None
            assert "error" not in seg

    def test_thin_segment_subjects_none(self, db, monkeypatch):
        """第 2 章每侧不足 30 条：该章 me/other 双 None，前章不受影响。"""
        span_a = (ts(2026, 3, 1), ts(2026, 3, 3))
        span_b = (span_a[1] + 1, ts(2026, 3, 5))
        use_chapter_spans(monkeypatch, span_a, span_b)
        self._seed_dense(db, ts(2026, 3, 2, 11))
        for i in range(10):  # 第 2 章薄样本
            db.execute(
                "INSERT INTO messages (conversation_id, is_sender, message_type, content, timestamp)"
                " VALUES (1, ?, 1, '薄样本', ?)",
                (i % 2, ts(2026, 3, 4, 13) + i * 60),
            )

        result = DeepAnalysisService().get_deep_analysis(
            1, ts(2026, 3, 1), ts(2026, 3, 5), bucket="week"
        )
        first, second = result["big5_evolution"]["series"]
        assert first["me"] is not None and first["other"] is not None
        assert second["me"] is None and second["other"] is None
        assert "error" not in second  # 薄样本是 None 而非错误

    def test_empty_span_degrades_not_crash(self, db):
        """空段（end < start，边界异常）：该段标 error 降级，payload 不炸。"""
        evo = DeepAnalysisService()._big5_evolution(1, [(1000, 1002), (1002, 1000)])
        assert len(evo["series"]) == 2
        assert all(s["me"] is None and s["other"] is None for s in evo["series"])
        assert any("error" in s for s in evo["series"])

    def test_first_call_persists_custom_window_cache(self, db, monkeypatch):
        """首开逐章算 local 并落 custom 窗缓存；清空消息后二次调用原样命中。"""
        span_a = (ts(2026, 3, 1), ts(2026, 3, 3))
        span_b = (span_a[1] + 1, ts(2026, 3, 5))
        use_chapter_spans(monkeypatch, span_a, span_b)
        self._seed_dense(db, ts(2026, 3, 2, 11))
        self._seed_dense(db, ts(2026, 3, 4, 11))
        service = DeepAnalysisService()
        first = service.get_deep_analysis(
            1, ts(2026, 3, 1), ts(2026, 3, 5), bucket="week"
        )

        rows = db.execute(
            "SELECT COUNT(*) FROM big5_impressions WHERE window_kind = 'custom' AND source = 'local'"
        ).fetchone()
        assert rows[0] == 4  # 2 章 × 双侧

        db.execute("DELETE FROM messages")
        second = service.get_deep_analysis(
            1, ts(2026, 3, 1), ts(2026, 3, 5), bucket="week"
        )
        for a, b in zip(first["big5_evolution"]["series"], second["big5_evolution"]["series"]):
            assert a["me"]["scores"] == b["me"]["scores"]
            assert a["other"]["scores"] == b["other"]["scores"]


class TestPosterBig5:
    """海报大五窗口对齐（C4-2）：页头印的是窗口日期，大五读数必须同窗。"""

    @staticmethod
    def _fake_impression_service(monkeypatch, *, cached, computed=None):
        """打桩大五服务：cached=(subject→行 or None) 缓存读数；
        computed 缺省时 get_impressions 抛错（断言未被调用的用例靠它显红）。"""
        import app.services.analysis.personality_impression_service as bimod

        calls: list[tuple] = []

        class FakeService:
            def _load_cached(self, conv, account, subject, now, window=None):
                calls.append(("load", subject, window))
                return cached.get(subject)

            def get_impressions(self, conv, account_wxid="", force_refresh=False,
                                from_ts=None, to_ts=None):
                calls.append(("compute", from_ts, to_ts))
                if computed is None:
                    raise AssertionError("custom 窗 miss 不应触发现算")
                return computed

        monkeypatch.setattr(bimod, "PersonalityImpressionService", FakeService)
        return calls

    def test_custom_window_miss_computes_local(self, db, monkeypatch):
        """custom 窗缓存 miss：按海报窗口现算（from_ts/to_ts 透传）。"""
        computed = {"ok": True, "subjects": {
            "me": {"source": "local", "scores": {"openness": {"score": 62, "label": "开放"}}},
            "other": {"source": "local", "scores": {"openness": {"score": 38, "label": "开放"}}},
        }}
        calls = self._fake_impression_service(monkeypatch, cached={}, computed=computed)

        result = DeepAnalysisService._poster_big5(1, "wxid_me", 1000, 2000)

        assert all(c == ("compute", 1000, 2000) for c in calls if c[0] == "compute")
        assert result["me"]["source"] == "local"
        assert result["me"]["scores"]["openness"] == {"score": 62, "label": "开放"}
        assert result["other"]["scores"]["openness"]["score"] == 38

    def test_custom_window_hit_skips_compute(self, db, monkeypatch):
        """窗口缓存双侧命中：不现算，读数原样带回（证据不随海报出网）。"""
        cached = {
            "me": {
                "source": "llm_enhanced",
                "scores": {"openness": {"score": 70, "label": "开放", "base_score": 60}},
                "evidence": {"openness": {"quote": "原文证据", "reason": "依据"}},
            },
            "other": {
                "source": "local",
                "scores": {"openness": {"score": 44, "label": "开放"}},
            },
        }
        calls = self._fake_impression_service(monkeypatch, cached=cached)

        result = DeepAnalysisService._poster_big5(1, "wxid_me", 1000, 2000)

        assert not any(c[0] == "compute" for c in calls)
        assert result["me"]["scores"]["openness"] == {"score": 70, "label": "开放"}  # 证据/base 剥离
        assert result["other"]["scores"]["openness"]["score"] == 44

    def test_cached_scores_stripped_to_score_label(self, db, monkeypatch):
        """缓存行只带 score/label：base_score/adjustment 等内部字段不出网。"""
        cached = {
            "me": {"source": "local", "scores": {
                "neuroticism": {"score": 41, "label": "敏感", "base_score": 50, "adjustment": -9},
            }},
            "other": {"source": "local", "scores": {}},
        }
        self._fake_impression_service(monkeypatch, cached=cached)

        result = DeepAnalysisService._poster_big5(1, "wxid_me", 1000, 2000)

        assert result["me"]["scores"]["neuroticism"] == {"score": 41, "label": "敏感"}


class TestPosterTopWordsSampling:
    """海报 top 词抽样口径（第四轮 W13）：窗口超上限时按时间序等距抽取。

    此前 ORDER BY timestamp DESC LIMIT 只取窗口尾部，词频系统性偏向
    近期话题，与海报「聊得最多的词」全窗措辞矛盾；等距抽样首条必中
    且尾段有代表，首尾两半计数接近。
    """

    def test_sampling_spans_full_window(self, db):
        from app.services.analysis.deep_analysis_service import POSTER_WORDCLOUD_SAMPLE

        calls: list[list[str]] = []

        class _RecordingGen:
            def generate(self, texts, top_n=12):
                calls.append(list(texts))
                return {"词": 1}

        # 5000 条 > 抽样上限 2000：stride=ceil(5000/2000)=3，约取 1667 条
        for i in range(5000):
            db.execute(
                "INSERT INTO messages (conversation_id, is_sender, message_type, content, timestamp)"
                " VALUES (1, ?, 1, ?, ?)",
                (i % 2, f"msg{i}", 1000 + i),
            )

        service = DeepAnalysisService.__new__(DeepAnalysisService)
        service._wordcloud_gen = _RecordingGen()

        service._poster_top_words(1, 0, 100000)

        all_texts = calls[0]  # 第一次调用即 "all" 槽
        assert len(calls) == 3  # all / me / other
        assert len(all_texts) <= POSTER_WORDCLOUD_SAMPLE
        assert len(all_texts) >= 1500  # 等距约 1667 条，留出容差
        indices = sorted(int(t[3:]) for t in all_texts)
        assert indices[0] == 0  # 首条必中：窗口起点有代表
        assert indices[-1] >= 4990  # 尾段有代表（DESC LIMIT 尾部偏倚的对照面）
        first_half = sum(1 for i in indices if i < 2500)
        second_half = len(indices) - first_half
        assert abs(first_half - second_half) <= 40  # 首尾两半均衡
        me_texts, other_texts = calls[1], calls[2]
        assert me_texts and other_texts  # 双方槽都拿到样本
