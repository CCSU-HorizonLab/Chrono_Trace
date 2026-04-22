"""Local model manager backed by ModelScope downloads."""

from __future__ import annotations

import json
import logging
import shutil
import threading
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional
from uuid import uuid4

logger = logging.getLogger(__name__)

VERSION_FILE = "model_version.json"


class ModelManager:
    """Manage a local model directory and download missing assets from ModelScope."""

    def __init__(self, model_dir: str, repo_id: str):
        self.model_dir = Path(model_dir)
        self.repo_id = repo_id
        self._max_retry_attempts = 3
        self._retry_delay_seconds = 2
        self._request_timeout_seconds = 30
        self._download_status: Dict[str, Dict[str, Any]] = {}
        self._download_lock = threading.Lock()

    def _run_with_retries(self, operation_name: str, func, timeout_seconds: Optional[int] = None):
        timeout = timeout_seconds or self._request_timeout_seconds

        for attempt in range(1, self._max_retry_attempts + 1):
            executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="ModelScopeRequest")
            future = executor.submit(func)
            try:
                return future.result(timeout=timeout)
            except FutureTimeoutError:
                logger.warning(
                    "[模型管理] %s 超时 (%s/%s, %ss)",
                    operation_name,
                    attempt,
                    self._max_retry_attempts,
                    timeout,
                )
            except Exception as exc:
                logger.warning(
                    "[模型管理] %s 失败 (%s/%s): %s",
                    operation_name,
                    attempt,
                    self._max_retry_attempts,
                    exc,
                )
            finally:
                executor.shutdown(wait=False, cancel_futures=True)

            if attempt < self._max_retry_attempts:
                time.sleep(self._retry_delay_seconds)

        logger.warning("[模型管理] %s 连续失败，回退到本地已有模型", operation_name)
        return None

    def diagnose_model_status(self) -> Dict[str, Any]:
        """Return a detailed diagnosis of the local model directory."""
        config_file = self.model_dir / "config.json"
        tokenizer_candidates = (
            "tokenizer.json",
            "tokenizer_config.json",
            "vocab.txt",
            "vocab.json",
            "merges.txt",
            "special_tokens_map.json",
            "spiece.model",
        )

        exists = self.model_dir.exists()
        has_config = config_file.exists()
        has_weights = False
        has_tokenizer = False
        if exists:
            has_weights = any(self.model_dir.glob("*.safetensors")) or any(self.model_dir.glob("*.bin"))
            has_tokenizer = any((self.model_dir / name).exists() for name in tokenizer_candidates)

        issue = None
        if not exists:
            issue = f"模型目录不存在: {self.model_dir}"
        elif not has_config:
            issue = f"模型目录缺少 config.json: {self.model_dir}"
        elif not has_weights:
            issue = f"模型目录缺少权重文件(.safetensors/.bin): {self.model_dir}"
        elif not has_tokenizer:
            issue = f"模型目录缺少 tokenizer 文件: {self.model_dir}"

        return {
            "exists": exists,
            "has_config": has_config,
            "has_weights": has_weights,
            "has_tokenizer": has_tokenizer,
            "model_dir": str(self.model_dir),
            "repo_id": self.repo_id,
            "version": self.get_local_version(),
            "issue": issue,
            "can_recover": bool(issue),
        }

    def ensure_model_exists(self) -> bool:
        diagnosis = self.diagnose_model_status()
        if diagnosis["issue"]:
            logger.warning("[模型管理] 本地模型不可用: %s", diagnosis["issue"])
            return False

        logger.debug("[模型管理] 本地模型可用: %s", self.model_dir)
        return True

    def get_local_version(self) -> Optional[str]:
        version_file = self.model_dir / VERSION_FILE
        if not version_file.exists():
            return None

        try:
            version_info = json.loads(version_file.read_text(encoding="utf-8"))
            return (
                version_info.get("revision")
                or version_info.get("commit_sha")
                or version_info.get("version")
            )
        except Exception as exc:
            logger.error("[模型管理] 读取版本文件失败: %s", exc)
            return None

    def _save_local_version(self, revision: Optional[str]):
        version_file = self.model_dir / VERSION_FILE
        version_info = {
            "revision": revision or "master",
            "repo_id": self.repo_id,
            "updated_at": datetime.now().isoformat(),
        }

        try:
            version_file.write_text(
                json.dumps(version_info, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as exc:
            logger.error("[模型管理] 保存版本文件失败: %s", exc)

    def _set_download_status(self, task_id: str, **updates: Any):
        with self._download_lock:
            current = self._download_status.get(task_id, {}).copy()
            current.update(updates)
            self._download_status[task_id] = current

    def download_model(self, progress_callback=None) -> Dict[str, Any]:
        """Download the model into ``self.model_dir`` for first install or repair."""
        temp_dir = self.model_dir.parent / f"{self.model_dir.name}_download_temp"
        backup_dir = self.model_dir.parent / f"{self.model_dir.name}_download_backup"

        try:
            try:
                from modelscope.hub.snapshot_download import snapshot_download
            except ImportError:
                return {
                    "success": False,
                    "model_dir": str(self.model_dir),
                    "error": "缺少 modelscope 依赖，无法下载模型",
                    "error_code": "MODELSCOPE_NOT_INSTALLED",
                }

            if progress_callback:
                progress_callback("正在准备模型下载...", 5.0)

            if temp_dir.exists():
                shutil.rmtree(temp_dir, ignore_errors=True)
            temp_dir.parent.mkdir(parents=True, exist_ok=True)

            if progress_callback:
                progress_callback("正在从 ModelScope 下载模型文件...", 30.0)

            revision = self._run_with_retries(
                "下载模型",
                lambda: snapshot_download(
                    self.repo_id,
                    cache_dir=str(temp_dir.parent),
                    local_dir=str(temp_dir),
                    ),
                timeout_seconds=120,
            )
            if revision is None:
                if temp_dir.exists():
                    shutil.rmtree(temp_dir, ignore_errors=True)
                return {
                    "success": False,
                    "model_dir": str(self.model_dir),
                    "error": f"模型下载失败: {self.repo_id}",
                    "error_code": "NETWORK_ERROR",
                }

            if progress_callback:
                progress_callback("正在校验模型文件...", 80.0)

            downloaded_manager = ModelManager(model_dir=str(temp_dir), repo_id=self.repo_id)
            downloaded_diagnosis = downloaded_manager.diagnose_model_status()
            if downloaded_diagnosis["issue"]:
                shutil.rmtree(temp_dir, ignore_errors=True)
                return {
                    "success": False,
                    "model_dir": str(self.model_dir),
                    "error": downloaded_diagnosis["issue"],
                    "error_code": "MODEL_VALIDATION_FAILED",
                }

            if progress_callback:
                progress_callback("正在替换本地模型...", 90.0)

            if backup_dir.exists():
                shutil.rmtree(backup_dir, ignore_errors=True)
            if self.model_dir.exists():
                shutil.move(str(self.model_dir), str(backup_dir))

            shutil.move(str(temp_dir), str(self.model_dir))
            self._save_local_version("master")

            final_diagnosis = self.diagnose_model_status()
            if final_diagnosis["issue"]:
                if self.model_dir.exists():
                    shutil.rmtree(self.model_dir, ignore_errors=True)
                if backup_dir.exists():
                    shutil.move(str(backup_dir), str(self.model_dir))
                return {
                    "success": False,
                    "model_dir": str(self.model_dir),
                    "error": final_diagnosis["issue"],
                    "error_code": "MODEL_VALIDATION_FAILED",
                }

            if backup_dir.exists():
                shutil.rmtree(backup_dir, ignore_errors=True)

            if progress_callback:
                progress_callback("模型下载完成", 100.0)

            return {
                "success": True,
                "model_dir": str(self.model_dir),
                "error": None,
                "error_code": None,
                "version": "master",
            }
        except Exception as exc:
            logger.error("[模型管理] 模型下载失败: %s: %s", type(exc).__name__, exc, exc_info=True)
            return {
                "success": False,
                "model_dir": str(self.model_dir),
                "error": f"{type(exc).__name__}: {exc}",
                "error_code": "UNKNOWN_ERROR",
            }
        finally:
            if temp_dir.exists():
                shutil.rmtree(temp_dir, ignore_errors=True)

    def download_model_async(self) -> str:
        task_id = f"model_download_{int(time.time())}_{uuid4().hex[:8]}"
        self._set_download_status(
            task_id,
            status="downloading",
            progress=0.0,
            step="等待开始下载...",
            error=None,
            error_code=None,
        )

        def _progress(step: str, percent: float):
            self._set_download_status(
                task_id,
                status="downloading",
                progress=max(0.0, min(100.0, float(percent))),
                step=step,
            )

        def _run():
            result = self.download_model(progress_callback=_progress)
            if result.get("success"):
                self._set_download_status(
                    task_id,
                    status="completed",
                    progress=100.0,
                    step="模型下载完成",
                    error=None,
                    error_code=None,
                )
            else:
                current_progress = self.get_download_progress(task_id).get("progress", 0.0)
                self._set_download_status(
                    task_id,
                    status="failed",
                    progress=current_progress,
                    step="模型下载失败",
                    error=result.get("error"),
                    error_code=result.get("error_code"),
                )

        threading.Thread(target=_run, name=f"ModelDownloader-{task_id}", daemon=True).start()
        return task_id

    def get_download_progress(self, task_id: str) -> Dict[str, Any]:
        with self._download_lock:
            progress = self._download_status.get(task_id)
        if progress is None:
            return {
                "status": "not_found",
                "progress": 0.0,
                "step": "",
                "error": "下载任务不存在",
                "error_code": "TASK_NOT_FOUND",
            }
        return progress.copy()

    def check_and_update_async(self):
        """Model updates are user-driven in the ModelScope-only flow."""
        logger.debug("[模型管理] 已禁用后台自动更新检查，等待用户手动触发下载/修复")
