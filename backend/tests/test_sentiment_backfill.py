"""情感补算任务测试：覆盖率查询 / 缺口补算 / 取消保留 / 任务互斥。

真形表内存库 + 构造器注入 Fake 情感服务（不触发 ONNX）。
"""
import os
import sqlite3
import sys
import threading
import time

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import app.services.analysis.preprocessing_orchestrator as orchmod
import app.services.analysis.sentiment_backfill_service as bfmod
from app.services.analysis.preprocessing_orchestrator import PreprocessingOrchestrator
from app.services.analysis.sentiment_backfill_service import SentimentBackfillService
from app.webview.api.affinity import AffinityApiMixin
from app.webview.api.deep_analysis import DeepAnalysisApiMixin


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
    monkeypatch.setattr(bfmod, "get_db", lambda: conn)
    monkeypatch.setattr(orchmod, "get_db", lambda: conn)
    yield conn
    conn.close()


def seed_messages(db, n=10, conversation_id=1, start_ts=1_700_000_000):
    ids = []
    for i in range(n):
        mid = start_ts + i  # 借时间戳序列当 id，避免跨测试撞号
        db.execute(
            "INSERT INTO messages (id, conversation_id, is_sender, message_type, content, timestamp)"
            " VALUES (?, ?, 0, 1, ?, ?)",
            (mid, conversation_id, f"消息内容{i}", start_ts + i * 60),
        )
        ids.append(mid)
    db.commit()
    return ids


class FakeSentimentService:
    """记录被分析消息、按批写缓存；可选在指定批次后置取消事件。"""

    def __init__(self, db, cancel_event=None, cancel_after_batches=None,
                 embedding_model_available=False):
        self.db = db
        self.cancel_event = cancel_event
        self.cancel_after_batches = cancel_after_batches
        self.embedding_model_available = embedding_model_available
        self.analyzed_texts: list[str] = []
        self.cached_ids: list[int] = []
        self.include_embeddings_seen: list[bool] = []
        self._batches_done = 0

    def has_local_embedding_model(self):
        return self.embedding_model_available

    def batch_get_sentiment_from_cache(self, message_ids):
        rows = self.db.execute(
            "SELECT message_id FROM sentiment_cache WHERE message_id IN "
            f"({','.join('?' * len(message_ids))})",
            message_ids,
        ).fetchall()
        return {row["message_id"]: {"polarity": 1, "intensity": 0.1} for row in rows}

    def analyze_batch(self, texts, include_embeddings=False):
        self.analyzed_texts.extend(texts)
        self.include_embeddings_seen.append(bool(include_embeddings))
        return [{"polarity": 1, "intensity": 0.4, "embedding": None} for _ in texts]

    def batch_cache_sentiments(self, cache_data):
        for item in cache_data:
            self.db.execute(
                "INSERT OR REPLACE INTO sentiment_cache (message_id, polarity, intensity, created_at)"
                " VALUES (?, ?, ?, 1)",
                (item["message_id"], item["polarity"], item["intensity"]),
            )
        self.db.commit()
        self.cached_ids.extend(item["message_id"] for item in cache_data)
        self._batches_done += 1
        if self.cancel_event is not None and self.cancel_after_batches is not None:
            if self._batches_done >= self.cancel_after_batches:
                self.cancel_event.set()


def make_service(db, cancel_event=None, cancel_after_batches=None):
    orchestrator = PreprocessingOrchestrator()
    fake = FakeSentimentService(db, cancel_event, cancel_after_batches)
    orchestrator.sentiment_service = fake
    return SentimentBackfillService(orchestrator=orchestrator), fake


class TestCoverage:
    def test_coverage_counts(self, db):
        ids = seed_messages(db, n=4)
        db.execute(
            "INSERT INTO sentiment_cache (message_id, polarity, intensity, created_at) VALUES (?, 1, 0.2, 1)",
            (ids[0],),
        )
        db.execute(
            "INSERT INTO sentiment_cache (message_id, polarity, intensity, created_at) VALUES (?, 0, 0.0, 1)",
            (ids[1],),
        )
        db.execute(
            "INSERT INTO messages (id, conversation_id, is_sender, message_type, content, timestamp)"
            " VALUES (999, 1, 0, 3, NULL, 123)",  # 非文本消息不计入
        )
        db.commit()

        coverage = SentimentBackfillService.get_coverage(1)
        assert coverage["total"] == 4
        assert coverage["cached"] == 2
        assert coverage["missing"] == 2
        assert coverage["need_backfill"] is True

    def test_full_coverage_no_backfill_needed(self, db):
        ids = seed_messages(db, n=2)
        for mid in ids:
            db.execute(
                "INSERT INTO sentiment_cache (message_id, polarity, intensity, created_at) VALUES (?, 1, 0.2, 1)",
                (mid,),
            )
        db.commit()
        coverage = SentimentBackfillService.get_coverage(1)
        assert coverage["need_backfill"] is False
        assert coverage["ratio"] == 1.0


class TestRunBackfill:
    def test_only_missing_messages_analyzed(self, db):
        """已缓存消息跳过；补算后缓存全覆盖。"""
        ids = seed_messages(db, n=6)
        db.execute(
            "INSERT INTO sentiment_cache (message_id, polarity, intensity, created_at) VALUES (?, -1, 0.8, 1)",
            (ids[0],),
        )
        db.commit()

        service, fake = make_service(db)
        task_id = "t1"
        service.register_task(task_id, 1)
        result = service.run_backfill(1, threading.Event(), task_id)

        assert result["status"] == "completed"
        assert result["progress_percent"] == 100
        assert len(fake.analyzed_texts) == 5  # 已缓存的 ids[0] 不进推理


class TestEmbeddingWriteGate:
    def test_preprocessing_passes_include_embeddings_by_availability(self, db):
        """嵌入写入随可用性门：模型在→include_embeddings=True，缺→False。"""
        seed_messages(db, n=3)

        orchestrator = PreprocessingOrchestrator()
        fake = FakeSentimentService(db, embedding_model_available=True)
        orchestrator.sentiment_service = fake
        orchestrator.run_sentiment_backfill(1)
        assert fake.include_embeddings_seen == [True]

        fake2 = FakeSentimentService(db, embedding_model_available=False)
        orchestrator.sentiment_service = fake2
        orchestrator.run_sentiment_backfill(1)  # 全缓存命中，不进批次
        assert fake2.include_embeddings_seen == []
        coverage = SentimentBackfillService.get_coverage(1)
        assert coverage["need_backfill"] is False

    def test_cancel_keeps_written_batches(self, db):
        """中途取消：已写入批次的缓存保留（续跑自动跳过）。"""
        seed_messages(db, n=1200)  # 500/批 → 3 批；第 1 批后取消
        cancel_event = threading.Event()
        service, fake = make_service(db, cancel_event=cancel_event, cancel_after_batches=1)
        task_id = "t2"
        service.register_task(task_id, 1)

        result = service.run_backfill(1, cancel_event, task_id)

        assert result["status"] == "cancelled"
        assert len(fake.cached_ids) == 500  # 第 1 批已落库
        coverage = SentimentBackfillService.get_coverage(1)
        assert coverage["cached"] == 500

        # 续跑：只补剩余缺口
        service2, fake2 = make_service(db)
        service2.register_task("t3", 1)
        result2 = service2.run_backfill(1, threading.Event(), "t3")
        assert result2["status"] == "completed"
        assert len(fake2.analyzed_texts) == 700


class TestTaskRegistry:
    def test_running_task_lifecycle(self):
        service = SentimentBackfillService(orchestrator=object())
        service.register_task("task_a", 7)
        assert service.find_running_task(7) == "task_a"
        assert service.has_running_task() is True
        assert service.find_running_task(8) is None

        service._update("task_a", status="completed")
        assert service.find_running_task(7) is None
        assert service.has_running_task() is False

    def test_prune_finished(self):
        service = SentimentBackfillService(orchestrator=object())
        service.register_task("old", 1)
        service._update("old", status="completed", finished_at=time.time() - 7200)
        service.register_task("new", 2)
        service.prune_finished()
        assert service.get_progress("old") is None
        assert service.get_progress("new") is not None


class _FakeAffinity:
    def __init__(self, running):
        self._running = running

    def has_running_task(self):
        return self._running


class _Bridge(DeepAnalysisApiMixin, AffinityApiMixin):
    """组合两 mixin（生产 Bridge 同构）：互斥守卫依赖 affinity 侧的
    _all_affinity_services 收集全部历史服务实例。"""
    def __init__(self, affinity=None, affinity_list=None, backfill=None):
        if affinity is not None:
            self._affinity_service = affinity
        if affinity_list is not None:
            self._affinity_services = affinity_list
        if backfill is not None:
            self._sentiment_backfill_service = backfill


class TestBridgeGuards:
    def test_start_refused_when_affinity_running(self):
        bridge = _Bridge(affinity=_FakeAffinity(running=True))
        result = bridge.start_sentiment_backfill(1)
        assert result["ok"] is False
        assert "全面分析" in result["error"]

    def test_start_refused_when_old_affinity_instance_running(self):
        """最新 affinity 实例空闲、旧实例仍运行 → 照样拒绝（防 ONNX 争抢）。"""
        bridge = _Bridge(
            affinity=_FakeAffinity(running=False),
            affinity_list=[_FakeAffinity(running=True), _FakeAffinity(running=False)],
        )
        result = bridge.start_sentiment_backfill(1)
        assert result["ok"] is False
        assert "全面分析" in result["error"]

    def test_start_refused_when_other_conversation_backfill_running(self):
        """不同会话的补算并发 → 拒绝（全局单飞，防覆盖取消事件）。"""
        backfill = SentimentBackfillService(orchestrator=object())
        backfill.register_task("running_other", 7)
        bridge = _Bridge(backfill=backfill)
        result = bridge.start_sentiment_backfill(8)
        assert result["ok"] is False
        assert "另一会话" in result["error"]

    def test_start_reuses_running_backfill(self):
        backfill = SentimentBackfillService(orchestrator=object())
        backfill.register_task("reuse_me", 3)
        bridge = _Bridge(backfill=backfill)
        result = bridge.start_sentiment_backfill(3)
        assert result["ok"] is True
        assert result["task_id"] == "reuse_me"

    def test_start_returns_complete_when_no_gap(self, db):
        ids = seed_messages(db, n=2)
        for mid in ids:
            db.execute(
                "INSERT INTO sentiment_cache (message_id, polarity, intensity, created_at) VALUES (?, 1, 0.2, 1)",
                (mid,),
            )
        db.commit()
        bridge = _Bridge()
        result = bridge.start_sentiment_backfill(1)
        assert result["ok"] is True
        assert result["status"] == "complete"

    def test_full_start_and_progress(self, db):
        """注入桩编排器的完整启动→轮询→完成链路。"""
        seed_messages(db, n=30)

        class _FakeOrchestrator:
            def __init__(self):
                self.calls = []

            def run_sentiment_backfill(self, conversation_id, cancel_event=None, progress_cb=None):
                self.calls.append(conversation_id)
                if progress_cb:
                    progress_cb(1.0)

        backfill = SentimentBackfillService(orchestrator=_FakeOrchestrator())
        bridge = _Bridge(backfill=backfill)
        result = bridge.start_sentiment_backfill(1)
        assert result["ok"] is True
        assert result["status"] == "started"
        task_id = result["task_id"]

        deadline = time.time() + 5
        progress = None
        while time.time() < deadline:
            progress = bridge.get_sentiment_backfill_progress(task_id)
            if progress["status"] in {"completed", "failed", "cancelled"}:
                break
            time.sleep(0.02)
        assert progress["status"] == "completed"
        assert progress["progress_percent"] == 100

    def test_progress_unknown_task(self):
        bridge = _Bridge(backfill=SentimentBackfillService(orchestrator=object()))
        progress = bridge.get_sentiment_backfill_progress("nope")
        assert progress["status"] == "not_found"

    def test_cancel_without_task(self):
        bridge = _Bridge()
        assert bridge.cancel_sentiment_backfill()["ok"] is False

    def test_per_task_cancel_and_event_cleanup(self, db):
        """按 task_id 精确取消；取消事件表在任务终态后清理。"""
        seed_messages(db, n=5)

        class _BlockingOrchestrator:
            def run_sentiment_backfill(self, conversation_id, cancel_event=None, progress_cb=None):
                cancel_event.wait()  # 模拟长推理，直到被取消
                raise RuntimeError("分析已被用户取消")

        backfill = SentimentBackfillService(orchestrator=_BlockingOrchestrator())
        bridge = _Bridge(backfill=backfill)
        result = bridge.start_sentiment_backfill(1)
        assert result["status"] == "started"
        task_id = result["task_id"]

        deadline = time.time() + 5
        while time.time() < deadline and not bridge._sentiment_backfill_cancel_events:
            time.sleep(0.02)

        assert bridge.cancel_sentiment_backfill(task_id)["ok"] is True
        assert bridge.cancel_sentiment_backfill("nope")["ok"] is False

        status = None
        while time.time() < deadline:
            status = bridge.get_sentiment_backfill_progress(task_id)["status"]
            if status in {"cancelled", "completed", "failed"}:
                break
            time.sleep(0.02)
        assert status == "cancelled"

        while time.time() < deadline and bridge._sentiment_backfill_cancel_events:
            time.sleep(0.02)
        assert not bridge._sentiment_backfill_cancel_events
