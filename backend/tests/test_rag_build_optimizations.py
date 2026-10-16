"""RAG 构建提速与可见性回归——预批嵌入调用形态 / 孤儿状态回收。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # backend/ 导入根

import sqlite3

import pytest

import app.services.realtime.rag.indexer as idxmod
from app.services.realtime.rag.embedding import RagEmbeddingUnavailable
from app.services.realtime.rag.indexer import RagIndexer, RagIndexQueue
from app.services.realtime.rag.segmenter import RagSegmenter
from app.services.realtime.rag.semantic_memory import SemanticFactExtractor


class _StubEmbedding:
    """确定性桩：向量按文本长度稳定生成，记录调用次数与批量规模。"""

    def __init__(self, fail: bool = False):
        self.calls = 0
        self.batch_sizes: list[int] = []
        self.fail = fail

    def embed_texts(self, texts):
        self.calls += 1
        self.batch_sizes.append(len(texts))
        if self.fail:
            raise RagEmbeddingUnavailable("stub unavailable")
        return [[float(len(t) % 17), 1.0, 0.5, 0.25] for t in texts]


def _make_indexer(monkeypatch, embed_stub) -> RagIndexer:
    """绕过重量级依赖构造索引器：内存库 + 桩嵌入 + 真分段/语义抽取。"""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE sessions (id INT, conversation_id INT, start_time INT, end_time INT, message_count INT, initiator INT)")
    conn.execute("CREATE TABLE rag_facts (id INTEGER PRIMARY KEY, status TEXT, enabled INT)")
    conn.execute("INSERT INTO rag_facts VALUES (1, 'active', 1)")
    monkeypatch.setattr(idxmod, "load_rag_settings", lambda *a, **k: {"rag_fact_shadow_enabled": True})

    facts_rows: list[dict] = []

    class _Store:
        pass

    store = _Store()
    store.conn = conn

    def _upsert_fact(**kw):
        facts_rows.append(kw)
        return 1  # 命中 rag_facts id=1 active/enabled=1

    store.upsert_fact = _upsert_fact

    indexer = RagIndexer.__new__(RagIndexer)
    indexer.store = store
    indexer.structured_fact_extractor = None
    indexer.segmenter = RagSegmenter()
    indexer.embedding_service = embed_stub
    indexer.semantic_fact_extractor = SemanticFactExtractor(embed_stub, indexer.segmenter)
    indexer._facts_rows = facts_rows
    return indexer


def _synthetic_messages(count: int):
    """每小时两条消息——按时间间隔切出 ~count 个段。"""
    base = 1_700_000_000
    messages = []
    mid = 0
    for i in range(count):
        for j, sender in enumerate((0, 1)):
            mid += 1
            messages.append(
                {
                    "id": mid,
                    "is_sender": sender,
                    "content": f"第{i}轮消息{j}，聊聊最近的安排和打算",
                    "timestamp": base + i * 7200 + j * 60,
                }
            )
    return messages


def _expected_segments(messages) -> int:
    """与 _build_documents 同口径数段（sessions 参考为空表 → 传空）。"""
    return len(RagSegmenter().segment(messages, conversation_id=1, sessions=[]))


def test_prebatch_embedding_collapses_per_segment_calls(monkeypatch):
    """语义抽取候选句跨段合批：嵌入调用次数 ≤ 段块数+原型加载（而非每段一次）。"""
    embed = _StubEmbedding()
    indexer = _make_indexer(monkeypatch, embed)
    messages = _synthetic_messages(300)  # ≥ 3 个块（SEMANTIC_CHUNK_SEGMENTS=128）
    conversation = {"display_name": "测试联系人", "username": "wxid_t", "message_count": len(messages)}

    docs = indexer._build_documents("wxid_me", 1, conversation, messages)

    n_segments = _expected_segments(messages)
    chunks = (n_segments + RagIndexer.SEMANTIC_CHUNK_SEGMENTS - 1) // RagIndexer.SEMANTIC_CHUNK_SEGMENTS
    # 逐段路径会调 ≥ n_segments 次；合批后只有块数 + 原型向量加载级别
    assert embed.calls <= chunks + 2
    assert embed.calls < n_segments
    # 主体文档仍在：每段固定产出话题段 + 证据摘录两份
    assert len([d for d in docs if d["doc_type"] == "topic_segment"]) == n_segments
    assert len([d for d in docs if d["doc_type"] == "evidence_excerpt"]) == n_segments


def test_prebatch_embedding_failure_falls_back_without_crash(monkeypatch):
    """嵌入不可用：整块退 marker 兜底，构建不中断（与逐段失败口径一致）。"""
    embed = _StubEmbedding(fail=True)
    indexer = _make_indexer(monkeypatch, embed)
    messages = _synthetic_messages(20)
    conversation = {"display_name": "测试联系人", "username": "wxid_t", "message_count": len(messages)}

    docs = indexer._build_documents("wxid_me", 1, conversation, messages)

    assert docs, "嵌入失败仍应产出文档（topic/excerpt 不依赖语义抽取向量）"
    n_segments = _expected_segments(messages)
    assert len([d for d in docs if d["doc_type"] == "topic_segment"]) == n_segments


def test_semantic_split_matches_legacy_extract(monkeypatch):
    """collect+score 两阶段与单段 extract 同口径（拆分重构不改判分）。"""
    embed = _StubEmbedding()
    indexer = _make_indexer(monkeypatch, embed)
    messages = _synthetic_messages(8)
    conversation = {"display_name": "测试联系人", "username": "wxid_t", "message_count": len(messages)}

    indexer._build_documents("wxid_me", 1, conversation, messages)

    # 兼容入口逐段重算（同桩向量 → 确定性），全集口径应与预批路径一致
    segments = RagSegmenter().segment(messages, conversation_id=1, sessions=[])
    legacy = SemanticFactExtractor(_StubEmbedding(), RagSegmenter())
    expected = {
        (f.memory_kind, f.source_window_start_ts, f.source_window_end_ts)
        for seg in segments
        for f in legacy.extract(seg)
    }
    got = {
        (r["kind"], r["source_window"]["start_ts"], r["source_window"]["end_ts"])
        for r in indexer._facts_rows
    }
    assert got == expected


def test_orphaned_indexing_requeued_on_worker_start(monkeypatch):
    """进程重启后孤儿 indexing 状态复位 pending 并重新入队（ready 不动）。"""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        "CREATE TABLE rag_index_status (account_wxid TEXT, conversation_id INT, status TEXT)"
    )
    conn.execute("INSERT INTO rag_index_status VALUES ('wx_a', 7, 'indexing')")
    conn.execute("INSERT INTO rag_index_status VALUES ('wx_a', 8, 'ready')")
    monkeypatch.setattr(idxmod, "get_db", lambda: conn)
    monkeypatch.setattr(RagIndexQueue, "_orphans_recovered", False)
    enqueued: list[tuple] = []
    monkeypatch.setattr(RagIndexQueue, "enqueue", lambda a, c: enqueued.append((a, c)))

    RagIndexQueue._recover_orphaned_indexing()

    statuses = {
        r["conversation_id"]: r["status"]
        for r in conn.execute("SELECT conversation_id, status FROM rag_index_status")
    }
    assert statuses[7] == "pending"
    assert statuses[8] == "ready"
    assert enqueued == [("wx_a", 7)]

    # 幂等：二次调用不再入队（进程内一次性）
    RagIndexQueue._recover_orphaned_indexing()
    assert enqueued == [("wx_a", 7)]
    conn.close()


def test_status_badge_counts_only_live_activity(monkeypatch):
    """徽标口径：已就绪数 DB 实际行；构建中只认 live 活动，不数历史 pending 残留。"""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        "CREATE TABLE conversations (id INTEGER PRIMARY KEY, account_wxid TEXT, "
        "display_name TEXT, username TEXT, is_deleted INTEGER DEFAULT 0, updated_at INTEGER)"
    )
    conn.execute(
        "CREATE TABLE rag_index_status (account_wxid TEXT, conversation_id INT, status TEXT, "
        "document_count INT DEFAULT 0, vector_count INT DEFAULT 0, last_indexed_at INT, "
        "last_error TEXT, storage_bytes INT DEFAULT 0, enabled INT DEFAULT 1, "
        "fact_read_mode TEXT)"
    )
    conn.execute(
        "CREATE TABLE rag_facts (id INTEGER PRIMARY KEY, account_wxid TEXT, "
        "conversation_id INT, kind TEXT, content TEXT, status TEXT, enabled INT)"
    )
    # 1 个 ready + 638 个历史脏 pending（重启后内存队列已丢，无人会构建它们）
    conn.execute("INSERT INTO conversations VALUES (1, 'acc', '张三', 'wxid_z', 0, 1)")
    conn.execute(
        "INSERT INTO rag_index_status (account_wxid, conversation_id, status) "
        "VALUES ('acc', 1, 'ready')"
    )
    conn.executemany(
        "INSERT INTO rag_index_status (account_wxid, conversation_id, status) "
        "VALUES ('acc', ?, 'pending')",
        [(i,) for i in range(100, 738)],
    )

    monkeypatch.setattr("app.db.connection.get_db", lambda: conn)
    monkeypatch.setattr(
        "app.services.realtime.rag.indexer.get_active_and_queued",
        lambda: {},  # 队列空：无构建无排队
    )

    from app.webview.api.rag_admin import RagAdminApiMixin

    class _Bridge(RagAdminApiMixin):
        settings = {"rag_enabled": True}

        def _resolve_account_wxid(self, account_wxid: str = "") -> str:
            return account_wxid or "acc"

    result = _Bridge().get_rag_status("acc")
    assert result["ok"] is True
    assert result["ready_count"] == 1
    assert result["building_count"] == 0  # 638 个脏 pending 不冒充构建中
    assert result["status_counts"]["pending"] == 638  # 诊断口径保留原值

    # live 活动（1 构建中 + 2 排队）如实计入徽标
    monkeypatch.setattr(
        "app.services.realtime.rag.indexer.get_active_and_queued",
        lambda: {("acc", 1): "building", ("acc", 2): "queued", ("acc", 3): "queued"},
    )
    result = _Bridge().get_rag_status("acc")
    assert result["building_count"] == 3
    conn.close()


def test_indexed_contact_stays_visible_beyond_recency_limit(monkeypatch):
    """可见性：已建索引的低频联系人不被 LIMIT 挤出列表（2234 联系人实测）。"""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        "CREATE TABLE conversations (id INTEGER PRIMARY KEY, account_wxid TEXT, "
        "display_name TEXT, username TEXT, is_deleted INTEGER DEFAULT 0, updated_at INTEGER)"
    )
    conn.execute(
        "CREATE TABLE rag_index_status (account_wxid TEXT, conversation_id INT, status TEXT, "
        "document_count INT DEFAULT 0, vector_count INT DEFAULT 0, last_indexed_at INT, "
        "last_error TEXT, storage_bytes INT DEFAULT 0, enabled INT DEFAULT 1, "
        "fact_read_mode TEXT)"
    )
    # 老联系人已建好索引但会话很久没动（updated_at 最小）；
    # 20 个更新但从未建索引的联系人排在纯时间序前面
    conn.execute("INSERT INTO conversations VALUES (1, 'acc', '赵六', 'wxid_zl', 0, 100)")
    conn.execute(
        "INSERT INTO rag_index_status (account_wxid, conversation_id, status, last_indexed_at) "
        "VALUES ('acc', 1, 'ready', 999)"
    )
    conn.executemany(
        "INSERT INTO conversations VALUES (?, 'acc', ?, ?, 0, ?)",
        [(i, f"新联系人{i}", f"wxid_{i}", 200 + i) for i in range(10, 30)],
    )

    monkeypatch.setattr("app.db.connection.get_db", lambda: conn)
    monkeypatch.setattr(
        "app.services.realtime.rag.indexer.get_active_and_queued", lambda: {}
    )

    from app.webview.api.rag_admin import RagAdminApiMixin

    class _Bridge(RagAdminApiMixin):
        settings = {"rag_enabled": True}

        def _resolve_account_wxid(self, account_wxid: str = "") -> str:
            return account_wxid or "acc"

    # limit=5：纯 updated_at 排序会把 conv 1 挤出 → 列表徽标与实际状态对不上
    result = _Bridge().get_rag_status("acc", 5)
    ids = [item["conversation_id"] for item in result["items"]]
    assert 1 in ids
    ready_in_items = [i for i in ids if result["items"][ids.index(i)]["status"] == "ready"]
    assert result["ready_count"] == len(ready_in_items)  # 徽标与列表口径一致
    conn.close()
