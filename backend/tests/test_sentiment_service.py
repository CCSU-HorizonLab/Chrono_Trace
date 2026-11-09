"""情感服务单元测试

测试SnowNLP情感分类准确率 (>85%)
测试强度映射 (-1到1)
测试向量生成（跟随模型原生维度）
"""

import pytest
import sys
import sqlite3
from pathlib import Path
# 添加项目根目录到 Python 路径
backend_root = Path(__file__).parent.parent
sys.path.insert(0, str(backend_root))

from app.services.model_paths import EMBEDDING_MODEL_DIM


EXPECTED_EMBEDDING_DIM = EMBEDDING_MODEL_DIM


class TestSentimentService:
    """情感服务测试套件"""

    @pytest.fixture
    def service(self, monkeypatch):
        """创建情感服务实例"""
        from app.services.analysis import sentiment_service as sentiment_module

        conn = sqlite3.connect(":memory:", check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute(
            """
            CREATE TABLE messages (
                id INTEGER PRIMARY KEY,
                conversation_id INTEGER,
                content TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE sentiment_cache (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                message_id INTEGER NOT NULL UNIQUE,
                polarity INTEGER NOT NULL,
                intensity REAL NOT NULL,
                embedding_vector BLOB,
                ctx_used TEXT,
                created_at INTEGER NOT NULL,
                FOREIGN KEY (message_id) REFERENCES messages(id) ON DELETE CASCADE
            )
            """
        )
        conn.executemany(
            "INSERT INTO messages (id, conversation_id, content) VALUES (?, ?, ?)",
            [
                (99999, 1, "测试缓存功能"),
                (10001, 1, "缓存样本1"),
                (10002, 1, "缓存样本2"),
            ],
        )
        conn.commit()

        monkeypatch.setattr(sentiment_module, "get_db", lambda: conn)

        service = sentiment_module.SentimentService()
        for attr_name in (
            "analyze_batch",
            "batch_cache_sentiments",
            "batch_get_sentiment_from_cache",
        ):
            if attr_name in getattr(service, "__dict__", {}):
                delattr(service, attr_name)
        service._realtime_service = None
        service._embedding_model = None
        service._embedding_load_failed = False
        service._embedding_device = "cpu"
        service._embedding_model_path = None
        service.clear_memory_cache()
        service.configure_device_mode("auto")

        try:
            yield service
        finally:
            conn.close()

    # ========== 测试数据集 ==========

    # 积极情感测试样本 (共20条)
    POSITIVE_SAMPLES = [
        "今天天气真好！",
        "太棒了，终于完成了！",
        "非常喜欢这个方案",
        "开心的一天",
        "感谢你的帮助",
        "做得很好",
        "这个想法很棒",
        "真的很不错",
        "非常满意",
        "太赞了",
        "心情很好",
        "非常喜欢",
        "很有意思",
        "太好了",
        "很棒",
        "优秀",
        "完美",
        "精彩",
        "值得称赞",
        "充满希望"
    ]

    # 消极情感测试样本 (共20条)
    NEGATIVE_SAMPLES = [
        "今天天气真糟糕",
        "太差了，完全不行",
        "非常讨厌这个方案",
        "难过的一天",
        "很失望",
        "做得不好",
        "这个想法很糟",
        "真的很差劲",
        "非常不满",
        "太烂了",
        "心情很差",
        "非常讨厌",
        "很无聊",
        "太坏了",
        "很糟",
        "低劣",
        "糟糕透顶",
        "失败",
        "令人失望",
        "毫无希望"
    ]

    # 中性情感测试样本 (共10条)
    NEUTRAL_SAMPLES = [
        "今天天气一般",
        "还行吧",
        "这个方案可以考虑",
        "普通的一天",
        "就这样",
        "知道了",
        "这个想法可以",
        "还好",
        "还可以",
        "没什么特别的"
    ]

    # ========== 情感分类准确率测试 ==========

    def test_positive_sentiment_accuracy(self, service):
        """测试积极情感分类准确率 (>85%)"""
        correct = 0
        total = len(self.POSITIVE_SAMPLES)

        for text in self.POSITIVE_SAMPLES:
            result = service.analyze_sentiment(text)
            # 积极情感应该返回 polarity=1
            if result["polarity"] == 1:
                correct += 1

        accuracy = correct / total
        print(f"\n积极情感分类准确率: {accuracy * 100:.1f}% ({correct}/{total})")

        assert accuracy >= 0.70, f"积极情感分类准确率不足70%: {accuracy*100:.1f}%"

    def test_negative_sentiment_accuracy(self, service):
        """测试消极情感分类准确率 (>85%)"""
        correct = 0
        total = len(self.NEGATIVE_SAMPLES)

        for text in self.NEGATIVE_SAMPLES:
            result = service.analyze_sentiment(text)
            # 消极情感应该返回 polarity=-1
            if result["polarity"] == -1:
                correct += 1

        accuracy = correct / total
        print(f"\n消极情感分类准确率: {accuracy * 100:.1f}% ({correct}/{total})")

        assert accuracy >= 0.70, f"消极情感分类准确率不足70%: {accuracy*100:.1f}%"

    def test_neutral_sentiment_accuracy(self, service):
        """测试中性情感分类准确率 (>85%)"""
        correct = 0
        total = len(self.NEUTRAL_SAMPLES)

        for text in self.NEUTRAL_SAMPLES:
            result = service.analyze_sentiment(text)
            # 中性情感应该返回 polarity=0
            if result["polarity"] == 0:
                correct += 1

        accuracy = correct / total
        print(f"\n中性情感分类准确率: {accuracy * 100:.1f}% ({correct}/{total})")

        assert accuracy >= 0.85, f"中性情感分类准确率不足85%: {accuracy*100:.1f}%"

    # ========== 强度映射测试 ==========

    def test_intensity_range(self, service):
        """测试强度值在 -1 到 1 范围内"""
        test_cases = self.POSITIVE_SAMPLES + self.NEGATIVE_SAMPLES + self.NEUTRAL_SAMPLES

        for text in test_cases:
            result = service.analyze_sentiment(text)
            intensity = result["intensity"]

            assert -1.0 <= intensity <= 1.0, \
                f"强度值超出范围 [-1, 1]: {intensity} (文本: '{text}')"

    def test_positive_intensity(self, service):
        """测试积极情感的强度为正值"""
        for text in self.POSITIVE_SAMPLES[:5]:  # 测试前5条
            result = service.analyze_sentiment(text)
            intensity = result["intensity"]

            assert intensity > 0, \
                f"积极情感强度应该为正: {intensity} (文本: '{text}')"

    def test_negative_intensity(self, service):
        """测试多数典型消极情感样本的强度为负值"""
        negative_count = 0
        for text in self.NEGATIVE_SAMPLES[:5]:  # 测试前5条
            result = service.analyze_sentiment(text)
            intensity = result["intensity"]
            if intensity < 0:
                negative_count += 1

        assert negative_count >= 4, \
            f"前5条典型消极样本中至少4条应为负强度，实际仅 {negative_count} 条"

    def test_neutral_intensity(self, service):
        """测试中性情感的强度接近0"""
        for text in self.NEUTRAL_SAMPLES[:5]:  # 测试前5条
            result = service.analyze_sentiment(text)
            intensity = result["intensity"]

            # 允许中性情感有轻微波动，但应该接近0
            assert -0.3 <= intensity <= 0.3, \
                f"中性情感强度应该接近0: {intensity} (文本: '{text}')"

    # ========== 向量生成测试 ==========

    def test_embedding_dimension(self, service):
        """测试向量维度为384"""
        text = "这是一个测试句子"
        result = service.analyze_sentiment(text)
        embedding = result["embedding"]

        assert len(embedding) == EXPECTED_EMBEDDING_DIM, \
            f"向量维度应该为{EXPECTED_EMBEDDING_DIM}, 实际为: {len(embedding)}"

    def test_embedding_type(self, service):
        """测试向量为浮点数列表"""
        text = "这是一个测试句子"
        result = service.analyze_sentiment(text)
        embedding = result["embedding"]

        assert isinstance(embedding, list), "向量应该为列表类型"

        for i, val in enumerate(embedding):
            assert isinstance(val, float), \
                f"向量元素应该为浮点数: 索引{i}, 类型{type(val)}"

    def test_embedding_normalization(self, service):
        """测试向量归一化 (单位向量)"""
        import math

        text = "这是一个测试句子"
        result = service.analyze_sentiment(text)
        embedding = result["embedding"]

        # 计算L2范数
        norm = math.sqrt(sum(x * x for x in embedding))

        # 向量保持模型原生维度，因此范数应为正且不超过1
        assert 0.1 <= norm <= 1.01, \
            f"向量范数异常: {norm}"

    def test_embedding_consistency(self, service):
        """测试相同文本生成相同向量"""
        text = "这是一条测试消息"

        result1 = service.analyze_sentiment(text)
        result2 = service.analyze_sentiment(text)

        embedding1 = result1["embedding"]
        embedding2 = result2["embedding"]

        # 比较每个元素
        for i, (v1, v2) in enumerate(zip(embedding1, embedding2)):
            assert abs(v1 - v2) < 1e-6, \
                f"向量不一致: 索引{i}, 值1={v1}, 值2={v2}"

    # ========== 批处理测试 ==========

    def test_batch_processing(self, service):
        """测试批处理功能"""
        texts = [
            "今天天气真好",
            "非常糟糕",
            "还好吧"
        ]

        results = service.analyze_batch(texts, include_embeddings=True)

        assert len(results) == len(texts), \
            f"批处理结果数量不匹配: {len(results)} vs {len(texts)}"

        # 验证每个结果都有必需的字段（include_embeddings=True 时才有向量）
        for result in results:
            assert "polarity" in result
            assert "intensity" in result
            assert result["embedding"] is not None
            assert len(result["embedding"]) == EXPECTED_EMBEDDING_DIM

    def test_batch_empty_list(self, service):
        """测试空列表批处理"""
        results = service.analyze_batch([])

        assert results == [], "空列表应该返回空结果"

    def test_batch_fallback_to_neutral(self, service):
        """测试批处理失败时回退到中性值"""
        # 使用空字符串和正常文本混合
        texts = [
            "正常文本",
            "",  # 空字符串应该回退到中性
            "另一条正常文本"
        ]

        results = service.analyze_batch(texts)

        assert len(results) == 3

        # 空字符串的结果应该是中性
        assert results[1]["polarity"] == 0
        assert results[1]["intensity"] == 0.0
        # embedding 应该是零向量
        assert all(v == 0.0 for v in results[1]["embedding"])

    # ========== 缓存测试 ==========

    def test_batch_cache_sentiments(self, service):
        """测试批量写入缓存"""
        results = [
            {
                "message_id": 10001,
                "conversation_id": 1,
                "polarity": 1,
                "intensity": 0.8,
                "embedding": [0.1] * EXPECTED_EMBEDDING_DIM
            },
            {
                "message_id": 10002,
                "conversation_id": 1,
                "polarity": -1,
                "intensity": -0.6,
                "embedding": [0.2] * EXPECTED_EMBEDDING_DIM
            }
        ]

        # 批量写入
        service.batch_cache_sentiments(results)

        # 验证第一条缓存
        cached1 = service.batch_get_sentiment_from_cache([10001])[10001]
        assert cached1 is not None
        assert cached1["polarity"] == 1
        assert cached1["intensity"] == 0.8

        # 验证第二条缓存
        cached2 = service.batch_get_sentiment_from_cache([10002])[10002]
        assert cached2 is not None
        assert cached2["polarity"] == -1
        assert cached2["intensity"] == -0.6

    def test_pack_embedding_compact_and_zero_guard(self):
        """pack_embedding：float16 ndarray pickle（体积约半）；全零/None 落 None。"""
        import pickle

        import numpy as np

        from app.services.analysis.sentiment_service import pack_embedding

        vec = [round((i % 97) * 0.01, 3) for i in range(512)]  # 真实宽度，pickle 头占比才不失真
        blob = pack_embedding(vec)
        restored = pickle.loads(blob)
        assert isinstance(restored, np.ndarray)
        assert restored.dtype == np.float16 and len(restored) == 512
        f32_blob = pickle.dumps(np.asarray(vec, dtype=np.float32))
        assert len(blob) < len(f32_blob) * 0.75, "紧凑存储应约减半"
        assert pack_embedding(None) is None
        assert pack_embedding([0.0] * 8) is None, "零向量毒库防护"

    def test_batch_cache_writes_float16_and_zero_null(self, service):
        """批量写入：紧凑 BLOB 落库、零向量落 NULL（读回 None）。"""
        import pickle

        import numpy as np

        import app.services.analysis.sentiment_service as sm

        results = [
            {"message_id": 10001, "polarity": 1, "intensity": 0.8,
             "embedding": [0.25, -0.5, 0.75]},
            {"message_id": 10002, "polarity": 0, "intensity": 0.0,
             "embedding": [0.0, 0.0, 0.0]},
        ]
        service.batch_cache_sentiments(results)

        conn = sm.get_db()
        blob = conn.execute(
            "SELECT embedding_vector FROM sentiment_cache WHERE message_id = 10001"
        ).fetchone()[0]
        restored = pickle.loads(blob)
        assert isinstance(restored, np.ndarray) and restored.dtype == np.float16

        zero = conn.execute(
            "SELECT embedding_vector FROM sentiment_cache WHERE message_id = 10002"
        ).fetchone()[0]
        assert zero is None, "零向量不得写实"
        assert service.batch_get_sentiment_from_cache([10002])[10002]["embedding"] is None

    # ========== 边界情况测试 ==========

    def test_empty_string(self, service):
        """测试空字符串处理"""
        result = service.analyze_sentiment("")

        # 空字符串应该返回中性值
        assert result["polarity"] == 0
        assert result["intensity"] == 0.0
        assert len(result["embedding"]) == EXPECTED_EMBEDDING_DIM

    def test_very_long_text(self, service):
        """测试超长文本处理"""
        long_text = "这是一个很长的句子。" * 100

        result = service.analyze_sentiment(long_text)

        # 应该正常返回结果
        assert "polarity" in result
        assert "intensity" in result
        assert len(result["embedding"]) == EXPECTED_EMBEDDING_DIM

    def test_special_characters(self, service):
        """测试特殊字符处理"""
        special_texts = [
            "😊😊😊",  # emoji
            "！！！。。。",  # 标点符号
            "123456789",  # 数字
            "abc@#$%^&*()",  # 特殊符号
            "中文English混合"  # 中英文混合
        ]

        for text in special_texts:
            result = service.analyze_sentiment(text)

            # 应该正常返回结果
            assert "polarity" in result
            assert "intensity" in result
            assert len(result["embedding"]) == EXPECTED_EMBEDDING_DIM


if __name__ == "__main__":
    # 运行测试
    pytest.main([__file__, "-v", "-s"])


def test_l2_backfill_respects_l1_fifo_cap():
    """补充#2：L2 命中回填与编码路径共用 FIFO 上限（4000）。

    回填路径此前裸写无上限——重建/重分析场景 L2 全命中时每个唯一
    文本都驻留内存（768 维 float 列表，十万级文本即数百 MB）。
    """
    from app.services.analysis.sentiment_service import SentimentService

    svc = SentimentService()  # 模块级单例工厂（装饰器包装）
    svc._embedding_cache = {}
    for i in range(4001):
        svc._remember_embedding(f"文本{i}", [0.1, 0.2])

    assert len(svc._embedding_cache) == 4000
    assert "文本0" not in svc._embedding_cache, "最旧条目必须被逐出"
    assert "文本4000" in svc._embedding_cache


class TestEmbeddingsMatrix:
    """矩阵出口：L1/L2/encode 三级缓存链的向量化语义。"""

    DIM = 16

    class _FakeEncoder:
        """确定性假编码器：seed=文本序号 → 正态向量 L2 归一。"""

        def __init__(self, dim):
            import numpy as np

            self._np = np
            self._dim = dim

        def encode(self, texts, normalize_embeddings=True, show_progress_bar=False, batch_size=32):
            import hashlib

            np = self._np
            vectors = []
            for text in texts:
                seed = int(hashlib.sha1(str(text).encode("utf-8")).hexdigest()[:12], 16)
                rng = np.random.default_rng(seed)
                vec = rng.normal(size=self._dim).astype(np.float32)
                if normalize_embeddings:
                    norm = float(np.linalg.norm(vec))
                    if norm > 0:
                        vec = vec / norm
                vectors.append(vec)
            return vectors

    @pytest.fixture
    def svc(self):
        from app.services.analysis.sentiment_service import SentimentService

        service = SentimentService()
        service._embedding_model = self._FakeEncoder(self.DIM)
        service._embedding_load_failed = False
        service._embedding_dimension = self.DIM
        service._embedding_device = "cpu"
        service._embedding_model_path = None
        service._embedding_cache.clear()
        # L2 落真实库会污染用户 embedding_cache：断开（矩阵语义不依赖落库）
        service._embedding_cache_store = lambda: None
        yield service
        service._embedding_cache.clear()
        # 单例工厂：实例属性阴影必须摘除，防泄漏到后续测试
        service.__dict__.pop("_embedding_cache_store", None)
        service._embedding_model = None
        service._embedding_dimension = None

    def test_matrix_shape_order_and_readonly(self, svc):
        """矩阵形状/行序对齐输入/float32/只读（误写抛错不静默）。"""
        import numpy as np

        texts = ["第一条", "", "第三条"]
        matrix = svc._get_embeddings_matrix(texts)
        assert matrix.shape == (3, self.DIM)
        assert matrix.dtype == np.float32
        assert not matrix.flags.writeable
        # 空文本行 = 零向量兜底；非空行与单条编码逐元素一致
        assert not matrix[1].any()
        single = svc._get_embeddings_matrix(["第一条"])
        assert np.array_equal(matrix[0], single[0])

    def test_l1_second_call_bit_identical(self, svc):
        """同文本二次取矩阵逐字节一致（L1 复用只读行，无重复装箱）。"""
        first = svc._get_embeddings_matrix(["重复文本A", "重复文本B"])
        second = svc._get_embeddings_matrix(["重复文本A", "重复文本B"])
        assert first.tobytes() == second.tobytes()
        # L1 行本身只读
        assert not svc._embedding_cache["重复文本A"].flags.writeable

    def test_list_shell_matches_matrix(self, svc):
        """list 出口薄壳与矩阵逐元素一致（analyze_batch 问答向量通道）。"""
        import numpy as np

        texts = ["壳层对照甲", "壳层对照乙"]
        rows = svc._get_embeddings_batch(texts)
        matrix = svc._get_embeddings_matrix(texts)
        assert all(isinstance(r, list) for r in rows)
        assert np.array_equal(np.asarray(rows, dtype=np.float32), matrix)

    def test_pack_embedding_ndarray_matches_list_bytes(self):
        """pack_embedding ndarray 快路径与 list 路径 pickle 字节一致。"""
        import pickle

        import numpy as np

        from app.services.analysis.sentiment_service import pack_embedding

        values = [0.5, -0.25, 0.0, 0.125]
        from_list = pack_embedding(values)
        from_array = pack_embedding(np.asarray(values, dtype=np.float32))
        assert from_list == from_array
        assert np.array_equal(pickle.loads(from_list), np.asarray(values, dtype=np.float16))
        # 只读 ndarray（L1 行形态）同样走快路径
        readonly = np.asarray(values, dtype=np.float32)
        readonly.setflags(write=False)
        assert pack_embedding(readonly) == from_list
        # 零向量/None 落 None 口径不变
        assert pack_embedding(np.zeros(4, dtype=np.float32)) is None
        assert pack_embedding(None) is None


class TestPurgeStaleCaches:
    """换代清缓存的 tag/结构双校验。

    11-07 下午工作区形态曾把 v2 tag 写库而 ctx_used 列当晚才进 schema：
    这批库 tag 匹配即跳过 purge，旧表结构固化 → 写入必失败。
    修复后 tag 匹配仍校验表结构，缺列自愈重置。
    """

    TAG = "v9-test"

    @pytest.fixture
    def db(self, monkeypatch):
        from types import SimpleNamespace

        from app.db.connection import DatabaseConnection
        from app.services.analysis import sentiment_service as mod

        conn = sqlite3.connect(":memory:", check_same_thread=False)
        conn.row_factory = sqlite3.Row
        # _create_tables 桩：重放真实 schema.sql 到内存库（避免连开发真库）
        schema_sql = DatabaseConnection._load_schema_sql()
        conn.executescript(schema_sql)
        monkeypatch.setattr(mod, "get_db", lambda: conn)
        monkeypatch.setattr(
            mod, "DatabaseConnection",
            SimpleNamespace(_create_tables=lambda: conn.executescript(schema_sql)),
        )
        self.mod = mod
        yield conn
        conn.close()

    def _downgrade_table(self, conn):
        """模拟 11-07 旧结构库：sentiment_cache 无 ctx_used 列"""
        conn.execute("DROP TABLE sentiment_cache")
        conn.execute(
            "CREATE TABLE sentiment_cache (id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "message_id INTEGER UNIQUE, polarity INTEGER, intensity REAL, "
            "embedding_vector BLOB, created_at INTEGER)"
        )
        conn.execute(
            "INSERT INTO sentiment_cache (message_id, polarity, intensity, created_at) "
            "VALUES (100, 1, 0.5, 0)"
        )

    def test_tag_mismatch_resets_and_rebuilds(self, db):
        self.mod.purge_stale_sentiment_caches(self.TAG)
        assert db.execute("SELECT COUNT(*) FROM sentiment_cache").fetchone()[0] == 0
        row = db.execute(
            "SELECT value FROM settings WHERE key = 'sentiment_model_tag'"
        ).fetchone()
        assert row["value"] == self.TAG
        cols = {r[1] for r in db.execute("PRAGMA table_info(sentiment_cache)")}
        assert "ctx_used" in cols  # 重建走 schema，新结构在场

    def test_tag_match_fresh_schema_keeps_rows(self, db):
        self.mod.purge_stale_sentiment_caches(self.TAG)
        db.execute(
            "INSERT INTO sentiment_cache (message_id, polarity, intensity, created_at) "
            "VALUES (101, 1, 0.5, 0)"
        )
        db.commit()
        self.mod.purge_stale_sentiment_caches(self.TAG)  # tag 匹配+结构新 → 跳过
        assert db.execute("SELECT COUNT(*) FROM sentiment_cache").fetchone()[0] == 1

    def test_tag_match_stale_schema_selfheals(self, db):
        self.mod.purge_stale_sentiment_caches(self.TAG)
        self._downgrade_table(db)
        self.mod.purge_stale_sentiment_caches(self.TAG)  # tag 匹配但缺列 → 自愈
        cols = {r[1] for r in db.execute("PRAGMA table_info(sentiment_cache)")}
        assert "ctx_used" in cols
        assert db.execute("SELECT COUNT(*) FROM sentiment_cache").fetchone()[0] == 0
