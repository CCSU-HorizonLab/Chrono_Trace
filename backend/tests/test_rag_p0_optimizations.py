"""RAG P0 优化回归：队列 FIFO/不丢任务、设置缓存失效、向量缓存。"""
from __future__ import annotations

import sys
from pathlib import Path

backend_root = Path(__file__).parent.parent
sys.path.insert(0, str(backend_root))
sys.path.insert(0, str(Path(__file__).parent))

import time

import app.services.realtime.rag.config as rag_config
from app.services.realtime.rag import indexer as rag_indexer
from app.services.realtime.rag.indexer import RagIndexQueue
from app.services.realtime.rag.retriever import (
    _VECTOR_CACHE,
    _cache_get,
    _cache_put,
    invalidate_vector_cache,
)


def _reset_queue():
    with RagIndexQueue._lock:
        RagIndexQueue._pending.clear()
        RagIndexQueue._pending_order.clear()
        RagIndexQueue._fact_pending.clear()
        RagIndexQueue._fact_order.clear()
    RagIndexQueue._worker = None


def test_queue_fifo_order(monkeypatch):
    """入队顺序 = 执行顺序（此前 set.pop 乱序）。"""
    _reset_queue()
    processed: list[tuple] = []
    monkeypatch.setattr(rag_indexer, "load_rag_settings", lambda *a, **k: {"rag_enabled": True})
    monkeypatch.setattr(
        rag_indexer, "RagIndexer",
        lambda: type("StubIndexer", (), {
            "rebuild_contact_index": staticmethod(
                lambda **kw: processed.append((kw["account_wxid"], kw["conversation_id"])) or {}
            ),
        }),
    )
    RagIndexQueue.enqueue("wxid_a", 1)
    RagIndexQueue.enqueue("wxid_a", 2)
    RagIndexQueue.enqueue("wxid_a", 3)

    # 直接同步跑 worker 循环（队列空自动退出）
    rag_indexer.time.sleep = lambda *_: None
    RagIndexQueue._run()

    assert processed == [("wxid_a", 1), ("wxid_a", 2), ("wxid_a", 3)]


def test_queue_keeps_tasks_when_disabled(monkeypatch):
    """rag_enabled=false：任务保留在队列等开关恢复（此前 pop 后直接丢弃）。"""
    _reset_queue()
    monkeypatch.setattr(rag_indexer, "load_rag_settings", lambda *a, **k: {"rag_enabled": False})
    assert RagIndexQueue._pop_job() is None
    RagIndexQueue.enqueue("wxid_a", 9)
    assert RagIndexQueue._pop_job() is None  # 不弹出
    with RagIndexQueue._lock:
        assert ("wxid_a", 9) in RagIndexQueue._pending  # 任务仍在
    # 开关恢复后可正常弹出
    monkeypatch.setattr(rag_indexer, "load_rag_settings", lambda *a, **k: {"rag_enabled": True})
    assert RagIndexQueue._pop_job() == ("wxid_a", 9, "rebuild")
    assert RagIndexQueue._pop_job() == "empty"


def test_queue_requeue_goes_to_front(monkeypatch):
    _reset_queue()
    monkeypatch.setattr(rag_indexer, "load_rag_settings", lambda *a, **k: {"rag_enabled": True})
    RagIndexQueue.enqueue("wxid_a", 1)
    RagIndexQueue.enqueue("wxid_a", 2)
    RagIndexQueue.requeue("wxid_a", 1)  # 已在集合中 → 不变（去重）
    with RagIndexQueue._lock:
        RagIndexQueue._pending.discard(("wxid_a", 1))  # 模拟已弹出
    RagIndexQueue.requeue("wxid_a", 1)  # 队头重试
    assert RagIndexQueue._pop_job() == ("wxid_a", 1, "rebuild")


def test_settings_cache_invalidates_on_write(tmp_path, monkeypatch):
    """mtime 门控：文件变化后缓存失效。"""
    settings_file = tmp_path / "settings.json"
    settings_file.write_text('{"rag_enabled": false}', encoding="utf-8")
    monkeypatch.setattr(
        "app.services.wechat.account_settings.default_settings_path",
        lambda: settings_file,
    )
    rag_config._settings_file_cache["key"] = None
    rag_config._settings_file_cache["payload"] = None

    first = rag_config.load_rag_settings()
    assert first["rag_enabled"] is False
    assert rag_config._settings_file_cache["payload"] is not None  # 已缓存

    # 修改文件（确保 mtime_ns 变化）
    time.sleep(0.01)
    settings_file.write_text('{"rag_enabled": true}', encoding="utf-8")
    second = rag_config.load_rag_settings()
    assert second["rag_enabled"] is True  # 缓存已失效重读


def test_vector_cache_put_get_invalidate():
    invalidate_vector_cache()
    key = ("wxid_a", 1, "facts", "m", 768)
    _cache_put(key, {"items": [{"id": 5, "vector": [0.1]}]})
    assert _cache_get(key) == {"items": [{"id": 5, "vector": [0.1]}]}
    assert key in _VECTOR_CACHE

    invalidate_vector_cache("wxid_a", 1)
    assert key not in _VECTOR_CACHE
    assert _cache_get(key) is None

    _cache_put(key, {"items": []})
    invalidate_vector_cache()  # 全清
    assert not _VECTOR_CACHE


def test_vector_cache_lru_eviction():
    invalidate_vector_cache()
    for i in range(rag_indexer and 10):
        _cache_put(("wxid_a", i, "facts", "m", 768), {"items": []})
    # 上限 8：最早插入的被淘汰
    from app.services.realtime.rag.retriever import _VECTOR_CACHE_MAX, _VECTOR_CACHE_ORDER
    assert len(_VECTOR_CACHE_ORDER) <= _VECTOR_CACHE_MAX
    assert ("wxid_a", 0, "facts", "m", 768) not in _VECTOR_CACHE
    invalidate_vector_cache()
