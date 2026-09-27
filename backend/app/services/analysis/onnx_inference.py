"""ONNX 推理引擎（阶段 B）：fp16 模型 + onnxruntime + HF tokenizers。

替代 torch/sentence-transformers/transformers 的推理职责：
- 包体：torch 栈 ~890MB → onnxruntime ~60-105MB；模型 fp32 1.17GB → fp16 409MB
- Windows GPU 走 DirectML（系统内建，免 CUDA）；Linux 走 CUDA EP（缺库自动回退 CPU）
- fp16 向量与 torch 路径数值一致（实测 cosine=1.0，999 条真实消息），因此
  embedding_cache / RAG 既有向量**无需重建**

引擎对外提供 sentence-transformers 兼容的 encode() 外观（SentimentService
原样挂载，L1/L2 缓存与全部消费方零改动），以及分类器的 logits 批量接口。

单后端：ONNX 是唯一运行时推理栈（无 torch 回退）。
"""
from __future__ import annotations

import logging
import os
import threading
from pathlib import Path
from typing import Optional, Sequence

import numpy as np

from ..model_paths import (
    EMBEDDING_MODEL_DIRNAME,
    SENTIMENT_MODEL_DIRNAME,
    get_model_root_dir,
)

logger = logging.getLogger(__name__)

EMBEDDING_MAX_LENGTH = 128          # sentence_bert_config.json 同值
CLASSIFIER_MAX_LENGTH = 512         # 与原 transformers 路径一致


def resolve_inference_backend() -> str:
    """单后端：恒 onnx（torch 回退已按需求移除；保留函数供历史调用点）。"""
    return "onnx"


def has_onnx_models() -> bool:
    """两个 fp16 模型文件是否齐备（tokenizer 由引擎按需回退 transformers）。"""
    return _onnx_path("embedding").exists() and _onnx_path("classifier").exists()


def _onnx_path(kind: str, fp32: bool = False) -> Path:
    name = "model.onnx" if fp32 else "model.fp16.onnx"
    dirname = EMBEDDING_MODEL_DIRNAME if kind == "embedding" else SENTIMENT_MODEL_DIRNAME
    return get_model_root_dir() / dirname / "onnx" / name


def _tokenizer_dir(kind: str) -> Path:
    dirname = EMBEDDING_MODEL_DIRNAME if kind == "embedding" else SENTIMENT_MODEL_DIRNAME
    return get_model_root_dir() / dirname / "onnx" / "tokenizer"


def resolve_providers(device_mode: str) -> tuple[list[str], list[str]]:
    """按设备模式产出 (请求序列, 实际可用序列)。

    dml 仅 Windows；cuda 仅 Linux/N 卡。两者不可用时 onnxruntime 自动
    回退 CPU（带 WARN），此处仍显式过滤避免无谓告警。
    """
    available = set(_get_available_providers())
    if device_mode == "cpu":
        requested = ["CPUExecutionProvider"]
    else:  # auto / gpu：有什么用什么，CPU 永远兜底
        requested = [
            "DmlExecutionProvider",
            "CUDAExecutionProvider",
            "CPUExecutionProvider",
        ]
    effective = [p for p in requested if p in available] or ["CPUExecutionProvider"]
    return requested, effective


def device_tag_of(providers: Sequence[str]) -> str:
    """L2 缓存键用的设备标签（cpu/cuda/dml）。"""
    for p in providers:
        if p == "DmlExecutionProvider":
            return "dml"
        if p == "CUDAExecutionProvider":
            return "cuda"
    return "cpu"


def _get_available_providers() -> list[str]:
    try:
        import onnxruntime as ort

        return list(ort.get_available_providers())
    except Exception as exc:
        logger.warning("[ONNX] onnxruntime 不可用: %s", exc)
        return []


class _BaseOnnxModel:
    def __init__(self, model_path: Path, tokenizer_dir: Path, device_mode: str,
                 max_length: int):
        import onnxruntime as ort

        requested, effective = resolve_providers(device_mode)
        self.providers = effective
        self.device_tag = device_tag_of(effective)
        self.max_length = max_length
        so = ort.SessionOptions()
        so.intra_op_num_threads = _resolve_thread_count()
        self.session = ort.InferenceSession(
            str(model_path), sess_options=so, providers=effective
        )
        self.input_names = {i.name for i in self.session.get_inputs()}
        self.tokenizer = _load_tokenizer(tokenizer_dir)
        self.tokenizer.enable_truncation(max_length=max_length)
        if effective != requested[: len(effective)] or self.device_tag != "cpu":
            logger.info(
                "[ONNX] %s providers=%s device=%s",
                model_path.name, effective, self.device_tag,
            )

    def _pad_batch(self, texts: Sequence[str]):
        enc = self.tokenizer.encode_batch(
            [t if (t and str(t).strip()) else "。" for t in texts]
        )
        maxlen = max(len(e.ids) for e in enc)
        ids = np.zeros((len(enc), maxlen), dtype=np.int64)
        mask = np.zeros((len(enc), maxlen), dtype=np.int64)
        ttype = np.zeros((len(enc), maxlen), dtype=np.int64)
        for i, e in enumerate(enc):
            ids[i, : len(e.ids)] = e.ids
            mask[i, : len(e.attention_mask)] = e.attention_mask
            if e.type_ids:
                ttype[i, : len(e.type_ids)] = e.type_ids
        feeds = {"input_ids": ids, "attention_mask": mask}
        if "token_type_ids" in self.input_names:
            feeds["token_type_ids"] = ttype
        return feeds, mask


def _resolve_thread_count() -> int:
    """CPU EP 线程数：物理核优先（与 torch 路径同一调优结论——逻辑核全开
    超线程争抢反而降吞吐，实测管线 163.9s vs 108.2s 的主因就是这里）。"""
    env = os.environ.get("CHRONO_ONNX_THREADS")
    if env and env.isdigit() and int(env) > 0:
        return int(env)
    try:
        logical = os.cpu_count() or 4
        return max(1, logical // 2)
    except Exception:
        return 4


def _load_tokenizer(tokenizer_dir: Path):
    if (tokenizer_dir / "tokenizer.json").exists():
        from tokenizers import Tokenizer

        return Tokenizer.from_file(str(tokenizer_dir / "tokenizer.json"))
    # 慢速 tokenizer（vocab.txt）→ transformers 转 fast，取底层句柄
    from transformers import AutoTokenizer

    return AutoTokenizer.from_pretrained(str(tokenizer_dir), local_files_only=True).backend_tokenizer


class OnnxEmbeddingModel(_BaseOnnxModel):
    """sentence-transformers 兼容外观——SentimentService 原样挂载。

    mask 加权 mean pooling + L2 归一，与 text2vec 的 1_Pooling 配置一致。
    """

    def __init__(self, device_mode: str = "auto"):
        super().__init__(
            _onnx_path("embedding"), _tokenizer_dir("embedding"),
            device_mode, EMBEDDING_MAX_LENGTH,
        )

    def encode(
        self,
        texts,
        batch_size: int = 32,
        normalize_embeddings: bool = True,
        show_progress_bar: bool = False,
        convert_to_numpy: bool = True,
    ):
        texts = [str(t) for t in texts]
        vectors = []
        for start in range(0, len(texts), max(1, batch_size)):
            chunk = texts[start : start + max(1, batch_size)]
            feeds, mask = self._pad_batch(chunk)
            hidden = self.session.run(None, feeds)[0]  # [b, seq, dim]
            m = mask[:, :, None].astype(hidden.dtype)
            pooled = (hidden * m).sum(1) / np.clip(m.sum(1), 1e-9, None)
            if normalize_embeddings:
                norms = np.linalg.norm(pooled, axis=1, keepdims=True)
                pooled = pooled / np.clip(norms, 1e-9, None)
            vectors.append(pooled)
        result = np.concatenate(vectors) if vectors else np.zeros((0, self.get_sentence_embedding_dimension()), dtype=np.float32)
        return result if convert_to_numpy else result.tolist()

    def get_sentence_embedding_dimension(self) -> Optional[int]:
        try:
            shape = self.session.get_outputs()[0].shape  # [batch, seq, dim]
            dim = shape[-1]
            return int(dim) if isinstance(dim, int) else 768
        except Exception:
            return 768


class OnnxClassifierModel(_BaseOnnxModel):
    """情感三分类：批量 logits（softmax/极性映射由调用方保持原逻辑）。"""

    def __init__(self, device_mode: str = "auto"):
        super().__init__(
            _onnx_path("classifier"), _tokenizer_dir("classifier"),
            device_mode, CLASSIFIER_MAX_LENGTH,
        )

    def predict_logits(self, texts: Sequence[str], batch_size: int = 32) -> np.ndarray:
        texts = [str(t) for t in texts]
        outputs = []
        for start in range(0, len(texts), max(1, batch_size)):
            chunk = texts[start : start + max(1, batch_size)]
            feeds, _ = self._pad_batch(chunk)
            outputs.append(self.session.run(None, feeds)[0])  # [b, num_classes]
        return np.concatenate(outputs) if outputs else np.zeros((0, 3), dtype=np.float32)


_engine_lock = threading.Lock()
_engine_cache: dict[str, _BaseOnnxModel] = {}


def get_shared_engine(kind: str, device_mode: str = "auto") -> _BaseOnnxModel:
    """进程内共享 session（204MB 模型加载一次）。"""
    key = f"{kind}:{device_tag_of(resolve_providers(device_mode)[1])}"
    with _engine_lock:
        if key not in _engine_cache:
            cls = OnnxEmbeddingModel if kind == "embedding" else OnnxClassifierModel
            _engine_cache[key] = cls(device_mode=device_mode)
        return _engine_cache[key]


def reset_shared_engines() -> None:
    """设备模式切换时清空（configure_device_mode 调用）。"""
    with _engine_lock:
        _engine_cache.clear()
