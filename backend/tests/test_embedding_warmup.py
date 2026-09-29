"""embedding 冷启动自愈回归:RAG 向量通道不得永久 embedding_cold。"""

import os
import sqlite3
import sys
import time
from types import SimpleNamespace


sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.realtime.rag.retriever import RagRetriever
from app.services.realtime.rag.store import RagStore


class FakeEmbeddingService:
    """冷服务:预热前 _embedding_model=None,prewarm 后变暖。"""

    def __init__(self):
        self.sentiment_service = SimpleNamespace(_embedding_model=None)
        self.prewarm_calls = 0

    def prewarm(self) -> bool:
        self.prewarm_calls += 1
        self.sentiment_service._embedding_model = object()
        return True


def _retriever(fake=None):
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    retriever = RagRetriever(store=RagStore(conn))
    if fake is not None:
        retriever.embedding_service = fake
    return retriever


def test_cold_check_kicks_background_prewarm():
    fake = FakeEmbeddingService()
    retriever = _retriever(fake)

    assert retriever._embedding_is_warm() is False  # 首查:冷
    deadline = time.time() + 5
    while fake.prewarm_calls == 0 and time.time() < deadline:
        time.sleep(0.02)
    assert fake.prewarm_calls == 1                # 后台预热被触发且仅一次
    deadline = time.time() + 5
    while not retriever._embedding_is_warm() and time.time() < deadline:
        time.sleep(0.02)
    assert retriever._embedding_is_warm() is True  # 预热完成后变暖
    assert fake.prewarm_calls == 1                 # 暖了就不再重复触发


def test_warm_service_never_kicks_prewarm():
    fake = FakeEmbeddingService()
    fake.sentiment_service._embedding_model = object()
    retriever = _retriever(fake)
    assert retriever._embedding_is_warm() is True
    assert fake.prewarm_calls == 0


def test_assemble_and_module_kick_trigger_process_prewarm(monkeypatch):
    """监听启动/上下文装配即触发进程级预热(22:39 首查冷窗口的根治)。"""
    import app.services.realtime.rag.embedding as emb

    calls = []

    class _FakeSvc:
        def prewarm(self) -> bool:
            calls.append(1)
            return True

    monkeypatch.setattr(emb, "RagEmbeddingService", lambda: _FakeSvc())
    monkeypatch.setattr(emb, "_prewarm_started", False)

    emb.kick_background_prewarm()
    deadline = time.time() + 5
    while not calls and time.time() < deadline:
        time.sleep(0.02)
    assert calls, "进程级预热未触发"

    emb.kick_background_prewarm()  # 二次调用不重复触发
    assert len(calls) == 1

    # assemble_generation_context 也会触发(重置标记后)
    monkeypatch.setattr(emb, "_prewarm_started", False)
    import sqlite3 as _sq

    from app.services.realtime.generation_context import assemble_generation_context

    conn = _sq.connect(":memory:")
    conn.row_factory = _sq.Row
    conn.execute(
        "CREATE TABLE conversations (id INTEGER PRIMARY KEY AUTOINCREMENT, account_wxid TEXT, "
        "display_name TEXT, username TEXT, is_deleted INTEGER DEFAULT 0, updated_at INTEGER)"
    )
    monkeypatch.setattr("app.db.connection.get_db", lambda: conn)
    assemble_generation_context({}, entrypoint="manual", account_wxid="wxid_a", display_name="无此人")
    deadline = time.time() + 5
    while len(calls) < 2 and time.time() < deadline:
        time.sleep(0.02)
    assert len(calls) == 2, "装配入口未触发进程级预热"


def test_load_failure_latch_retries_when_models_appear(monkeypatch):
    """onnxruntime 后装/模型后导出的场景:失败锁死不得永久生效。"""
    from app.services.analysis import sentiment_service as ss

    service = ss.SentimentService()  # @singleton 工厂,返回共享实例
    saved = (
        getattr(service, "_embedding_model", None),
        getattr(service, "_embedding_load_failed", False),
        getattr(service, "_embedding_model_path", None),
    )
    real_set_dim = type(service)._set_embedding_dimension_from_model
    try:
        service._embedding_model = None
        service._embedding_load_failed = True

        # 模型仍未就位:保持失败态,不尝试加载
        monkeypatch.setattr("app.services.analysis.onnx_inference.has_onnx_models", lambda: False)
        service._load_embedding_model()
        assert service._embedding_load_failed is True
        assert service._embedding_model is None

        # 模型就位(导出完成/依赖补装):解除锁死并完成加载
        class _FakeEngine:
            device_tag = "cpu"
            providers = ["CPUExecutionProvider"]

        monkeypatch.setattr("app.services.analysis.onnx_inference.has_onnx_models", lambda: True)
        monkeypatch.setattr(
            "app.services.analysis.onnx_inference.get_shared_engine",
            lambda name, device_mode=None: _FakeEngine(),
        )
        monkeypatch.setattr(type(service), "_set_embedding_dimension_from_model", lambda self: None)
        service._load_embedding_model()
        assert service._embedding_model is not None
        assert service._embedding_load_failed is False
    finally:
        service._embedding_model, service._embedding_load_failed, service._embedding_model_path = saved
        monkeypatch.setattr(type(service), "_set_embedding_dimension_from_model", real_set_dim, raising=False)
