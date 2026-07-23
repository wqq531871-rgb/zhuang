# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller onefile spec：交付目录只有 exe + 配置 + 工作区，无 _internal、无 .py 源码。"""

import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_submodules

SPECDIR = Path(SPEC).resolve().parent
ROOT = SPECDIR.parent  # packing-system

# Prefer packing/src over the top-level src/ tree
sys.path.insert(0, str(ROOT / "packing"))
sys.path.insert(0, str(ROOT / "local_wcs_receiver"))
sys.path.insert(0, str(ROOT / "ui"))

block_cipher = None

ortools_datas, ortools_binaries, ortools_hidden = collect_all("ortools")
pyqt_datas, pyqt_binaries, pyqt_hidden = collect_all("PyQt5")
np_datas, np_binaries, np_hidden = collect_all("numpy")
pd_datas, pd_binaries, pd_hidden = collect_all("pandas")

# 只打配置进包（yaml），不要把 ui/src/app 的 .py 当 datas（否则对方能直接打开源码）
datas = []
datas += ortools_datas + pyqt_datas + np_datas + pd_datas
datas += [
    (str(ROOT / "config"), "config"),
    (str(ROOT / "local_wcs_receiver" / "config"), "local_wcs_receiver/config"),
]

binaries = []
binaries += ortools_binaries + pyqt_binaries + np_binaries + pd_binaries

hiddenimports = []
hiddenimports += ortools_hidden + pyqt_hidden + np_hidden + pd_hidden
hiddenimports += collect_submodules("src")
hiddenimports += collect_submodules("app")
hiddenimports += [
    "yaml",
    "openpyxl",
    "pymysql",
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
    "app_launcher",
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
        str(ROOT),
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

# onefile：所有依赖打进单个 exe；运行时解压到用户本地 AppData，不在交付目录留 _internal
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="PackingWorkbench",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,  # 由 runtime_hook 指到 %LOCALAPPDATA%
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
