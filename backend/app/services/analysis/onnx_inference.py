"""ONNX 推理引擎（阶段 B）：onnxruntime + HF tokenizers（嵌入 fp32 / 分类器 fp16，按实测择优）。

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
    get_embedding_model_dir,
    get_model_root_dir,
)

logger = logging.getLogger(__name__)

EMBEDDING_MAX_LENGTH = 64           # 聊天消息实测 97% ≤64 字（中位 6 字）；
                                    # 动态 padding 下仅影响 3% 长文本，降档
                                    # 只省注意力计算不伤短消息精度
CLASSIFIER_MAX_LENGTH = 128         # 情感三分类输入同为聊天消息，512 是
                                    # transformers 时代遗留的保守值


def resolve_inference_backend() -> str:
    """单后端：恒 onnx（torch 回退已按需求移除；保留函数供历史调用点）。"""
    return "onnx"


def has_onnx_models() -> bool:
    """两个模型文件是否齐备（嵌入 fp32 / 分类器 fp16；tokenizer 按需回退）。"""
    return _onnx_path("embedding", fp32=True).exists() and _onnx_path("classifier").exists()


def _onnx_path(kind: str, fp32: bool = False) -> Path:
    name = "model.onnx" if fp32 else "model.fp16.onnx"
    # 嵌入模型目录跟随变体（bge/text2vec 切换）；此前用硬编码常量
    # EMBEDDING_MODEL_DIRNAME，变体机制被完全绕过
    if kind == "embedding":
        return get_embedding_model_dir() / "onnx" / name
    return get_model_root_dir() / SENTIMENT_MODEL_DIRNAME / "onnx" / name


def _embedding_model_path() -> Path:
    """嵌入产物定死 fp32（bge-small 实测 CPU 上比 fp16 快 32%——82→108 条/s，
    fp16 在 CPU 需逐层 cast 回 fp32 计算；输出 cosine=1.0 无损）。分类器
    相反（fp16 快 14%），维持 fp16。每个模型只进包一个文件。
    """
    return _onnx_path("embedding", fp32=True)


def _tokenizer_dir(kind: str) -> Path:
    if kind == "embedding":
        return get_embedding_model_dir() / "onnx" / "tokenizer"
    return get_model_root_dir() / SENTIMENT_MODEL_DIRNAME / "onnx" / "tokenizer"


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

    def _plan_sorted_unique_batches(
        self, texts: Sequence[str], batch_size: int
    ) -> tuple[list[str], list[int]]:
        """运行内去重 + 长度排序的批规划（padding 浪费消解）。

        实测（生产同款模型/批大小/线程）：批内按 BatchLongest 补齐 + 聊天
        文本长度极度偏斜（中位 6 字 / p97 128+），时间序切批时一条长消息
        让整批短消息陪跑，注意力算力随长度平方放大。按 token 长度聚批后
        分类器 7.3→43.7 条/s（6.0×）、嵌入 93.4→331 条/s（3.5×），且
        argmax 一致率 100%（logits 扰动 1.1e-3，fp16 量化粒度级）。

        排序键 (截断后token长度, 文本sha1)：sha1 决胜保证同数据集跨次运行
        批划分完全一致——输出 bit 级可复现，不会因批组合噪声漂移不定。
        重复文本只推理一次（最大会话实测重复率 13%，"哈哈"类短消息）。

        Returns:
            (ordered_unique, orig_map)：前者为排序后的去重文本（切批对象），
            orig_map[i] 为原第 i 条在 ordered_unique 中的下标（摊回用）。
        """
        import hashlib

        seen: dict[str, int] = {}
        for t in texts:
            if t not in seen:
                seen[t] = len(seen)
        keyed = []
        for t in seen:
            n_tokens = len(self.tokenizer.encode(t).ids)  # 截断由 tokenizer 配置生效
            keyed.append((n_tokens, hashlib.sha1(t.encode("utf-8")).hexdigest(), t))
        keyed.sort(key=lambda x: (x[0], x[1]))
        ordered_unique = [k[2] for k in keyed]
        pos = {t: i for i, t in enumerate(ordered_unique)}
        orig_map = [pos[t] for t in texts]
        return ordered_unique, orig_map

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
            _onnx_path("embedding", fp32=True), _tokenizer_dir("embedding"),
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
        if not texts:
            result = np.zeros((0, self.get_sentence_embedding_dimension()), dtype=np.float32)
            return result if convert_to_numpy else result.tolist()
        ordered, orig_map = self._plan_sorted_unique_batches(texts, batch_size)
        vectors = []
        for start in range(0, len(ordered), max(1, batch_size)):
            chunk = ordered[start : start + max(1, batch_size)]
            feeds, mask = self._pad_batch(chunk)
            hidden = self.session.run(None, feeds)[0]  # [b, seq, dim]
            m = mask[:, :, None].astype(hidden.dtype)
            pooled = (hidden * m).sum(1) / np.clip(m.sum(1), 1e-9, None)
            if normalize_embeddings:
                norms = np.linalg.norm(pooled, axis=1, keepdims=True)
                pooled = pooled / np.clip(norms, 1e-9, None)
            vectors.append(pooled)
        unique_result = np.concatenate(vectors)
        result = unique_result[orig_map]  # 去重摊回 + 还原调用方原序
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
        if not texts:
            return np.zeros((0, 3), dtype=np.float32)
        ordered, orig_map = self._plan_sorted_unique_batches(texts, batch_size)
        outputs = []
        for start in range(0, len(ordered), max(1, batch_size)):
            chunk = ordered[start : start + max(1, batch_size)]
            feeds, _ = self._pad_batch(chunk)
            outputs.append(self.session.run(None, feeds)[0])  # [b, num_classes]
        return np.concatenate(outputs)[orig_map]


_engine_lock = threading.Lock()
_engine_cache: dict[str, _BaseOnnxModel] = {}


def get_shared_engine(kind: str, device_mode: str = "auto") -> _BaseOnnxModel:
    """进程内共享 session（204MB 模型加载一次）。"""
    from ..model_paths import get_embedding_variant_info

    variant = get_embedding_variant_info()["dirname"] if kind == "embedding" else ""
    # 键含嵌入变体：切换模型后取新 session，旧变体实例交由 GC
    key = f"{kind}:{variant}:{device_tag_of(resolve_providers(device_mode)[1])}"
    with _engine_lock:
        if key not in _engine_cache:
            cls = OnnxEmbeddingModel if kind == "embedding" else OnnxClassifierModel
            _engine_cache[key] = cls(device_mode=device_mode)
        return _engine_cache[key]


def reset_shared_engines() -> None:
    """设备模式切换时清空（configure_device_mode 调用）。"""
    with _engine_lock:
        _engine_cache.clear()
