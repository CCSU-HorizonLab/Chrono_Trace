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
