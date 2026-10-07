"""model_paths 变体与打包内置目录解析测试。

回归背景：Linux spec 改为只内置 bge 后，normalize_model_root_dir 判
「安装包内置模型」仍写死检查 text2vec 目录——bge-only 打包版会绕过
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
    (onnx_dir / "model.fp16.onnx").write_bytes(b"x")


def test_frozen_bge_only_bundle_uses_bundled_dir(frozen_env):
    """Linux 包形态：只内置 bge——必须命中内置目录（此前 text2vec 写死检查致绕过）。"""
    mp, bundled_root = frozen_env
    _make_variant_products(bundled_root, "bge_small_zh_v15")

    assert Path(mp.normalize_model_root_dir(None)) == bundled_root.resolve()
    # 默认变体 bge 直接命中，无回退
    assert mp.resolve_embedding_variant({}) == "bge_small_zh_v15"


def test_frozen_text2vec_only_bundle_uses_bundled_dir(frozen_env):
    """Windows 包形态：只内置 text2vec——内置目录同样命中，默认 bge 缺产物回退 text2vec。"""
    mp, bundled_root = frozen_env
    _make_variant_products(bundled_root, "text2vec_base_chinese")

    assert Path(mp.normalize_model_root_dir(None)) == bundled_root.resolve()
    assert mp.resolve_embedding_variant({}) == "text2vec_base_chinese"


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
