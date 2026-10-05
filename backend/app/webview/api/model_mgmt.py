"""分析模型状态与下载管理——从 bridge.py 拆出（步骤 3 mixin）。

Bridge 继承此 Mixin，方法名不变、前端 API 面与测试零破坏。
"""
from __future__ import annotations

import logging
import threading
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


import shutil, uuid
from ...services.model_paths import EMBEDDING_MODEL_DIRNAME, EMBEDDING_MODEL_REPO_ID, MODEL_ROOT_DIR_KEY, SENTIMENT_MODEL_DIRNAME, SENTIMENT_MODEL_REPO_ID, get_embedding_model_dir, get_model_root_dir, get_sentiment_model_dir, normalize_model_root_dir

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
            repo_id=EMBEDDING_MODEL_REPO_ID,
        ).diagnose_model_status()
        diagnosis["can_recover"] = True
        return diagnosis

    def _download_embedding_model(self, progress_callback=None) -> dict[str, Any]:
        from ...services.model_manager import ModelManager

        return ModelManager(
            model_dir=str(get_embedding_model_dir(self.settings)),
            repo_id=EMBEDDING_MODEL_REPO_ID,
        ).download_model(progress_callback=progress_callback)

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
                    "skipped_models": [SENTIMENT_MODEL_DIRNAME, EMBEDDING_MODEL_DIRNAME],
                }

            moved: list[tuple[Path, Path]] = []
            skipped: list[str] = []
            try:
                for dirname in (SENTIMENT_MODEL_DIRNAME, EMBEDDING_MODEL_DIRNAME):
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

            sentiment_model_ready = not sentiment_diagnosis["issue"]
            embedding_model_ready = not embedding_diagnosis["issue"]

            missing_models = []
            missing_details = []

            if not sentiment_model_ready:
                missing_models.append("sentiment")
                missing_details.append({
                    "model_name": "情感分类模型",
                    "model_key": "sentiment",
                    "repo_id": sentiment_diagnosis.get("repo_id"),
                    "issue": sentiment_diagnosis.get("issue") or "情感分类模型不可用",
                    "can_auto_download": False,
                })

            if not embedding_model_ready:
                missing_models.append("embedding")
                missing_details.append({
                    "model_name": "文本向量模型",
                    "model_key": "embedding",
                    "repo_id": embedding_diagnosis.get("repo_id"),
                    "issue": embedding_diagnosis.get("issue") or "文本向量模型不可用",
                    "can_auto_download": False,
                })
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

    def download_analysis_models(self) -> dict[str, Any]:
        """Start downloading all missing analysis models in the background."""
        try:
            model_status = self.check_analysis_model_status()
            if not model_status.get("ok"):
                return {
                    "ok": False,
                    "error": model_status.get("error") or "模型状态检查失败",
                    "error_code": model_status.get("error_code") or "UNKNOWN_ERROR",
                    "error_detail": model_status.get("error_detail") or "无法启动模型下载",
                }

            models_to_download = model_status.get("missing_models", [])
            if not models_to_download:
                return {
                    "ok": True,
                    "task_id": None,
                    "models_to_download": [],
                    "status": "completed",
                }

            # 加 uuid 后缀防撞号：同秒内重复点击下载时按秒生成的 task_id 会互相覆盖
            task_id = f"analysis_model_download_{int(time.time())}_{uuid.uuid4().hex[:8]}"
            self._update_model_download_status(
                task_id,
                status="downloading",
                overall_progress=0.0,
                current_model=models_to_download[0],
                current_step="等待开始下载...",
                completed_models=[],
                failed_models=[],
                error=None,
                error_code=None,
                error_detail=None,
                models_to_download=models_to_download,
            )

            def _run():
                completed_models = []
                failed_models = []
                total_models = len(models_to_download)

                try:
                    for index, model_key in enumerate(models_to_download):
                        base_progress = (index / total_models) * 100.0
                        span = 100.0 / total_models

                        def _progress(step: str, percent: float):
                            overall = base_progress + span * (max(0.0, min(100.0, float(percent))) / 100.0)
                            self._update_model_download_status(
                                task_id,
                                status="downloading",
                                overall_progress=overall,
                                current_model=model_key,
                                current_step=step,
                                completed_models=completed_models.copy(),
                                failed_models=failed_models.copy(),
                            )

                        if model_key == "sentiment":
                            result = self._get_sentiment_model_manager().download_model(progress_callback=_progress)
                        else:
                            result = self._download_embedding_model(progress_callback=_progress)

                        if result.get("success"):
                            completed_models.append(model_key)
                            self._update_model_download_status(
                                task_id,
                                status="downloading",
                                overall_progress=base_progress + span,
                                current_model=model_key,
                                current_step=f"{model_key} 模型下载完成",
                                completed_models=completed_models.copy(),
                                failed_models=failed_models.copy(),
                            )
                        else:
                            failed_models.append(model_key)
                            error = result.get("error") or f"{model_key} 模型下载失败"
                            error_code = result.get("error_code") or "UNKNOWN_ERROR"
                            self._update_model_download_status(
                                task_id,
                                status="failed",
                                overall_progress=base_progress,
                                current_model=model_key,
                                current_step=f"{model_key} 模型下载失败",
                                completed_models=completed_models.copy(),
                                failed_models=failed_models.copy(),
                                error=error,
                                error_code=error_code,
                                error_detail=error,
                            )
                            return

                    self._update_model_download_status(
                        task_id,
                        status="completed",
                        overall_progress=100.0,
                        current_model=models_to_download[-1],
                        current_step="缺失模型下载完成",
                        completed_models=completed_models.copy(),
                        failed_models=failed_models.copy(),
                        error=None,
                        error_code=None,
                        error_detail=None,
                    )
                except Exception as e:
                    logger.error(f"[Bridge] 模型下载任务失败: {type(e).__name__}: {e}", exc_info=True)
                    current_status = self._get_model_download_status(task_id)
                    self._update_model_download_status(
                        task_id,
                        status="failed",
                        overall_progress=current_status.get("overall_progress", 0.0),
                        current_model=current_status.get("current_model"),
                        current_step="模型下载失败",
                        completed_models=completed_models.copy(),
                        failed_models=failed_models.copy(),
                        error=str(e),
                        error_code="UNKNOWN_ERROR",
                        error_detail=f"{type(e).__name__}: {e}",
                    )

            threading.Thread(target=_run, name=f"AnalysisModelDownload-{task_id}", daemon=True).start()

            return {
                "ok": True,
                "task_id": task_id,
                "models_to_download": models_to_download,
            }
        except Exception as e:
            logger.error(f"[Bridge] 启动模型下载失败: {type(e).__name__}: {e}", exc_info=True)
            return {
                "ok": False,
                "error": str(e),
                "error_code": "UNKNOWN_ERROR",
                "error_detail": f"{type(e).__name__}: {e}",
            }

    def get_model_download_progress(self, task_id: str) -> dict[str, Any]:
        """Query analysis model download progress."""
        try:
            status = self._get_model_download_status(task_id)
            if not status:
                return {
                    "ok": False,
                    "status": "not_found",
                    "overall_progress": 0.0,
                    "current_model": None,
                    "current_step": "",
                    "completed_models": [],
                    "failed_models": [],
                    "error": "下载任务不存在",
                    "error_code": "TASK_NOT_FOUND",
                    "error_detail": "未找到对应的模型下载任务",
                }

            return {
                "ok": True,
                "status": status.get("status", "downloading"),
                "overall_progress": status.get("overall_progress", 0.0),
                "current_model": status.get("current_model"),
                "current_step": status.get("current_step", ""),
                "completed_models": status.get("completed_models", []),
                "failed_models": status.get("failed_models", []),
                "error": status.get("error"),
                "error_code": status.get("error_code"),
                "error_detail": status.get("error_detail"),
            }
        except Exception as e:
            logger.error(f"[Bridge] 获取模型下载进度失败: {type(e).__name__}: {e}", exc_info=True)
            return {
                "ok": False,
                "status": "failed",
                "overall_progress": 0.0,
                "current_model": None,
                "current_step": "",
                "completed_models": [],
                "failed_models": [],
                "error": str(e),
                "error_code": "UNKNOWN_ERROR",
                "error_detail": f"{type(e).__name__}: {e}",
            }

