# -*- coding: utf-8 -*-
"""onefile 运行时：把解压目录放到 LocalAppData，避免交付目录出现 _internal。

父子进程（UI 再拉 packing/wcs/receiver）共用同一解压目录，减少重复解压。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def _setup() -> None:
    if not getattr(sys, "frozen", False):
        return
    # 已由 bootloader 解压过则不再改
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("TEMP") or str(Path.home())
    tmp = Path(base) / "PackingWorkbench" / "_pyi"
    try:
        tmp.mkdir(parents=True, exist_ok=True)
    except OSError:
        return
    # PyInstaller 6+：可通过环境变量提示 bootloader（部分版本在解压前读取）
    os.environ.setdefault("PYINSTALLER_RUNTIME_TMPDIR", str(tmp))


_setup()
