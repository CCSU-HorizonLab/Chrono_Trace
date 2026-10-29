"""分析模型状态与下载管理——从 bridge.py 拆出（步骤 3 mixin）。

Bridge 继承此 Mixin，方法名不变、前端 API 面与测试零破坏。
"""
from __future__ import annotations

import logging
import shutil
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


from ...services.model_paths import EMBEDDING_VARIANTS, MODEL_ROOT_DIR_KEY, SENTIMENT_MODEL_DIRNAME, SENTIMENT_MODEL_REPO_ID, get_embedding_model_dir, get_embedding_model_repo_id, get_model_root_dir, get_sentiment_model_dir, normalize_model_root_dir


def _embedding_dir_names() -> list[str]:
    """全部嵌入变体目录名（迁移/清点用——本机可能存在任一变体产物）。"""
    return [v["dirname"] for v in EMBEDDING_VARIANTS.values()]


class ModelMgmtApiMixin:
    """分析模型状态与下载管理"""

    def _get_sentiment_model_manager(self):
        from ...services.model_manager import ModelManager

        return ModelManager(
            model_dir=str(get_sentiment_model_dir(self.settings)),
            repo_id=SENTIMENT_MODEL_REPO_ID,
        )

    def _diagnose_embedding_model_status(self) -> dict[str, Any]:
        from ...services.model_manager import ModelManager

        diagnosis = ModelManager(
            model_dir=str(get_embedding_model_dir(self.settings)),
            repo_id=get_embedding_model_repo_id(self.settings),
        ).diagnose_model_status()
        diagnosis["can_recover"] = True
        return diagnosis

    def _get_model_root_dir(self) -> Path:
        return get_model_root_dir(self.settings)

    def _migrate_model_root_dir(self, target_dir: str) -> dict[str, Any]:
        with self._settings_lock:
            current_root = self._get_model_root_dir()
            next_root = Path(normalize_model_root_dir(target_dir))
            next_root.mkdir(parents=True, exist_ok=True)

            if current_root == next_root:
                self.settings[MODEL_ROOT_DIR_KEY] = str(next_root)
                self._save_settings()
                return {
                    "ok": True,
                    "model_root_dir": str(next_root),
                    "migrated_models": [],
                    "skipped_models": _embedding_dir_names() + [SENTIMENT_MODEL_DIRNAME],
                }

            moved: list[tuple[Path, Path]] = []
            skipped: list[str] = []
            try:
                for dirname in (SENTIMENT_MODEL_DIRNAME, *_embedding_dir_names()):
                    source = current_root / dirname
                    destination = next_root / dirname
                    if not source.exists():
                        skipped.append(dirname)
                        continue
                    if destination.exists():
                        raise FileExistsError(f"目标目录已存在: {destination}")
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(source), str(destination))
                    moved.append((source, destination))

                self.settings[MODEL_ROOT_DIR_KEY] = str(next_root)
                self._save_settings()
                return {
                    "ok": True,
                    "model_root_dir": str(next_root),
                    "migrated_models": [dst.name for _, dst in moved],
                    "skipped_models": skipped,
                }
            except Exception:
                for source, destination in reversed(moved):
                    if destination.exists() and not source.exists():
                        source.parent.mkdir(parents=True, exist_ok=True)
                        shutil.move(str(destination), str(source))
                raise

    def update_model_root_dir(self, new_dir: str) -> dict[str, Any]:
        try:
            result = self._migrate_model_root_dir(new_dir)
            return {
                **result,
                "sentiment_model_dir": str(get_sentiment_model_dir(self.settings)),
                "embedding_model_dir": str(get_embedding_model_dir(self.settings)),
            }
        except Exception as e:
            logger.error(f"[Bridge] 更新模型目录失败: {type(e).__name__}: {e}", exc_info=True)
            return {
                "ok": False,
                "error": f"{type(e).__name__}: {e}",
                "model_root_dir": str(self._get_model_root_dir()),
                "migrated_models": [],
                "skipped_models": [],
            }

    def get_embedding_cache_stats(self) -> dict[str, Any]:
        """嵌入 L2 缓存容量报告（text→vector 纯函数缓存，全局不分会话）。"""
        from ...services.analysis.embedding_cache_store import EMBEDDING_CACHE_MAX_ROWS, EmbeddingCacheStore

        stats = EmbeddingCacheStore.stats()
        return {
            "ok": True,
            "rows": stats["rows"],
            "bytes": stats["bytes"],
            "max_rows": EMBEDDING_CACHE_MAX_ROWS,
            "by_model": stats["by_model"],
        }

    def clear_embedding_cache(self) -> dict[str, Any]:
        """清空嵌入缓存（重分析时自动重嵌，2.4ms/条，无损操作）。"""
        from ...services.analysis.embedding_cache_store import EmbeddingCacheStore

        try:
            deleted = EmbeddingCacheStore.purge()
            return {"ok": True, "deleted": deleted}
        except Exception as e:
            logger.error(f"[Bridge] 清理嵌入缓存失败: {type(e).__name__}: {e}", exc_info=True)
            return {"ok": False, "error": f"{type(e).__name__}: {e}"}

    def check_analysis_model_status(self) -> dict[str, Any]:
        """Check whether analysis models are available locally with detailed diagnosis.

        ONNX 后端口径：fp16 产物存在即就绪（torch 格式的 config.json 不再是
        必需品——打包版内置目录只有 onnx/，此前按 torch 标记判活导致安装包
        自带模型还被提示缺失并引导无谓下载）。
        """
        try:
            onnx_ready = False
            try:
                from ...services.analysis.onnx_inference import has_onnx_models

                onnx_ready = has_onnx_models()
            except Exception as exc:
                logger.debug("[Bridge] ONNX 模型探测失败: %s", exc)

            if onnx_ready:
                empty_diagnosis = {"repo_id": "", "issue": None, "detail": "ONNX fp16 ready"}
                return {
                    "ok": True,
                    "analysis_available": True,
                    "sentiment_model_ready": True,
                    "embedding_model_ready": True,
                    "missing_models": [],
                    "missing_details": [],
                    "sentiment_diagnosis": empty_diagnosis,
                    "embedding_diagnosis": empty_diagnosis,
                    "backend": "onnx",
                }

            sentiment_manager = self._get_sentiment_model_manager()
            sentiment_diagnosis = sentiment_manager.diagnose_model_status()
            embedding_diagnosis = self._diagnose_embedding_model_status()

            # ONNX 单后端：可用性由 ONNX 产物单点决定——diagnose 按 torch 源
            # 权重（config.json + .safetensors/.bin）判活，残留的旧权重会让
            # issue=None 而 onnx/ 产物缺失，此前据 diagnose 置 ready 误报
            # analysis_available=True，实际推理并不可用
            sentiment_model_ready = onnx_ready
            embedding_model_ready = onnx_ready

            missing_models = []
            missing_details = []

            if not sentiment_model_ready:
                missing_models.append("sentiment")
                missing_details.append({
                    "model_name": "情感分类模型",
                    "model_key": "sentiment",
                    "repo_id": sentiment_diagnosis.get("repo_id"),
                    "issue": sentiment_diagnosis.get("issue")
                    or "源模型权重存在但 ONNX fp16 产物缺失，需重新导出 onnx/",
                    "can_auto_download": False,
                })

            if not embedding_model_ready:
                missing_models.append("embedding")
                missing_details.append({
                    "model_name": "文本向量模型",
                    "model_key": "embedding",
                    "repo_id": embedding_diagnosis.get("repo_id"),
                    "issue": embedding_diagnosis.get("issue")
                    or "源模型权重存在但 ONNX fp16 产物缺失，需重新导出 onnx/",
                    "can_auto_download": False,
                })
            # 打包版（frozen）：内置 ONNX 缺失只能重装完整安装包——应用内
            # 下载拉的是 ModelScope 源模型权重，推理单后端只认 onnx 产物，
            # 下载完依然不可用（假修复）；「运行 python 脚本」文案也只对
            # 开发态有意义
            from ...config import IS_FROZEN

            if IS_FROZEN:
                for item in missing_details:
                    item["issue"] = "安装包内置模型缺失：请重新下载完整安装包并覆盖安装"
                    item["can_auto_download"] = False
            else:
                for item in missing_details:
                    item["issue"] = (
                        f"{item['issue']}（推理为 ONNX 单后端：运行 "
                        "python backend/scripts/ensure_models_for_export.py --with-export "
                        "下载源模型并生成 ONNX 产物）"
                    )

            return {
                "ok": True,
                "analysis_available": sentiment_model_ready and embedding_model_ready,
                "sentiment_model_ready": sentiment_model_ready,
                "embedding_model_ready": embedding_model_ready,
                "missing_models": missing_models,
                "missing_details": missing_details,
                "sentiment_diagnosis": sentiment_diagnosis,
                "embedding_diagnosis": embedding_diagnosis,
                "error": None,
                "error_code": None,
                "error_detail": None,
            }
        except Exception as e:
            logger.error(f"[Bridge] 分析模型状态检查失败: {type(e).__name__}: {e}", exc_info=True)
            return {
                "ok": False,
                "analysis_available": False,
                "sentiment_model_ready": False,
                "embedding_model_ready": False,
                "missing_models": ["sentiment", "embedding"],
                "missing_details": [],
                "sentiment_diagnosis": {},
                "embedding_diagnosis": {},
                "error": str(e),
                "error_code": "UNKNOWN_ERROR",
                "error_detail": f"模型状态检查过程中发生异常: {type(e).__name__}: {e}",
            }

