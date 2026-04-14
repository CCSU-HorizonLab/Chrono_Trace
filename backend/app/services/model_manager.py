"""Local model manager with optional background Hugging Face update checks."""

import json
import logging
import os
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
_global_update_started = set()


class ModelManager:
    """Manage locally cached models and optional background remote updates."""

    def __init__(
        self,
        model_dir: str,
        repo_id: str,
        mirror_endpoint: Optional[str] = "https://hf-mirror.com",
    ):
        self.model_dir = Path(model_dir)
        self.repo_id = repo_id
        self.mirror_endpoint = mirror_endpoint
        self._update_thread: Optional[threading.Thread] = None
        self._updating = False
        self._max_retry_attempts = 3
        self._retry_delay_seconds = 2
        self._request_timeout_seconds = 15
        self._download_status: Dict[str, Dict[str, Any]] = {}
        self._download_lock = threading.Lock()

    def _run_with_retries(self, operation_name: str, func, timeout_seconds: Optional[int] = None):
        """Run a remote operation with limited retries and fall back to local models on failure."""
        timeout = timeout_seconds or self._request_timeout_seconds

        for attempt in range(1, self._max_retry_attempts + 1):
            executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="HFRequest")
            future = executor.submit(func)
            try:
                return future.result(timeout=timeout)
            except FutureTimeoutError:
                logger.warning(
                    f"[模型管理] {operation_name} 超时 "
                    f"({attempt}/{self._max_retry_attempts}, {timeout}s)"
                )
            except Exception as e:
                logger.warning(
                    f"[模型管理] {operation_name} 失败 "
                    f"({attempt}/{self._max_retry_attempts}): {e}"
                )
            finally:
                executor.shutdown(wait=False, cancel_futures=True)

            if attempt < self._max_retry_attempts:
                time.sleep(self._retry_delay_seconds)

        logger.warning(f"[模型管理] {operation_name} 连续失败，回退到本地已有模型")
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
        """Return whether the local model directory is present and usable."""
        diagnosis = self.diagnose_model_status()
        if diagnosis["issue"]:
            logger.warning(f"[模型管理] 本地模型不可用: {diagnosis['issue']}")
            return False

        logger.debug(f"[模型管理] 本地模型可用: {self.model_dir}")
        return True

    def get_local_version(self) -> Optional[str]:
        """Return the locally recorded model version sha if available."""
        version_file = self.model_dir / VERSION_FILE
        if not version_file.exists():
            return None

        try:
            with open(version_file, "r", encoding="utf-8") as f:
                version_info = json.load(f)
            return version_info.get("commit_sha")
        except Exception as e:
            logger.error(f"[模型管理] 读取版本文件失败: {e}")
            return None

    def _save_local_version(self, commit_sha: str):
        """Persist the current remote version sha alongside the local model."""
        version_file = self.model_dir / VERSION_FILE
        version_info = {
            "commit_sha": commit_sha,
            "repo_id": self.repo_id,
            "updated_at": datetime.now().isoformat(),
        }

        try:
            with open(version_file, "w", encoding="utf-8") as f:
                json.dump(version_info, f, ensure_ascii=False, indent=2)
            logger.debug(f"[模型管理] 版本信息已保存: {commit_sha[:8]}...")
        except Exception as e:
            logger.error(f"[模型管理] 保存版本文件失败: {e}")

    def _set_download_status(self, task_id: str, **updates: Any):
        with self._download_lock:
            current = self._download_status.get(task_id, {}).copy()
            current.update(updates)
            self._download_status[task_id] = current

    def download_model(self, progress_callback=None) -> Dict[str, Any]:
        """
        Download the model to self.model_dir for first-time install or repair.

        Args:
            progress_callback: Optional callback receiving (step: str, percent: float)
        """
        temp_dir = self.model_dir.parent / f"{self.model_dir.name}_download_temp"
        backup_dir = self.model_dir.parent / f"{self.model_dir.name}_download_backup"
        old_endpoint = os.environ.get("HF_ENDPOINT")

        try:
            try:
                from huggingface_hub import model_info, snapshot_download
            except ImportError:
                return {
                    "success": False,
                    "model_dir": str(self.model_dir),
                    "error": "缺少 huggingface_hub 依赖，无法下载模型",
                    "error_code": "HF_NOT_INSTALLED",
                }

            if self.mirror_endpoint:
                os.environ["HF_ENDPOINT"] = self.mirror_endpoint

            if progress_callback:
                progress_callback("正在准备模型下载...", 5.0)

            if temp_dir.exists():
                shutil.rmtree(temp_dir, ignore_errors=True)

            remote_sha = None
            if progress_callback:
                progress_callback("正在获取模型版本信息...", 10.0)

            info = self._run_with_retries(
                "获取模型版本信息",
                lambda: model_info(self.repo_id),
            )
            if info is not None:
                remote_sha = getattr(info, "sha", None)

            if progress_callback:
                progress_callback("正在下载模型文件...", 30.0)

            download_result = self._run_with_retries(
                "下载模型",
                lambda: snapshot_download(
                    self.repo_id,
                    local_dir=str(temp_dir),
                    local_dir_use_symlinks=False,
                ),
                timeout_seconds=60,
            )
            if download_result is None:
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

            downloaded_manager = ModelManager(
                model_dir=str(temp_dir),
                repo_id=self.repo_id,
                mirror_endpoint=self.mirror_endpoint,
            )
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
            if remote_sha:
                self._save_local_version(remote_sha)

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
                "version": remote_sha,
            }
        except Exception as e:
            logger.error(f"[模型管理] 模型下载失败: {type(e).__name__}: {e}", exc_info=True)
            return {
                "success": False,
                "model_dir": str(self.model_dir),
                "error": f"{type(e).__name__}: {e}",
                "error_code": "UNKNOWN_ERROR",
            }
        finally:
            if temp_dir.exists():
                shutil.rmtree(temp_dir, ignore_errors=True)
            if old_endpoint is not None:
                os.environ["HF_ENDPOINT"] = old_endpoint
            elif "HF_ENDPOINT" in os.environ and self.mirror_endpoint:
                del os.environ["HF_ENDPOINT"]

    def download_model_async(self) -> str:
        """Start a background download task and return its task id."""
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
        """Return the current status for a background download task."""
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
        """Check for remote updates in the background without blocking startup."""
        global _global_update_started
        if self._updating or self.repo_id in _global_update_started:
            logger.debug("[模型管理] 已有更新任务在运行，跳过")
            return

        _global_update_started.add(self.repo_id)
        self._update_thread = threading.Thread(
            target=self._check_and_update,
            name="ModelUpdateChecker",
            daemon=True,
        )
        self._update_thread.start()

    def _check_and_update(self):
        """Background wrapper for remote update checks."""
        self._updating = True
        try:
            self._do_check_and_update()
        except Exception as e:
            logger.error(f"[模型管理] 后台更新检查失败: {e}")
        finally:
            self._updating = False
            global _global_update_started
            _global_update_started.discard(self.repo_id)

    def _do_check_and_update(self):
        """Check remote model metadata and download updates when available."""
        try:
            from huggingface_hub import model_info, snapshot_download
        except ImportError:
            logger.warning("[模型管理] huggingface_hub 未安装，跳过更新检查")
            return

        old_endpoint = os.environ.get("HF_ENDPOINT")
        if self.mirror_endpoint:
            os.environ["HF_ENDPOINT"] = self.mirror_endpoint

        try:
            if not self.ensure_model_exists():
                logger.info("[模型管理] 本地模型缺失或损坏，跳过后台自动更新，等待用户手动触发下载/修复")
                return

            logger.debug(f"[模型管理] 正在检查云端更新: {self.repo_id}")
            info = self._run_with_retries(
                "检查云端更新",
                lambda: model_info(self.repo_id),
            )
            if info is None:
                return

            remote_sha = info.sha
            if not remote_sha:
                logger.debug("[模型管理] 无法获取云端版本信息")
                return

            local_sha = self.get_local_version()
            if local_sha == remote_sha:
                logger.debug(f"[模型管理] 模型已经是最新版本: {remote_sha[:8]}...")
                return

            if local_sha:
                logger.info(f"[模型管理] 发现新版本: {local_sha[:8]}... -> {remote_sha[:8]}...")
            else:
                logger.info(f"[模型管理] 首次记录版本: {remote_sha[:8]}...")
                self._save_local_version(remote_sha)
                return

            temp_dir = self.model_dir.parent / f"{self.model_dir.name}_update_temp"
            logger.info("[模型管理] 正在下载模型更新...")

            download_result = self._run_with_retries(
                "下载模型更新",
                lambda: snapshot_download(
                    self.repo_id,
                    local_dir=str(temp_dir),
                    local_dir_use_symlinks=False,
                ),
                timeout_seconds=30,
            )
            if download_result is None:
                if temp_dir.exists():
                    shutil.rmtree(temp_dir, ignore_errors=True)
                return

            temp_manager = ModelManager(
                model_dir=str(temp_dir),
                repo_id=self.repo_id,
                mirror_endpoint=self.mirror_endpoint,
            )
            if temp_manager.diagnose_model_status()["issue"]:
                logger.error("[模型管理] 下载的模型校验失败，放弃更新")
                shutil.rmtree(temp_dir, ignore_errors=True)
                return

            backup_dir = self.model_dir.parent / f"{self.model_dir.name}_backup"
            try:
                if self.model_dir.exists():
                    if backup_dir.exists():
                        shutil.rmtree(backup_dir, ignore_errors=True)
                    shutil.move(str(self.model_dir), str(backup_dir))

                shutil.move(str(temp_dir), str(self.model_dir))
                self._save_local_version(remote_sha)
                logger.info(f"[模型管理] 模型已更新至 {remote_sha[:8]}...")

                if backup_dir.exists():
                    shutil.rmtree(backup_dir, ignore_errors=True)
            except Exception as e:
                logger.error(f"[模型管理] 替换模型失败: {e}")
                if backup_dir.exists() and not self.model_dir.exists():
                    shutil.move(str(backup_dir), str(self.model_dir))
                    logger.info("[模型管理] 已从备份恢复旧模型")
                if temp_dir.exists():
                    shutil.rmtree(temp_dir, ignore_errors=True)
        finally:
            if old_endpoint is not None:
                os.environ["HF_ENDPOINT"] = old_endpoint
            elif "HF_ENDPOINT" in os.environ:
                del os.environ["HF_ENDPOINT"]
