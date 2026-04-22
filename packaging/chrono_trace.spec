# -*- mode: python ; coding: utf-8 -*-

import os
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, copy_metadata


SPEC_FILE = globals().get("__file__") or globals().get("SPEC")
PROJECT_ROOT = Path(SPEC_FILE).resolve().parents[1] if SPEC_FILE else Path(os.getcwd()).resolve()
APP_NAME = "Chrono Trace"
FRONTEND_DIST_DIR = PROJECT_ROOT / "frontend" / "webdist"
APP_ICON = PROJECT_ROOT / "chrono Trace.ico"

if not FRONTEND_DIST_DIR.exists():
    raise SystemExit(
        "Missing frontend/webdist. Run `npm run build` in the frontend directory before building."
    )


datas = [
    (str(PROJECT_ROOT / "backend" / "app" / "db" / "schema.sql"), "backend/app/db"),
    (str(PROJECT_ROOT / "backend" / "app" / "db" / "migrations"), "backend/app/db/migrations"),
    (str(FRONTEND_DIST_DIR), "frontend/webdist"),
]
datas += collect_data_files("webview")
datas += collect_data_files("jieba")
datas += copy_metadata("pywebview")
datas += copy_metadata("transformers")
datas += copy_metadata("sentence-transformers")
datas += copy_metadata("modelscope")


hiddenimports = [
    "webview",
    "transformers",
    "sentence_transformers",
]


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
