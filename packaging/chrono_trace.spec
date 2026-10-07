# -*- mode: python ; coding: utf-8 -*-

import os
from importlib.metadata import PackageNotFoundError
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules, copy_metadata


SPEC_FILE = globals().get("__file__") or globals().get("SPEC")
PROJECT_ROOT = Path(SPEC_FILE).resolve().parents[1] if SPEC_FILE else Path(os.getcwd()).resolve()
APP_NAME = "ChronoTrace"  # 产物文件名不带空格；用户数据目录名在 config.APP_NAME（未改）
FRONTEND_DIST_DIR = PROJECT_ROOT / "frontend" / "webdist"
APP_ICON = PROJECT_ROOT / "chrono Trace.ico"
BUILD_INFO_FILE = PROJECT_ROOT / "packaging" / "generated" / "build_info.json"

if not FRONTEND_DIST_DIR.exists():
    raise SystemExit(
        "Missing frontend/webdist. Run `npm run build` in the frontend directory before building."
    )


def safe_copy_metadata(package_name: str):
    try:
        return copy_metadata(package_name)
    except PackageNotFoundError:
        print(f"[chrono_trace.spec] metadata not found for optional package: {package_name}")
        return []


datas = [
    (str(PROJECT_ROOT / "backend" / "app" / "db" / "schema.sql"), "backend/app/db"),
    (str(PROJECT_ROOT / "backend" / "app" / "db" / "migrations"), "backend/app/db/migrations"),
    (str(FRONTEND_DIST_DIR), "frontend/webdist"),
]
if BUILD_INFO_FILE.exists():
    datas.append((str(BUILD_INFO_FILE), "packaging/generated"))
datas += collect_data_files("webview")
datas += collect_data_files("jieba")
datas += copy_metadata("pywebview")
datas += safe_copy_metadata("modelscope")
# ONNX 模型内置（阶段 B：安装包捆绑 fp16 产物，免运行时下载）；
# 由 build 脚本在打包前运行 backend/scripts/export_models_onnx.py 生成
_MODELS_ROOT = PROJECT_ROOT / "backend" / "data" / "models"
# 双平台统一 bge（6.3× 提速、fp16 无损；公开中文基准不输 text2vec，
# 参数仅 1/4）——与 chrono_trace_linux.spec 同清单，默认变体直接命中。
# 变体机制保留：质量有诉求时可导出 text2vec 产物配置切回。
for _model_name in ("bge_small_zh_v15", "sentiment_3class"):
    # 只打发行所需文件——按精度实测择优（嵌入 fp32：bge CPU 快 32%；
    # 分类器 fp16：反快 14%），弃用的 int8/pc8 实验产物不进包
    _need_fp32 = _model_name.startswith("bge")
    _fname = "model.onnx" if _need_fp32 else "model.fp16.onnx"
    _model = _MODELS_ROOT / _model_name / "onnx" / _fname
    _tokenizer = _MODELS_ROOT / _model_name / "onnx" / "tokenizer"
    if _model.exists():
        datas.append((str(_model), f"models/{_model_name}/onnx"))
        if _tokenizer.exists():
            datas.append((str(_tokenizer), f"models/{_model_name}/onnx/tokenizer"))
    else:
        print(f"[chrono_trace.spec] WARNING: missing {_model} (run backend/scripts/export_models_onnx.py first)")




hiddenimports = [
    "webview",
    "wx_key",
    "modelscope",
    "modelscope.hub",
    "modelscope.hub.snapshot_download",
]
hiddenimports += collect_submodules("modelscope.hub")
# SciPy 1.18 vendors array-api-compat under a private package.  Recent
# transformers imports sklearn.metrics during lazy loading, which reaches
# this module through SciPy.  PyInstaller cannot reliably discover the
# dynamically referenced vendor modules, so collect them explicitly.
hiddenimports += collect_submodules("scipy._external.array_api_compat")


a = Analysis(
    [str(PROJECT_ROOT / "app.py")],
    pathex=[str(PROJECT_ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "pytest",
        "tkinter",
        "matplotlib",
        "tensorflow",
        "tensorboard",
        "tensorboardX",
        "torch",
        "torchvision",
        "torchaudio",
        "transformers",
        "sentence_transformers",
        "IPython",
        "notebook",
        "jupyter",
        "nltk",
    ],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=APP_NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    icon=str(APP_ICON) if APP_ICON.exists() else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name=APP_NAME,
)
