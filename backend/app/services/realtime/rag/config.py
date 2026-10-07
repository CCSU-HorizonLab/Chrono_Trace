"""Configuration helpers for realtime suggestion RAG."""

from __future__ import annotations

import ipaddress
import json
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from ...model_paths import (
    EMBEDDING_VARIANTS,
    get_embedding_model_dim,
    get_embedding_model_repo_id,
)
from ...wechat.account_settings import load_settings_from_file


RAG_DEFAULTS: dict[str, Any] = {
    "rag_enabled": False,
    "rag_remote_context_redaction": True,
    "rag_allow_remote_embedding": False,
    "rag_embedding_provider": "local",
    # 默认模型名/维度跟随激活变体（text2vec=768 / bge-small=512）——
    # 写死常量会让另一变体激活的新装机 RAG 全量撞维度守卫
    "rag_embedding_model": get_embedding_model_repo_id(),
    "rag_embedding_dim": get_embedding_model_dim(),
    "rag_privacy_mode": "balanced",
    "rag_query_scope": "latest_turn",
    "rag_fact_shadow_enabled": True,
    "rag_fact_read_enabled": True,
    "rag_fact_score_threshold": 0.30,
    "rag_relationship_policy_shadow_enabled": False,
    "rag_structured_fact_extraction_enabled": False,
    "rag_relationship_policy_injection_enabled": True,
    "rag_prompt_snapshot_enabled": False,
}


def _load_fact_kind_hints() -> dict[str, list[str]]:
    path = Path(__file__).with_name("fact_kind_hints.json")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return {
            str(kind): [str(term) for term in terms if str(term).strip()]
            for kind, terms in payload.items()
            if isinstance(terms, list)
        }
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        return {}

_FACT_READ_MIGRATION_KEY = "_rag_fact_read_migrated_v1"


def _as_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "yes", "on", "enabled"}:
        return True
    if normalized in {"0", "false", "no", "off", "disabled"}:
        return False
    return default


def migrate_stale_variant_tuple(settings: dict[str, Any]) -> bool:
    """本地 RAG 嵌入配置与激活变体不一致时的一次性迁移。

    场景：嵌入变体已切换（如 text2vec→bge）但 settings.json 持久化的
    rag_embedding_model/dim 还是旧变体元组——旧值与 rag_index_status 里
    的旧值一致导致 config_match 永远通过、增量短路不重建，而引擎实际
    产新维度向量，检索侧维度守卫永久降级（死锁态）。

    规则（保守）：仅当 provider 为 local 且 (model, dim) 精确匹配某个
    已注册变体的 (repo_id, dim) 且该变体 ≠ 当前解析变体时，重写为当前
    变体元组。remote/custom 的任意远端模型名、以及对应变体仍激活的
    机器绝不动。重写后 config_match 失效 → 该联系人下次被用到时自动
    全量重建新维度向量。

    Returns:
        True 表示发生了改写（调用方可据此落盘）。
    """
    if str(settings.get("rag_embedding_provider") or "local") != "local":
        return False
    resolved_repo = get_embedding_model_repo_id(settings)
    resolved_dim = get_embedding_model_dim(settings)
    try:
        pair = (str(settings.get("rag_embedding_model") or ""), int(settings.get("rag_embedding_dim") or 0))
    except (TypeError, ValueError):
        return False
    resolved_pair = (str(resolved_repo), int(resolved_dim))
    if pair == resolved_pair:
        return False
    for variant in EMBEDDING_VARIANTS.values():
        if pair == (str(variant["repo_id"]), int(variant["dim"])):
            settings["rag_embedding_model"] = resolved_repo
            settings["rag_embedding_dim"] = resolved_dim
            return True
    return False


def apply_rag_defaults(settings: dict[str, Any]) -> dict[str, Any]:
    """Mutate and return settings with explicit RAG defaults."""
    # ``False`` was the old shadow-only default.  Existing settings files do
    # not distinguish that default from an intentional user opt-out, so the
    # first load upgrades legacy values once and records a marker.  Subsequent
    # explicit user changes are preserved.
    if _FACT_READ_MIGRATION_KEY not in settings:
        if settings.get("rag_fact_read_enabled") is False:
            settings["rag_fact_read_enabled"] = True
        settings[_FACT_READ_MIGRATION_KEY] = True
    for key, value in RAG_DEFAULTS.items():
        settings.setdefault(key, value)
    # 条件赋值：setdefault 实参先求值，键已存在时也会读一遍 hints JSON
    if "rag_fact_kind_hints" not in settings:
        settings["rag_fact_kind_hints"] = _load_fact_kind_hints()
    settings["rag_enabled"] = _as_bool(settings.get("rag_enabled"), False)
    settings["rag_remote_context_redaction"] = _as_bool(
        settings.get("rag_remote_context_redaction"),
        True,
    )
    settings["rag_allow_remote_embedding"] = _as_bool(
        settings.get("rag_allow_remote_embedding"),
        False,
    )
    if settings.get("rag_query_scope") not in {"latest_turn", "recent_window", "all"}:
        settings["rag_query_scope"] = "latest_turn"
    settings["rag_relationship_policy_shadow_enabled"] = _as_bool(
        settings.get("rag_relationship_policy_shadow_enabled"),
        default=RAG_DEFAULTS["rag_relationship_policy_shadow_enabled"],
    )
    settings["rag_structured_fact_extraction_enabled"] = _as_bool(
        settings.get("rag_structured_fact_extraction_enabled"),
        default=RAG_DEFAULTS["rag_structured_fact_extraction_enabled"],
    )
    settings["rag_relationship_policy_injection_enabled"] = _as_bool(
        settings.get("rag_relationship_policy_injection_enabled"),
        default=RAG_DEFAULTS["rag_relationship_policy_injection_enabled"],
    )
    settings["rag_fact_shadow_enabled"] = _as_bool(
        settings.get("rag_fact_shadow_enabled"),
        True,
    )
    settings["rag_fact_read_enabled"] = _as_bool(
        settings.get("rag_fact_read_enabled"),
        True,
    )
    try:
        settings["rag_fact_score_threshold"] = float(settings.get("rag_fact_score_threshold") or 0.30)
    except (TypeError, ValueError):
        settings["rag_fact_score_threshold"] = 0.30
    settings["rag_fact_score_threshold"] = min(1.0, max(0.0, settings["rag_fact_score_threshold"]))
    resolved_dim = get_embedding_model_dim(settings)
    resolved_repo = get_embedding_model_repo_id(settings)
    try:
        settings["rag_embedding_dim"] = int(settings.get("rag_embedding_dim") or resolved_dim)
    except (TypeError, ValueError):
        settings["rag_embedding_dim"] = resolved_dim
    if settings["rag_embedding_dim"] <= 0:
        settings["rag_embedding_dim"] = resolved_dim
    if not str(settings.get("rag_embedding_model") or "").strip():
        settings["rag_embedding_model"] = resolved_repo
    # 384 was the previous hard-coded projection width, not this model's
    # native shape. Migrate that legacy default so existing installations
    # rebuild vectors instead of silently continuing to lose half the vector.
    # 兼容旧默认标签（text2vec 时代写入 settings 的值）：命中即重打为
    # 当前变体标签+维度，让索引隔离机制强制干净重建
    _LEGACY_TEXT2VEC_LABEL = "tingting0514/text2vec-base-chinese"
    if (
        settings["rag_embedding_model"] in (resolved_repo, _LEGACY_TEXT2VEC_LABEL)
        and settings["rag_embedding_dim"] == 384
    ):
        settings["rag_embedding_model"] = resolved_repo
        settings["rag_embedding_dim"] = resolved_dim
    if settings.get("rag_embedding_provider") not in {"local", "remote", "custom"}:
        settings["rag_embedding_provider"] = "local"
    # 变体切换后的旧元组残留迁移（见 migrate_stale_variant_tuple 注释）；
    # 放在 provider 归一化之后，保证 provider 缺省时按 local 参与判定
    migrate_stale_variant_tuple(settings)
    if settings.get("rag_privacy_mode") not in {"balanced", "strict", "raw_local"}:
        settings["rag_privacy_mode"] = "balanced"
    return settings


_settings_file_cache: dict[str, Any] = {"key": None, "payload": None}


def load_rag_settings(settings: dict[str, Any] | None = None) -> dict[str, Any]:
    """Load persisted RAG settings with normalized defaults.

    无参（读文件）路径带 (mtime_ns, size) 门控的进程内缓存：一次检索链路
    会加载 3-4 次（retriever/indexer/context_builder 各自调），每次都全量
    读盘+归一化。set_settings 落盘会改变 mtime → 缓存自动失效。
    """
    if settings is not None:
        return apply_rag_defaults(dict(settings))
    from ...wechat.account_settings import default_settings_path
    path = default_settings_path()
    try:
        stat = path.stat()
        cache_key = (str(path), stat.st_mtime_ns, stat.st_size)
    except OSError:
        cache_key = None
    if cache_key is not None and _settings_file_cache["key"] == cache_key:
        return dict(_settings_file_cache["payload"])
    payload = apply_rag_defaults(dict(load_settings_from_file()))
    if cache_key is not None:
        _settings_file_cache["key"] = cache_key
        _settings_file_cache["payload"] = dict(payload)
    return payload


def persist_rag_variant_migration_if_needed() -> bool:
    """启动期一次性执行变体迁移并落盘（读路径保持纯内存，见上）。

    只回写两个嵌入键、不固化其余填充默认值；幂等，未命中/失败均安静
    返回。调用点：Bridge 构造（双入口共用）。
    """
    from ...wechat.account_settings import load_settings_from_file, save_settings_to_file

    raw = dict(load_settings_from_file())
    payload = apply_rag_defaults(dict(raw))
    raw_model = str(raw.get("rag_embedding_model") or "")
    if not raw_model or raw_model == str(payload["rag_embedding_model"]):
        return False
    try:
        corrected = dict(raw)
        corrected["rag_embedding_model"] = payload["rag_embedding_model"]
        corrected["rag_embedding_dim"] = payload["rag_embedding_dim"]
        save_settings_to_file(corrected)
        logger.info(
            "[RAG] 嵌入配置已迁移: %s/%s → %s/%s",
            raw_model, raw.get("rag_embedding_dim"),
            corrected["rag_embedding_model"], corrected["rag_embedding_dim"],
        )
        return True
    except Exception as exc:
        logger.warning("[RAG] 嵌入变体迁移落盘失败（内存改写仍生效）: %s", exc)
        return False


def is_remote_llm_model(model_config: dict[str, Any] | None) -> bool:
    """Return whether the active LLM sends prompts outside the local machine."""
    if not model_config:
        return False
    provider = str(model_config.get("provider") or "").strip().lower()
    base_url = str(model_config.get("api_base_url") or "").strip().lower()
    if not base_url:
        return provider not in {"ollama", "lmstudio", "local"}
    parsed = urlparse(base_url if "://" in base_url else f"http://{base_url}")
    host = (parsed.hostname or "").strip().lower()
    if host in {"localhost", "127.0.0.1", "::1"}:
        return False
    try:
        if ipaddress.ip_address(host).is_loopback:
            return False
    except ValueError:
        pass
    return True
