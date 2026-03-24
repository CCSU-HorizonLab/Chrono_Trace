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
from typing import Optional

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

        logger.warning(f"[模型管理] {operation_name} 连续失败，回退到本地现有模型")
        return None

    def ensure_model_exists(self) -> bool:
        """Return whether the local model directory is present and usable."""
        config_file = self.model_dir / "config.json"
        if not self.model_dir.exists() or not config_file.exists():
            logger.warning(f"[模型管理] 本地模型不存在: {self.model_dir}")
            logger.warning("[模型管理] 请先运行训练脚本或手动放置模型文件")
            return False

        has_weights = any(self.model_dir.glob("*.safetensors")) or any(self.model_dir.glob("*.bin"))
        if not has_weights:
            logger.warning(f"[模型管理] 本地模型目录缺少权重文件: {self.model_dir}")
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
                logger.debug(f"[模型管理] 模型已是最新版本: {remote_sha[:8]}...")
                return

            if local_sha:
                logger.info(f"[模型管理] 发现新版本: {local_sha[:8]}... -> {remote_sha[:8]}...")
            else:
                logger.info(f"[模型管理] 首次记录版本: {remote_sha[:8]}...")
                if self.ensure_model_exists():
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

            temp_config = temp_dir / "config.json"
            if not temp_config.exists():
                logger.error("[模型管理] 下载的模型缺少 config.json，放弃更新")
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
                logger.info(f"[模型管理] 模型已更新至 {remote_sha[:8]}...，下次启动生效")

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
