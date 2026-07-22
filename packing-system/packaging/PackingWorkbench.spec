# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for PackingWorkbench (no source delivery)."""

import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_submodules

SPECDIR = Path(SPEC).resolve().parent
ROOT = SPECDIR.parent  # packing-system

# Prefer packing/src over the top-level src/ tree
sys.path.insert(0, str(ROOT / "packing"))
sys.path.insert(0, str(ROOT / "local_wcs_receiver"))

block_cipher = None

# Heavy / binary-heavy deps
ortools_datas, ortools_binaries, ortools_hidden = collect_all("ortools")
pyqt_datas, pyqt_binaries, pyqt_hidden = collect_all("PyQt5")
np_datas, np_binaries, np_hidden = collect_all("numpy")
pd_datas, pd_binaries, pd_hidden = collect_all("pandas")

datas = []
datas += ortools_datas + pyqt_datas + np_datas + pd_datas
datas += [
    (str(ROOT / "config"), "config"),
    (str(ROOT / "local_wcs_receiver" / "config"), "local_wcs_receiver/config"),
    (str(ROOT / "local_wcs_receiver" / "app"), "local_wcs_receiver/app"),
    (str(ROOT / "packing" / "src"), "src"),
    (str(ROOT / "ui"), "ui"),
]

binaries = []
binaries += ortools_binaries + pyqt_binaries + np_binaries + pd_binaries

hiddenimports = []
hiddenimports += ortools_hidden + pyqt_hidden + np_hidden + pd_hidden
hiddenimports += collect_submodules("src")
hiddenimports += collect_submodules("app")  # local_wcs_receiver.app when on path
hiddenimports += [
    "yaml",
    "openpyxl",
    "PyQt5",
    "PyQt5.QtCore",
    "PyQt5.QtGui",
    "PyQt5.QtWidgets",
    "pyqtgraph",
    "OpenGL",
    "fastapi",
    "uvicorn",
    "uvicorn.logging",
    "uvicorn.loops",
    "uvicorn.loops.auto",
    "uvicorn.protocols",
    "uvicorn.protocols.http",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.websockets",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.lifespan",
    "uvicorn.lifespan.on",
    "pydantic",
    "starlette",
    "requests",
    "run_packing",
    "run_wcs_service",
    "run_receiver",
    "realtime_dashboard_v3_clean",
    "realtime_dashboard_v2",
    "stability_business_dashboard_json",
    "dashboard_state",
    "runtime_paths",
    "sequence_order",
    "result_sequence_update",
]

a = Analysis(
    [str(ROOT / "packing" / "freeze_entry.py")],
    pathex=[
        str(ROOT / "packing"),
        str(ROOT / "ui"),
        str(ROOT / "local_wcs_receiver"),
        str(ROOT),  # 仅用于找到 app_launcher.py；run_packing 由 packing/ 优先
    ],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "pytest",
        "IPython",
        "tkinter",
        "sphinx",
        "matplotlib",
        "scipy",
        "pyarrow",
        "notebook",
        "jedi",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="PackingWorkbench",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,  # 保留控制台，保证子进程 packing/wcs 日志可被 UI 管道捕获
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="PackingWorkbench",
)
