# -*- mode: python ; coding: utf-8 -*-
# Linux 打包 spec（与 chrono_trace.spec 同构，差异：去 wx_key hiddenimport / 去 .ico 图标）

import os
from importlib.metadata import PackageNotFoundError
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules, copy_metadata


SPEC_FILE = globals().get("__file__") or globals().get("SPEC")
PROJECT_ROOT = Path(SPEC_FILE).resolve().parents[1] if SPEC_FILE else Path(os.getcwd()).resolve()
APP_NAME = "Chrono Trace"
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
datas += copy_metadata("transformers")
datas += copy_metadata("sentence-transformers")
datas += safe_copy_metadata("modelscope")


hiddenimports = [
    "webview",
    # Linux 无 wx_key 扩展（密钥走 keys/gdb_linux）；pywebview 使用 Qt 后端
    "qtpy",
    "transformers",
    "sentence_transformers",
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
    "libQt6Multimedia", "libQt6SpatialAudio",
    "libQt6Pdf",
    "libQt6RemoteObjects", "libQt6Sensors", "libQt6SerialPort",
    "libQt6Test", "libQt6TextToSpeech", "libQt6StateMachine",
    "libQt6QuickTest",
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
        "tkinter",
        "matplotlib",
        "tensorflow",
        "tensorboard",
        "tensorboardX",
        "torchvision",
        "torchaudio",
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
