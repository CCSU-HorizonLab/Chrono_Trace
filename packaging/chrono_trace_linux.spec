# -*- mode: python ; coding: utf-8 -*-
# Linux 打包 spec（与 chrono_trace.spec 同构，差异：去 wx_key hiddenimport / 去 .ico 图标）

import os
from importlib.metadata import PackageNotFoundError
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules, copy_metadata


SPEC_FILE = globals().get("__file__") or globals().get("SPEC")
PROJECT_ROOT = Path(SPEC_FILE).resolve().parents[1] if SPEC_FILE else Path(os.getcwd()).resolve()
APP_NAME = "ChronoTrace"  # 产物文件名不带空格；用户数据目录名在 config.APP_NAME（未改）
FRONTEND_DIST_DIR = PROJECT_ROOT / "frontend" / "webdist"
BUILD_INFO_FILE = PROJECT_ROOT / "packaging" / "generated" / "build_info.json"

if not FRONTEND_DIST_DIR.exists():
    raise SystemExit(
        "Missing frontend/webdist. Run `npm run build` in the frontend directory before building."
    )


def safe_copy_metadata(package_name: str):
    try:
        return copy_metadata(package_name)
    except PackageNotFoundError:
        print(f"[chrono_trace_linux.spec] metadata not found for optional package: {package_name}")
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
# bge-small 是激活嵌入变体（6.3× 提速 + 仅 47MB vs text2vec 195MB）；
# 打包只内置 bge，variant 回退链兜底（model_paths.resolve_embedding_variant
# 会自动选有产物的变体）。text2vec 不再进包，省 148MB。
for _model_name in ("bge_small_zh_v15", "sentiment_3class"):
    # 只打发行所需文件（fp16 + tokenizer）——开发目录里的 fp32 基准与
    # 弃用的 int8/pc8 实验产物不进包（此前整目录收集让包体多了 1.5GB）
    _fp16 = _MODELS_ROOT / _model_name / "onnx" / "model.fp16.onnx"
    _tokenizer = _MODELS_ROOT / _model_name / "onnx" / "tokenizer"
    if _fp16.exists():
        datas.append((str(_fp16), f"models/{_model_name}/onnx"))
        if _tokenizer.exists():
            datas.append((str(_tokenizer), f"models/{_model_name}/onnx/tokenizer"))
    else:
        print(f"[chrono_trace.spec] WARNING: missing {_fp16} (run backend/scripts/export_models_onnx.py first)")




hiddenimports = [
    "webview",
    # Linux 无 wx_key 扩展（密钥走 keys/gdb_linux）；pywebview 使用 Qt 后端
    "qtpy",
    "modelscope",
    "modelscope.hub",
    "modelscope.hub.snapshot_download",
]
hiddenimports += collect_submodules("modelscope.hub")
hiddenimports += collect_submodules("scipy._external.array_api_compat")


# ---------- Linux 产物瘦身 ----------
# 1) Qt 模块裁剪：只保留 Qt 后端 + WebEngine 实际依赖（WebEngine 需要
#    Qml/Quick/WebChannel/QuickControls/Network/Wayland/Xcb 等，勿删）
_QT_MODULE_EXCLUDES = (
    # 注：libQt6Positioning 是 WebEngineCore/Widgets 的硬链接依赖（ldd 核实），不可裁
    # 注：libQt6Qml/Quick 也是 WebEngineCore 的 ldd 硬依赖，不可裁
    "libQt6Multimedia", "libQt6SpatialAudio",
    "libQt6Pdf",
    "libQt6RemoteObjects", "libQt6Sensors", "libQt6SerialPort",
    "libQt6Test", "libQt6TextToSpeech", "libQt6StateMachine",
    "libQt6QuickTest",
    # Quick3D 系列：WebEngine 不依赖（ldd 核实无 Quick3D），pywebview 不用
    "libQt6Quick3D",
    "libQt6PositioningQuick",
    "libQt6EglFSDeviceIntegration",
)
# 2) 数据裁剪：Qt 翻译只留中英、去 WebEngine devtools 资源（仅远程调试用）
def _keep_data(name: str) -> bool:
    if "qtwebengine_devtools_resources" in name:
        return False
    if "Qt6/translations/" in name or "/translations/" in name:
        if "qtwebengine_locales" in name:
            return "zh-CN" in name or "zh_CN" in name or "en-US" in name or name.endswith("en.pak")
        return False  # qt_*.qm 全部不需要（应用界面语言由前端控制）
    return True


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
        # GTK 栈（PyGObject/pycairo）是 pywebview 的可选 GTK 后端依赖；
        # 本项目 Linux 定死 Qt 后端——即便打包环境被误装（曾因调研 GTK
        # 后端引入，拖进 117M 图标/主题/重复ICU），也绝不进产物
        "gi",
        "pycairo",
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
        "win32gui",
        "win32con",
        "win32process",
        "win32api",
        "pywinauto",
        "wx_key",
    ],
    noarchive=False,
)
# 瘦身过滤（见上方清单）：未用 Qt 模块与翻译资源在进包前剔除
a.binaries = [b for b in a.binaries if not any(pat in b[0] for pat in _QT_MODULE_EXCLUDES)]
a.datas = [d for d in a.datas if _keep_data(d[0])]
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=APP_NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,  # 全量 strip 会打坏 scipy OpenBLAS 的 ELF 布局——瘦身由构建脚本选择性 strip
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    # Linux 无 .ico；如需图标在桌面快捷方式/打包外层配置
    icon=None,
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
