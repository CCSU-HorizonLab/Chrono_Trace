from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from .config import RESOURCE_ROOT_PATH, USER_DATA_DIR_PATH, ensure_directory


GPU_RUNTIME_ROOT_PATH = ensure_directory(USER_DATA_DIR_PATH / "runtime" / "gpu")
GPU_EMBEDDED_PYTHON_DIR_PATH = GPU_RUNTIME_ROOT_PATH / "python-embed"
GPU_SITE_PACKAGES_PATH = ensure_directory(GPU_RUNTIME_ROOT_PATH / "site-packages")
GPU_INSTALL_STATE_PATH = GPU_RUNTIME_ROOT_PATH / "install_state.json"
BUILD_INFO_PATH = RESOURCE_ROOT_PATH / "packaging" / "generated" / "build_info.json"


def get_gpu_install_state() -> dict[str, Any]:
    if not GPU_INSTALL_STATE_PATH.exists():
        return {}
    try:
        return json.loads(GPU_INSTALL_STATE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_gpu_install_state(payload: dict[str, Any]) -> None:
    ensure_directory(GPU_RUNTIME_ROOT_PATH)
    GPU_INSTALL_STATE_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def clear_gpu_install_state() -> None:
    if GPU_INSTALL_STATE_PATH.exists():
        GPU_INSTALL_STATE_PATH.unlink()


def get_build_info() -> dict[str, Any]:
    if not BUILD_INFO_PATH.exists():
        return {}
    try:
        return json.loads(BUILD_INFO_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def get_build_variant() -> str:
    variant = str(get_build_info().get("variant") or "").strip().lower()
    if variant in {"cpu", "gpu"}:
        return variant
    return "dev"


def has_gpu_overlay() -> bool:
    return (
        GPU_SITE_PACKAGES_PATH.exists()
        and (GPU_SITE_PACKAGES_PATH / "torch").exists()
        and GPU_INSTALL_STATE_PATH.exists()
    )


def activate_gpu_overlay_path() -> bool:
    if not GPU_INSTALL_STATE_PATH.exists():
        return False
    state = get_gpu_install_state()
    if not state.get("active", True):
        return False
    if not has_gpu_overlay():
        return False

    site_packages = str(GPU_SITE_PACKAGES_PATH)
    if site_packages in sys.path:
        sys.path.remove(site_packages)
    sys.path.insert(0, site_packages)
    return True
