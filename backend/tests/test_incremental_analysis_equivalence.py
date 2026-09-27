"""增量分析等价性验证——用户点名「详细检查全过程增量正确性」。

金标准对照：同一终态消息集，无论经历什么路径（冷跑 / 暖跑 / 增量导入后重跑 /
乱序插入 / 重复导入），分析产物必须与「全量消息一次冷跑」完全一致。

覆盖的产物面（八类）：
  speech_units / interaction_pairs / sessions / response_times /
  initiative_stats / word_counts / sentiment_cache / settings 两个缓存行。

嵌入确定性：monkeypatch 假编码器（sha1 分桶固定 seed 向量），CI 无模型可跑；
真模型模式另行 skipif 保护。float32 往返后 .tolist() 与冷跑逐 bit 相等，
浮点断言用 ==（这不是近似——是同值往返）。
"""

import json
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import sys

backend_root = Path(__file__).parent.parent
sys.path.insert(0, str(backend_root))

from app.db.connection import DatabaseConnection, get_db
from app.services.analysis.analysis_state import (
    get_analysis_freshness,
    mark_analysis_complete,
    mark_conversations_stale,
)
from app.services.analysis.embedding_cache_store import EmbeddingCacheStore
from app.services.analysis.feature_extraction_service import FeatureExtractionService
from app.services.analysis.sentiment_service import SentimentService

FAKE_DIM = 32


class FakeEncoder:
    """确定性假编码器：sha1(text) 分桶 → 固定 seed 正态向量 → L2 归一。"""

    encode_calls = 0

    def encode(self, texts, normalize_embeddings=True, show_progress_bar=False, batch_size=32):
        import hashlib

        import numpy as np

        FakeEncoder.encode_calls += 1
        vectors = []
        for text in texts:
            seed = int(hashlib.sha1(str(text).encode("utf-8")).hexdigest()[:12], 16)
            rng = np.random.default_rng(seed)
            vec = rng.normal(size=FAKE_DIM).astype(np.float32)
            if normalize_embeddings:
                norm = float(np.linalg.norm(vec))
                if norm > 0:
                    vec = vec / norm
            vectors.append(vec)
        return vectors


@pytest.fixture
def fake_embedding(monkeypatch):
    """把 SentimentService 的模型加载替换为假编码器（幂等安装）。

    注意 singleton 装饰器返回工厂函数——真类要经实例 __class__ 取。
    """
    FakeEncoder.encode_calls = 0

    def _fake_load(self):
        if self._embedding_model is None:
            self._embedding_model = FakeEncoder()
            self._embedding_load_failed = False
            self._embedding_device = "cpu"
            self._embedding_dimension = FAKE_DIM

    service = SentimentService()
    real_class = service.__class__
    monkeypatch.setattr(real_class, "_load_embedding_model", _fake_load)
    _fake_load(service)
    service._embedding_cache.clear()
    return FakeEncoder


@pytest.fixture
def test_db(tmp_path):
    """隔离 DB；顺带清 L2（表在测试库里，随 tmp_path 销毁）。"""
    DatabaseConnection.close()
    DatabaseConnection._db_path = None
    db_path = tmp_path / "chrono_incremental.db"
    conn = DatabaseConnection.initialize(str(db_path))
    yield conn
    DatabaseConnection.close()
    DatabaseConnection._db_path = None


BASE_TS = 1_700_000_000


def build_message_rows(n_messages=36):
    """构造消息集：交替发送者、3 个 >1800s 簇、跨睡眠窗间隙、type 混 1/3/34。

    返回 [(local_id, is_sender, message_type, content, timestamp), ...]，
    时间戳严格递增（乱序场景由插入顺序制造）。
    """
    rows = []
    ts = BASE_TS
    for i in range(n_messages):
        if i in (10, 22, 30):
            ts += 7200  # 会话间隙：>1800s 强制切分
        if i == 16:
            ts += 10 * 3600  # 跨睡眠窗（0-7 点）：强制切分
        ts += 40 + (i % 7) * 25
        msg_type = 1
        content = f"测试消息 {i}，今天聊聊近况和工作计划。"
        if i % 9 == 4:
            msg_type = 3
            content = "[图片]"
        elif i % 11 == 7:
            msg_type = 34
            content = "[语音]"
        rows.append((i + 1, i % 2, msg_type, content, ts))
    return rows


def import_messages(conversation_id, rows, mark_stale=True):
    """复刻 ingest 的写入语义：INSERT OR IGNORE + touched 打脏 + 会话计数刷新。

    返回实际插入条数（重复导入应为 0，与 _insert_message_batch 的
    cursor.rowcount 语义一致）。
    """
    conn = get_db()
    inserted = 0
    latest_ts = 0
    for local_id, is_sender, msg_type, content, ts in rows:
        cursor = conn.execute(
            """
            INSERT OR IGNORE INTO messages
            (conversation_id, local_id, talker, is_sender, message_type,
             content, timestamp, source, created_at)
            VALUES (?, ?, 'test_user', ?, ?, ?, ?, 'long', ?)
            """,
            (conversation_id, local_id, is_sender, msg_type, content, ts, int(time.time())),
        )
        if cursor.rowcount == 1:
            inserted += 1
            latest_ts = max(latest_ts, ts)
    if inserted:
        total = conn.execute(
            "SELECT COUNT(*) FROM messages WHERE conversation_id = ?", (conversation_id,)
        ).fetchone()[0]
        max_ts = conn.execute(
            "SELECT MAX(timestamp) FROM messages WHERE conversation_id = ?", (conversation_id,)
        ).fetchone()[0]
        conn.execute(
            "UPDATE conversations SET message_count = ?, updated_at = ? WHERE id = ?",
            (total, max_ts or latest_ts or int(time.time()), conversation_id),
        )
        if mark_stale:
            mark_conversations_stale([conversation_id])
    conn.commit()
    return inserted


_CONV_SEQ = iter(range(1000))


def create_conversation(display="测试联系人"):
    conn = get_db()
    username = f"test_user_{next(_CONV_SEQ)}"  # UNIQUE(account, username, platform)
    cursor = conn.execute(
        """
        INSERT INTO conversations
        (account_wxid, username, display_name, platform, created_at, updated_at)
        VALUES ('wxid_test', ?, ?, 'wechat', ?, ?)
        """,
        (username, display, BASE_TS, BASE_TS),
    )
    conn.commit()
    return cursor.lastrowid


def run_pipeline(conversation_id):
    """完整两阶段：特征提取 + 好感度（均强制全量语义）。"""
    features = FeatureExtractionService()
    features.extract_features(conversation_id)

    from app.services.analysis.affinity_analysis_service import AffinityAnalysisService

    affinity = AffinityAnalysisService()
    return affinity.analyze(conversation_id, force_reanalyze=True)


# ===================== 快照（八类产物，自增 id / 时间戳列忽略） =====================

def _rows(sql, params=()):
    return get_db().execute(sql, params).fetchall()


def _rank_map(conversation_id):
    """消息 id → 会话内序数（按 timestamp,id 排序）。

    自增 id 跨会话不可比；归一化后两库的结构产物才可对照。
    """
    rows = _rows(
        "SELECT id FROM messages WHERE conversation_id = ? ORDER BY timestamp, id",
        (conversation_id,),
    )
    return {row["id"]: rank for rank, row in enumerate(rows)}


def snapshot(conversation_id):
    snap = {}
    rank = _rank_map(conversation_id)

    def _norm_ids(message_ids_json):
        # 实际存储为 JSON 数组字符串（schema 注释写逗号分隔已过时）
        try:
            raw_ids = json.loads(str(message_ids_json))
        except (ValueError, TypeError):
            raw_ids = [x for x in str(message_ids_json).split(",") if x]
        return [rank.get(int(x), x) for x in raw_ids]

    snap["speech_units"] = sorted(
        (
            (r["first_message_timestamp"], r["sender"], _norm_ids(r["message_ids"]),
             r["last_message_timestamp"], r["message_count"])
            for r in _rows(
                "SELECT * FROM speech_units WHERE conversation_id = ?", (conversation_id,)
            )
        )
    )

    def _unit_anchor(unit_id):
        row = get_db().execute(
            "SELECT first_message_timestamp, message_ids FROM speech_units WHERE id = ?",
            (unit_id,),
        ).fetchone()
        return (row["first_message_timestamp"], _norm_ids(row["message_ids"])) if row else (None, [])

    pairs = []
    for r in _rows(
        "SELECT * FROM interaction_pairs WHERE conversation_id = ?", (conversation_id,)
    ):
        from_anchor = _unit_anchor(r["from_speech_unit_id"])
        to_anchor = _unit_anchor(r["to_speech_unit_id"])
        pairs.append((
            from_anchor, to_anchor, r["time_gap"], r["semantic_similarity"],
            r["from_polarity"], r["to_polarity"], r["from_intensity"], r["to_intensity"],
            r["is_negative_initiation"], r["is_empathetic_response"],
        ))
    snap["interaction_pairs"] = sorted(pairs, key=repr)

    snap["sessions"] = sorted(
        (
            r["start_time"], r["end_time"], r["message_count"], r["initiator"]
        )
        for r in _rows(
            "SELECT * FROM sessions WHERE conversation_id = ?", (conversation_id,)
        )
    )

    def _msg_anchor(message_id):
        row = get_db().execute(
            "SELECT timestamp FROM messages WHERE id = ?", (message_id,)
        ).fetchone()
        return row["timestamp"] if row else None

    rt = []
    for r in _rows(
        "SELECT * FROM response_times WHERE conversation_id = ?", (conversation_id,)
    ):
        rt.append((
            _msg_anchor(r["sent_message_id"]), _msg_anchor(r["reply_message_id"]),
            r["response_time_seconds"], r["is_abnormal"], r["abnormal_reason"],
        ))
    snap["response_times"] = sorted(rt, key=repr)

    init = _rows(
        "SELECT * FROM initiative_stats WHERE conversation_id = ?", (conversation_id,)
    )
    snap["initiative_stats"] = [
        (r["total_sessions"], r["user_initiated_sessions"],
         r["other_initiated_sessions"], r["initiative_rate"])
        for r in init
    ]

    snap["word_counts"] = sorted(
        (r["user_char_count"], r["other_char_count"], r["char_ratio"])
        for r in _rows(
            "SELECT * FROM word_counts WHERE conversation_id = ? AND session_id IS NULL",
            (conversation_id,),
        )
    )

    snap["sentiment_cache"] = sorted(
        (rank.get(r["message_id"], r["message_id"]), r["polarity"], r["intensity"])
        for r in _rows(
            "SELECT * FROM sentiment_cache WHERE message_id IN "
            "(SELECT id FROM messages WHERE conversation_id = ?)",
            (conversation_id,),
        )
    )

    _VOLATILE_KEYS = {
        "preprocessing_timestamp", "preprocessing_duration_ms",
        "analysis_timestamp", "analysis_duration_ms",
        "conversation_id", "task_id",
        "cache_updated_at", "cache_created_at",
    }

    def _strip_volatile(value):
        """深度剥离易变字段（conversation_id 等会嵌在 confidence_meta 里）。"""
        if isinstance(value, dict):
            return {
                k: _strip_volatile(v)
                for k, v in value.items() if k not in _VOLATILE_KEYS
            }
        if isinstance(value, list):
            return [_strip_volatile(item) for item in value]
        return value

    def _settings_json(key):
        row = get_db().execute(
            "SELECT value FROM settings WHERE key = ?", (key,)
        ).fetchone()
        if not row:
            return None
        return _strip_volatile(json.loads(row["value"]))

    snap["preprocessing_stats"] = _settings_json(f"preprocessing_stats_v2_{conversation_id}")
    snap["affinity_scores"] = _settings_json(f"affinity_scores_{conversation_id}")
    return snap


DIFF_KEYS_TRACKER = []


def _first_diff_path(a, b, path="$"):
    """递归定位第一个不一致点，返回可读路径与两侧值。"""
    if isinstance(a, dict) and isinstance(b, dict):
        for key in sorted(set(a) | set(b)):
            if key not in a or key not in b:
                return f"{path}.{key}", a.get(key, "<缺>"), b.get(key, "<缺>")
            hit = _first_diff_path(a[key], b[key], f"{path}.{key}")
            if hit:
                return hit
        return None
    if isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            return f"{path}[len]", len(a), len(b)
        for i, (x, y) in enumerate(zip(a, b)):
            hit = _first_diff_path(x, y, f"{path}[{i}]")
            if hit:
                return hit
        return None
    if a != b:
        return path, a, b
    return None


def assert_snapshots_equal(golden, candidate, label):
    assert set(golden.keys()) == set(candidate.keys()), f"{label}: 产物面不一致"
    for key in golden:
        if golden[key] != candidate[key]:
            hit = _first_diff_path(golden[key], candidate[key], key)
            if hit:
                diff_path, g_val, c_val = hit
                pytest.fail(
                    f"{label}: 产物 [{key}] 首个差异 @ {diff_path}\n"
                    f"金标准: {repr(g_val)[:300]}\n实际:   {repr(c_val)[:300]}"
                )
            pytest.fail(
                f"{label}: 产物 [{key}] 不一致\n金标准: {repr(golden[key])[:400]}\n"
                f"实际:   {repr(candidate[key])[:400]}"
            )


# ===================== 场景矩阵 =====================

class TestIncrementalEquivalence:

    def test_01_cold_run_writes_l2(self, test_db, fake_embedding):
        """① 首跑冷：跑通全管线且 L2 有行写入。"""
        conv = create_conversation()
        import_messages(conv, build_message_rows())
        run_pipeline(conv)
        stats = EmbeddingCacheStore.stats()
        assert stats["rows"] > 0, "冷跑后 embedding_cache 应有向量"
        assert snapshot(conv)["speech_units"], "应产出发言单元"

    def test_02_warm_rerun_equivalent_zero_encode(self, test_db, fake_embedding):
        """② 暖跑（模拟重启）：清 L1 后重跑，产物全等且零模型编码。"""
        conv = create_conversation()
        import_messages(conv, build_message_rows())
        run_pipeline(conv)
        cold = snapshot(conv)

        # 模拟进程重启：L1 清空（L2 在库里），编码计数归零
        SentimentService()._embedding_cache.clear()
        FakeEncoder.encode_calls = 0

        run_pipeline(conv)
        warm = snapshot(conv)
        assert_snapshots_equal(cold, warm, "暖跑")
        assert FakeEncoder.encode_calls == 0, (
            f"暖跑不应触发模型编码（实际 {FakeEncoder.encode_calls} 次）——L2 未生效？"
        )

    def test_03_incremental_import_then_rerun(self, test_db, fake_embedding):
        """③ 增量导入（含乱序回填）后重跑 == 全量一次冷跑（金标准）。"""
        rows = build_message_rows()
        batch1, batch2 = rows[:20], rows[20:]

        # 增量路径：先导入 20 条并分析
        conv = create_conversation()
        assert import_messages(conv, batch1) == 20
        run_pipeline(conv)
        assert get_analysis_freshness(conv)["stale"] is False

        # 乱序回填：batch2 里挑一条早于水位的时间戳插到最前（仍属新消息）
        out_of_order = (999, 1, 1, "补录的乱序消息，聊聊周末安排。", batch1[0][4] + 5)
        assert import_messages(conv, batch2 + [out_of_order]) == len(batch2) + 1
        freshness = get_analysis_freshness(conv)
        assert freshness["stale"] is True, "导入新消息后应标记待更新"
        assert freshness["pending_message_count"] == len(batch2) + 1

        run_pipeline(conv)
        incremental = snapshot(conv)
        assert get_analysis_freshness(conv)["stale"] is False, "分析完成后应清脏"

        # 金标准：另建会话，全量消息一次冷跑
        golden_conv = create_conversation(display="金标准")
        import_messages(golden_conv, rows + [out_of_order])
        run_pipeline(golden_conv)
        golden = snapshot(golden_conv)

        assert_snapshots_equal(golden, incremental, "增量导入后重跑")

    def test_04_duplicate_import_no_stale_no_change(self, test_db, fake_embedding):
        """④ 重复导入：OR IGNORE 全跳过 → 不打脏、产物不变。"""
        conv = create_conversation()
        rows = build_message_rows()
        import_messages(conv, rows)
        run_pipeline(conv)
        before = snapshot(conv)

        assert import_messages(conv, rows) == 0, "重复导入应全部跳过"
        assert get_analysis_freshness(conv)["stale"] is False, "全 skip 不应打脏"
        assert snapshot(conv) == before, "产物不应变化"

    def test_05_out_of_order_vs_ordered_insert(self, test_db, fake_embedding):
        """⑤ 乱序插入 vs 有序插入：同终态消息集产物相等。"""
        rows = build_message_rows()

        conv_ordered = create_conversation(display="有序")
        import_messages(conv_ordered, rows)
        run_pipeline(conv_ordered)

        # 乱序：整段交错插入（第 2 段先插，第 1 段后插）
        conv_shuffled = create_conversation(display="乱序")
        import_messages(conv_shuffled, rows[18:])
        import_messages(conv_shuffled, rows[:18])
        run_pipeline(conv_shuffled)

        assert_snapshots_equal(
            snapshot(conv_ordered), snapshot(conv_shuffled), "乱序插入"
        )

    def test_06_realtime_row_reconciled(self, test_db, fake_embedding):
        """⑥ realtime 行并入后再导入：对账去冗余，产物 == 纯 long 库。"""
        rows = build_message_rows()

        # 纯 long 金标准
        golden_conv = create_conversation(display="纯long金标准")
        import_messages(golden_conv, rows)
        run_pipeline(golden_conv)

        # realtime 先行：local_id NULL 不受唯一索引约束，同签名 ±59s
        conv = create_conversation(display="realtime对账")
        conn = get_db()
        for local_id, is_sender, msg_type, content, ts in rows[:6]:
            conn.execute(
                """
                INSERT INTO messages
                (conversation_id, local_id, talker, is_sender, message_type,
                 content, timestamp, source, created_at)
                VALUES (?, NULL, 'test_user', ?, ?, ?, ?, 'realtime', ?)
                """,
                (conv, is_sender, msg_type, content, ts + 10, int(time.time())),
            )
        conn.commit()

        # 导入 long 行后复刻对账：删除被 long 覆盖的同签名 realtime 行
        import_messages(conv, rows)
        conn.execute(
            """
            DELETE FROM messages
            WHERE conversation_id = ? AND source = 'realtime'
              AND EXISTS (
                  SELECT 1 FROM messages m
                  WHERE m.conversation_id = messages.conversation_id
                    AND m.source = 'long'
                    AND m.is_sender = messages.is_sender
                    AND m.message_type = messages.message_type
                    AND m.content = messages.content
                    AND ABS(m.timestamp - messages.timestamp) <= 59
              )
            """,
            (conv,),
        )
        conn.commit()

        total = conn.execute(
            "SELECT COUNT(*) FROM messages WHERE conversation_id = ?", (conv,)
        ).fetchone()[0]
        assert total == len(rows), f"对账后消息数应等于 long 条数（实际 {total}）"

        run_pipeline(conv)
        assert_snapshots_equal(snapshot(golden_conv), snapshot(conv), "realtime对账")

    def test_07_empty_conversation(self, test_db, fake_embedding):
        """⑦ 空会话：不炸、统计为零、完成后清脏。"""
        conv = create_conversation(display="空会话")
        mark_conversations_stale([conv])
        run_pipeline(conv)
        freshness = get_analysis_freshness(conv)
        assert freshness["stale"] is False
        assert freshness["pending_message_count"] == 0

    def test_08_l2_key_isolation(self, test_db, fake_embedding):
        """⑧⑨ 键隔离：model/device 任一不同即 miss；零向量不落库。"""
        store_cpu = EmbeddingCacheStore("repo-A", "cpu", FAKE_DIM)
        store_cuda = EmbeddingCacheStore("repo-A", "cuda", FAKE_DIM)
        store_other = EmbeddingCacheStore("repo-B", "cpu", FAKE_DIM)

        texts = ["键隔离测试文本甲", "键隔离测试文本乙"]
        vectors = [[0.1] * FAKE_DIM, [0.2] * FAKE_DIM]
        store_cpu.batch_store(texts, vectors)

        assert set(store_cpu.batch_lookup(texts)) == set(texts)
        assert store_cuda.batch_lookup(texts) == {}, "设备不同不应命中"
        assert store_other.batch_lookup(texts) == {}, "模型不同不应命中"

        # 维度不符视为 miss（防御旧宽度残留）
        store_odd = EmbeddingCacheStore("repo-A", "cpu", FAKE_DIM + 1)
        assert store_odd.batch_lookup(texts) == {}

        # 空文本/空向量不落库
        assert store_cpu.batch_store(["", "  "], [[0.0] * FAKE_DIM] * 2) == 0
        assert store_cpu.batch_store(["零向量文本"], [[0.0] * FAKE_DIM]) == 0

    def test_09_stale_lifecycle(self, test_db, fake_embedding):
        """stale 生命周期：打脏删除 preprocessing_stats 缓存行；完成恢复。"""
        conv = create_conversation()
        import_messages(conv, build_message_rows())
        run_pipeline(conv)

        conn = get_db()
        key = f"preprocessing_stats_v2_{conv}"
        assert conn.execute(
            "SELECT 1 FROM settings WHERE key = ?", (key,)
        ).fetchone(), "分析后应有统计缓存行"

        mark_conversations_stale([conv])
        assert conn.execute(
            "SELECT 1 FROM settings WHERE key = ?", (key,)
        ).fetchone() is None, "打脏应删除统计缓存行（既有陈旧 bug 的修复）"
        assert get_analysis_freshness(conv)["stale"] is True

        mark_analysis_complete(conv)
        freshness = get_analysis_freshness(conv)
        assert freshness["stale"] is False
        assert freshness["pending_message_count"] == 0

    @pytest.mark.skipif(
        not SentimentService().has_local_embedding_model(),
        reason="本地无嵌入模型（CI 用假编码器覆盖，真模型等价另行验证）",
    )
    def test_10_real_model_roundtrip(self, test_db):
        """真模型模式：float32 往返与直算逐值相等（bit 级）。"""
        from app.services.model_paths import EMBEDDING_MODEL_REPO_ID

        service = SentimentService()
        service._load_embedding_model()
        texts = ["真实模型往返验证一", "真实模型往返验证二"]
        direct = service._embedding_model.encode(
            texts, normalize_embeddings=True, show_progress_bar=False
        )
        stored = EmbeddingCacheStore(
            EMBEDDING_MODEL_REPO_ID,
            service._embedding_device,
            len(direct[0]),
        )
        stored.batch_store(texts, [v.tolist() for v in direct])
        looked_up = stored.batch_lookup(texts)
        for i, text in enumerate(texts):
            assert looked_up[text] == direct[i].tolist(), "float32 往返必须逐值相等"
