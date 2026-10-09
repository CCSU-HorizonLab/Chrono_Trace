from __future__ import annotations

import json
from typing import Any

from .config import IS_FROZEN, RESOURCE_ROOT_PATH


BUILD_INFO_PATH = RESOURCE_ROOT_PATH / "packaging" / "generated" / "build_info.json"


def get_build_info() -> dict[str, Any]:
    if not BUILD_INFO_PATH.exists():
        return {}
    try:
        return json.loads(BUILD_INFO_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def get_build_variant() -> str:
    """构建变体标识（打包脚本写入 build_info.json；开发态 dev）。

    torch 时代的「运行时下载 CUDA PyTorch overlay」链路已随 ONNX/DirectML
    单后端整体移除：onnxruntime-directml 免 CUDA 免 torch，安装包单变体
    通吃 CPU/GPU，本模块只剩构建信息读取。
    """
    if not IS_FROZEN:
        return "dev"
    return str(get_build_info().get("variant") or "").strip().lower() or "dev"
