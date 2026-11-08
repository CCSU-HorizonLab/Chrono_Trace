"""本地模型目录诊断（只读）。

ModelScope 运行时下载链路已随「模型内置安装包 / git 分发」移除——推理是
ONNX 单后端，应用内下载源模型权重救不了缺失的 onnx/ 产物（假修复）。
本类只保留存在性/版本诊断，供设置页模型状态检查展示用。
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

VERSION_FILE = "model_version.json"


class ModelManager:
    """Manage a local model directory."""

    def __init__(self, model_dir: str, repo_id: str):
        self.model_dir = Path(model_dir)
        self.repo_id = repo_id

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
