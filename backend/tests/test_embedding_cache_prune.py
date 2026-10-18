"""嵌入 L2 缓存淘汰测试（embedding_cache 无界增长问题的封顶机制）。"""

import sys
from pathlib import Path

import pytest


backend_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(backend_dir))


from app.db.connection import DatabaseConnection
from app.services.analysis import embedding_cache_store as cache_mod
from app.services.analysis.embedding_cache_store import EmbeddingCacheStore


@pytest.fixture
def isolated_db(tmp_path):
    DatabaseConnection.close()
    DatabaseConnection._db_path = None
    conn = DatabaseConnection.initialize(str(tmp_path / "chrono_trace_test.db"))
    yield conn
    DatabaseConnection.close()
    DatabaseConnection._db_path = None


def seed_rows(conn, n, dim=4):
    """直插 n 行向量（绕过 store 的 settings 门控，纯表级行为测试）。"""
    import struct

    rows = [
        (f"sha{i:08d}", "test-model", "cpu", dim, struct.pack(f"<{dim}f", *([0.1] * dim)), 1000 + i)
        for i in range(n)
    ]
    conn.executemany(
        "INSERT INTO embedding_cache (content_sha1, model, device, dim, vector, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        rows,
    )
    conn.commit()
    return rows


class TestPrune:
    def test_prune_keeps_newest_rows(self, isolated_db):
        rows = seed_rows(isolated_db, 10)
        deleted = EmbeddingCacheStore.prune(max_rows=3)
        assert deleted == 7
        kept = isolated_db.execute("SELECT content_sha1 FROM embedding_cache ORDER BY id").fetchall()
        assert [r["content_sha1"] for r in kept] == [rows[i][0] for i in (7, 8, 9)]

    def test_prune_noop_when_under_limit(self, isolated_db):
        seed_rows(isolated_db, 5)
        assert EmbeddingCacheStore.prune(max_rows=100) == 0
        assert isolated_db.execute("SELECT COUNT(*) AS n FROM embedding_cache").fetchone()["n"] == 5

    def test_prune_invalid_limit(self, isolated_db):
        seed_rows(isolated_db, 3)
        assert EmbeddingCacheStore.prune(max_rows=0) == 0
        assert EmbeddingCacheStore.prune(max_rows=-1) == 0

    def test_maybe_prune_throttled(self, isolated_db, monkeypatch):
        """节流：窗口期内第二次调用不触发 DELETE（时间戳短路）。"""
        monkeypatch.setattr(cache_mod, "EMBEDDING_CACHE_MAX_ROWS", 5)
        seed_rows(isolated_db, 10)
        monkeypatch.setattr(cache_mod, "_last_prune_at", 0.0)
        # 时间冻结（time.time 固定）→ 首次已过节流窗，执行并把时间戳推到当前
        monkeypatch.setattr(cache_mod, "time", type("T", (), {"time": staticmethod(lambda: 10_000.0)}))
        cache_mod._maybe_prune()  # 10000 - 0 > 300 → 执行，10 行删至 5
        assert isolated_db.execute("SELECT COUNT(*) AS n FROM embedding_cache").fetchone()["n"] == 5
        # 再插超限行后调用：时间仍为 10000，节流短路，不删
        seed_rows(isolated_db, 5)
        cache_mod._maybe_prune()
        assert isolated_db.execute("SELECT COUNT(*) AS n FROM embedding_cache").fetchone()["n"] == 10


class TestStatsAndPurge:
    def test_stats_reports_rows_and_bytes(self, isolated_db):
        seed_rows(isolated_db, 3)
        stats = EmbeddingCacheStore.stats()
        assert stats["rows"] == 3
        assert stats["bytes"] == 3 * 16  # 4 维 float32
        assert stats["by_model"] == [{"model": "test-model", "device": "cpu", "rows": 3}]

    def test_purge_all(self, isolated_db):
        seed_rows(isolated_db, 3)
        assert EmbeddingCacheStore.purge() == 3
        assert EmbeddingCacheStore.stats()["rows"] == 0
