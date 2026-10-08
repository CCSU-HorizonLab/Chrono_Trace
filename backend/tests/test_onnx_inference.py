"""ONNX 推理后端测试（阶段 B）。

覆盖：后端选择（env/settings/auto）、provider 解析与设备标签、嵌入引擎
（ST 兼容签名/单位范数/维度）、分类引擎（极性与 torch 一致性锚定）、
SentimentService 的 ONNX 装配。模型缺失环境自动 skip。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

backend_root = Path(__file__).parent.parent
sys.path.insert(0, str(backend_root))

from app.services.analysis import onnx_inference
from app.services.analysis.onnx_inference import (
    device_tag_of,
    resolve_providers,
)

pytestmark = pytest.mark.skipif(
    not onnx_inference.has_onnx_models(),
    reason="本地无 ONNX fp16 模型（先跑 backend/scripts/export_models_onnx.py）",
)


class TestBackendSelection:

    def test_single_backend_always_onnx(self, monkeypatch):
        """单后端：无 torch 回退，任何环境/配置下恒 onnx。"""
        monkeypatch.setenv("CHRONO_INFERENCE_BACKEND", "torch")
        assert onnx_inference.resolve_inference_backend() == "onnx"
        monkeypatch.delenv("CHRONO_INFERENCE_BACKEND", raising=False)
        assert onnx_inference.resolve_inference_backend() == "onnx"


class TestProviderResolution:

    def test_cpu_mode_cpu_only(self):
        requested, effective = resolve_providers("cpu")
        assert requested == ["CPUExecutionProvider"]
        assert effective == ["CPUExecutionProvider"]
        assert device_tag_of(effective) == "cpu"

    def test_auto_keeps_cpu_fallback(self):
        _, effective = resolve_providers("auto")
        assert effective[-1] == "CPUExecutionProvider", "CPU 永远兜底"
        assert device_tag_of(effective) in ("cpu", "cuda", "dml")


class TestEmbeddingEngine:

    def test_st_compatible_encode(self):
        engine = onnx_inference.get_shared_engine("embedding", device_mode="cpu")
        vecs = engine.encode(
            ["今天心情不错", "这个方案还要改", ""],
            batch_size=8, normalize_embeddings=True, show_progress_bar=False,
        )
        from app.services.model_paths import get_embedding_model_dim
        assert vecs.shape == (3, get_embedding_model_dim() or 768)
        norms = (vecs * vecs).sum(1) ** 0.5
        assert abs(norms[0] - 1.0) < 1e-3, "归一化后范数应为 1"
        from app.services.model_paths import get_embedding_model_dim
        assert engine.get_sentence_embedding_dimension() == (get_embedding_model_dim() or 768)

    def test_shared_engine_cached(self):
        a = onnx_inference.get_shared_engine("embedding", device_mode="cpu")
        b = onnx_inference.get_shared_engine("embedding", device_mode="cpu")
        assert a is b


class TestClassifierEngine:

    def test_logits_shape_and_probs(self):
        engine = onnx_inference.get_shared_engine("classifier", device_mode="cpu")
        logits = engine.predict_logits(["太烦了不想干", "哈哈笑死我了", "明天三点开会"])
        assert logits.shape == (3, 3)
        # 与 torch 后端的锚定值（三句极性 -1/1/0，置信 0.761/0.886/0.880，
        # 由 verify_onnx_equivalence 实测逐位一致）
        import numpy as np

        preds = np.argmax(logits, axis=1).tolist()
        assert preds == [0, 1, 2], "三类极性顺序 0=负 1=正 2=中"


class TestSentimentServiceOnnx:

    def test_load_and_batch(self, monkeypatch):
        monkeypatch.setenv("CHRONO_INFERENCE_BACKEND", "onnx")
        from app.services.analysis.sentiment_service import SentimentService

        svc = SentimentService()
        svc._embedding_model = None
        svc._embedding_load_failed = False
        svc._load_embedding_model()
        assert type(svc._embedding_model).__name__ == "OnnxEmbeddingModel"
        from app.services.model_paths import get_embedding_model_dim
        assert svc._embedding_dimension == (get_embedding_model_dim() or 768)
        assert svc._embedding_device in ("cpu", "cuda", "dml")
        vectors = svc._get_embeddings_batch(["测试句一", "测试句二"], batch_size=8)
        from app.services.model_paths import get_embedding_model_dim
        assert len(vectors) == 2 and len(vectors[0]) == (get_embedding_model_dim() or 768)

    def test_realtime_classifier_onnx(self, monkeypatch):
        monkeypatch.setenv("CHRONO_INFERENCE_BACKEND", "onnx")
        from app.services.realtime.realtime_sentiment_service import RealtimeSentimentService

        rs = RealtimeSentimentService(skip_db_init=True)
        rs._model = None
        result = rs.analyze("这也太烦了吧，不想干了")
        assert result["polarity"] == -1
        assert result["confidence"] > 0.5
