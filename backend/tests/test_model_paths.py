"""model_paths 打包内置目录解析测试。

回归背景：Linux spec 改为只内置 bge 后，normalize_model_root_dir 判
「安装包内置模型」曾写死检查旧嵌入目录——bge-only 打包版会绕过
内置目录（包里 46M 模型找不到，运行时转用户数据目录/下载）。
"""
import sys
from pathlib import Path

import pytest

backend_root = str(Path(__file__).resolve().parents[1])
if backend_root not in sys.path:
    sys.path.insert(0, backend_root)

from app.services import model_paths as mp


@pytest.fixture
def frozen_env(tmp_path, monkeypatch):
    """伪造 frozen 环境：内置根指向临时目录，返回 (model_paths, bundled_root)。"""
    bundled_root = tmp_path / "resources" / "models"
    monkeypatch.setattr(mp, "IS_FROZEN", True)
    monkeypatch.setattr(mp, "RESOURCE_ROOT_PATH", tmp_path / "resources")
    monkeypatch.setattr(mp, "MODELS_DIR_PATH", tmp_path / "userdata" / "models")
    return mp, bundled_root


def _make_variant_products(bundled_root: Path, dirname: str) -> None:
    onnx_dir = bundled_root / dirname / "onnx"
    onnx_dir.mkdir(parents=True)
    (onnx_dir / "model.onnx").write_bytes(b"x")


def test_frozen_bge_only_bundle_uses_bundled_dir(frozen_env):
    """打包形态：只内置 bge——必须命中内置目录（此前写死检查旧嵌入目录致绕过）。"""
    mp, bundled_root = frozen_env
    _make_variant_products(bundled_root, "bge_small_zh_v15")

    assert Path(mp.normalize_model_root_dir(None)) == bundled_root.resolve()


def test_frozen_custom_dir_with_models_wins_over_bundle(frozen_env, tmp_path):
    """用户显式配置且有模型的目录优先于内置目录。"""
    mp, bundled_root = frozen_env
    _make_variant_products(bundled_root, "bge_small_zh_v15")
    custom = tmp_path / "custom-models"
    _make_variant_products(custom, "bge_small_zh_v15")

    assert Path(mp.normalize_model_root_dir(str(custom))) == custom.resolve()


def test_frozen_custom_dir_without_models_falls_back_to_bundle(frozen_env, tmp_path):
    """配置目录没有 ONNX 产物时回落内置目录。"""
    mp, bundled_root = frozen_env
    _make_variant_products(bundled_root, "bge_small_zh_v15")
    empty_custom = tmp_path / "empty-custom"
    empty_custom.mkdir()

    assert Path(mp.normalize_model_root_dir(str(empty_custom))) == bundled_root.resolve()
