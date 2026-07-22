# -*- coding: utf-8 -*-
"""PyInstaller 入口（放在 packing/ 下，避免与仓库根 run_packing.py 同名冲突）。"""

from __future__ import annotations

import sys
from pathlib import Path

_PACKING_DIR = Path(__file__).resolve().parent
_ROOT = _PACKING_DIR.parent

# packing/ 必须优先，保证 import run_packing 命中本目录
if str(_PACKING_DIR) in sys.path:
    sys.path.remove(str(_PACKING_DIR))
sys.path.insert(0, str(_PACKING_DIR))
if str(_ROOT) not in sys.path:
    sys.path.append(str(_ROOT))

from app_launcher import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main())
