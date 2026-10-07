"""Helpers for resolving configurable local model paths."""

from __future__ import annotations

import logging

from pathlib import Path
from typing import Any, Optional

from ..config import IS_FROZEN, MODELS_DIR_PATH, RESOURCE_ROOT_PATH
from .wechat.account_settings import load_settings_from_file


MODEL_ROOT_DIR_KEY = "model_root_dir"
#: 激活的嵌入模型变体（settings 键）；bge-small 24M 参数约为 text2vec
#: （102M）的 1/4 计算量，C-MTEB 同档——CPU 吞吐主升级路径
EMBEDDING_VARIANT_KEY = "embedding_model_variant"

logger = logging.getLogger(__name__)

SENTIMENT_MODEL_REPO_ID = "tingting0514/chrono-trace-sentiment"
EMBEDDING_MODEL_REPO_ID = "tingting0514/text2vec-base-chinese"
# text2vec-base-chinese is a BERT-base embedding model.  Do not project its
# vectors down to this value; it is only the default index schema dimension.
EMBEDDING_MODEL_DIM = 768

SENTIMENT_MODEL_DIRNAME = "sentiment_3class"
EMBEDDING_MODEL_DIRNAME = "text2vec_base_chinese"

#: 嵌入模型变体注册表：dirname/repo_id/维度。L2 嵌入缓存按 repo_id 隔离，
#: RAG 按模型名+维度触发全量重建——切换变体自动隔离旧向量，无需迁移
EMBEDDING_VARIANTS: dict[str, dict] = {
    "text2vec_base_chinese": {
        "dirname": "text2vec_base_chinese",
        "repo_id": EMBEDDING_MODEL_REPO_ID,
        "dim": 768,
    },
    "bge_small_zh_v15": {
        "dirname": "bge_small_zh_v15",
        "repo_id": "BAAI/bge-small-zh-v1.5",
        "dim": 512,
    },
}
# 默认 bge（24M 参数，实测 6.3× 提速、fp16 无损）。Windows 安装包仍内置
# text2vec——回退链自动兜底（默认变体无产物 → 任选有产物者），行为不变。
DEFAULT_EMBEDDING_VARIANT = "bge_small_zh_v15"

# 回落只提示一次：resolve 每个嵌入批次都会重算（引擎 key 组成部分），
# 不去重会在冷跑分析中刷上千行相同 INFO
_fallback_logged_variants: set[str] = set()


def resolve_embedding_variant(settings: Optional[dict[str, Any]] = None) -> str:
    """解析激活的嵌入变体，带回退链：配置值 → 默认 → 任一存在产物者。

    打包版可能只内置 bge（47MB）不内置 text2vec（195MB）——配置指向
    的变体缺产物时依次尝试：默认变体 → 另一变体，保证至少能找到
    一个可用模型。
    """
    current = settings if settings is not None else load_settings_from_file()
    raw = str(current.get(EMBEDDING_VARIANT_KEY) or "").strip()
    model_root = get_model_root_dir(current)

    def _has_products(variant: str) -> bool:
        return (
            model_root / EMBEDDING_VARIANTS[variant]["dirname"] / "onnx" / "model.fp16.onnx"
        ).exists()

    if raw and raw in EMBEDDING_VARIANTS and _has_products(raw):
        return raw
    if _has_products(DEFAULT_EMBEDDING_VARIANT):
        return DEFAULT_EMBEDDING_VARIANT
    for variant in EMBEDDING_VARIANTS:
        if variant != DEFAULT_EMBEDDING_VARIANT and _has_products(variant):
            if variant not in _fallback_logged_variants:
                _fallback_logged_variants.add(variant)
                logger.info(
                    "[模型路径] 默认变体 %s 无产物，回落 %s", DEFAULT_EMBEDDING_VARIANT, variant
                )
            return variant
    return DEFAULT_EMBEDDING_VARIANT


def get_embedding_variant_info(settings: Optional[dict[str, Any]] = None) -> dict:
    return EMBEDDING_VARIANTS[resolve_embedding_variant(settings)]


def get_embedding_model_repo_id(settings: Optional[dict[str, Any]] = None) -> str:
    return str(get_embedding_variant_info(settings)["repo_id"])


def get_embedding_model_dim(settings: Optional[dict[str, Any]] = None) -> int:
    return int(get_embedding_variant_info(settings)["dim"])


def normalize_model_root_dir(value: Optional[str]) -> str:
    """归一化模型根目录：显式自定义 > 打包内置 > 用户数据目录。

    frozen 分支必须在 normalize 里做——get_model_root_dir 无配置时走的
    是本函数（此前只改 get_default_model_root_dir，打包产物里
    has_onnx_models() 落到用户数据目录找不到内置模型，回退 torch 栈）。
    防御：settings 存的默认用户数据目录值（「更改模型位置」或旧版本持久
    化）不算自定义；自定义目录无 ONNX 模型时回落内置。
    """
    raw_value = str(value or "").strip()
    resolved_custom = str(Path(raw_value).expanduser().resolve()) if raw_value else ""
    default_user_dir = str(Path(MODELS_DIR_PATH).resolve())

    if IS_FROZEN:
        bundled = Path(RESOURCE_ROOT_PATH) / "models"
        # 内置判定按「任一嵌入变体有产物」——各平台 spec 内置的变体不同
        # （Linux 仅 bge、Windows 仍 text2vec），写死单变体名会让另一平台
        # 的打包版绕过内置目录、找不到自带的模型
        bundled_has_embedding = any(
            (bundled / v["dirname"] / "onnx" / "model.fp16.onnx").exists()
            for v in EMBEDDING_VARIANTS.values()
        )
        if bundled_has_embedding:
            if not resolved_custom or resolved_custom == default_user_dir:
                return str(bundled.resolve())
            if not any(
                (Path(resolved_custom) / v["dirname"] / "onnx").exists()
                for v in EMBEDDING_VARIANTS.values()
            ):
                logger.info(
                    "[模型路径] 配置目录 %s 无 ONNX 模型，回落安装包内置目录",
                    resolved_custom,
                )
                return str(bundled.resolve())
    return resolved_custom or default_user_dir


def get_default_model_root_dir() -> Path:
    return Path(normalize_model_root_dir(None))


def get_model_root_dir(settings: Optional[dict[str, Any]] = None) -> Path:
    current_settings = settings if settings is not None else load_settings_from_file()
    return Path(normalize_model_root_dir(current_settings.get(MODEL_ROOT_DIR_KEY))).resolve()


def get_sentiment_model_dir(settings: Optional[dict[str, Any]] = None) -> Path:
    return get_model_root_dir(settings) / SENTIMENT_MODEL_DIRNAME


def get_embedding_model_dir(settings: Optional[dict[str, Any]] = None) -> Path:
    return get_model_root_dir(settings) / get_embedding_variant_info(settings)["dirname"]


def ensure_model_root_dir(settings: Optional[dict[str, Any]] = None) -> Path:
    model_root = get_model_root_dir(settings)
    model_root.mkdir(parents=True, exist_ok=True)
    return model_root
