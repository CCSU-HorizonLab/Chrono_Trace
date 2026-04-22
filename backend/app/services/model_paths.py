"""Helpers for resolving configurable local model paths."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from ..config import MODELS_DIR_PATH
from .wechat.account_settings import load_settings_from_file


MODEL_ROOT_DIR_KEY = "model_root_dir"

SENTIMENT_MODEL_REPO_ID = "tingting0514/chrono-trace-sentiment"
EMBEDDING_MODEL_REPO_ID = "tingting0514/text2vec-base-chinese"

SENTIMENT_MODEL_DIRNAME = "sentiment_3class"
EMBEDDING_MODEL_DIRNAME = "text2vec_base_chinese"


def normalize_model_root_dir(value: Optional[str]) -> str:
    raw_value = str(value or "").strip()
    target = Path(raw_value).expanduser() if raw_value else Path(MODELS_DIR_PATH)
    return str(target.resolve())


def get_default_model_root_dir() -> Path:
    return Path(MODELS_DIR_PATH).resolve()


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
