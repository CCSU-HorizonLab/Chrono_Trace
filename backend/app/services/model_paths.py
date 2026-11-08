"""Helpers for resolving configurable local model paths."""

from __future__ import annotations

import logging

from pathlib import Path
from typing import Any, Optional

from ..config import IS_FROZEN, MODELS_DIR_PATH, RESOURCE_ROOT_PATH
from .wechat.account_settings import load_settings_from_file


MODEL_ROOT_DIR_KEY = "model_root_dir"

logger = logging.getLogger(__name__)

# 情感模型不再有 ModelScope 远端（历史仓库停更于 v1）；发行产物随 git
# 仓库分发，发布工具 push_sentiment_model.py 自带目标仓库 ID
# 嵌入模型唯一：BAAI/bge-small-zh-v1.5（24M 参数、512 维，官方仓库）。
# 旧 text2vec-base-chinese（768 维，自建镜像）变体与注册表/回退链已移除
EMBEDDING_MODEL_REPO_ID = "BAAI/bge-small-zh-v1.5"
EMBEDDING_MODEL_DIM = 512

SENTIMENT_MODEL_DIRNAME = "sentiment_3class"
EMBEDDING_MODEL_DIRNAME = "bge_small_zh_v15"

#: 情感模型代际标识（权重 + 输入口径的联合身份）。三处消费同一值：
#: SentimentService.MODEL_TAG（缓存重置）、export 脚本（model_version.json
#: 随权重落档，get_local_version 读 version 键）、ensure 脚本（代际比对，
#: 本地/远端落后即拒绝导出防旧模型混入）。换代 = 改这里 + 重训 + 上传
SENTIMENT_MODEL_TAG = "v2-ctx-20261107"

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
        # 内置判定按嵌入产物在位——写死文件名以外的口径会在精度调整时
        # 让打包版绕过内置目录、找不到自带的模型
        bundled_has_embedding = (
            bundled / EMBEDDING_MODEL_DIRNAME / "onnx" / "model.onnx"
        ).exists()
        if bundled_has_embedding:
            if not resolved_custom or resolved_custom == default_user_dir:
                return str(bundled.resolve())
            if not (Path(resolved_custom) / EMBEDDING_MODEL_DIRNAME / "onnx").exists():
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
    return get_model_root_dir(settings) / EMBEDDING_MODEL_DIRNAME


def ensure_model_root_dir(settings: Optional[dict[str, Any]] = None) -> Path:
    model_root = get_model_root_dir(settings)
    model_root.mkdir(parents=True, exist_ok=True)
    return model_root
