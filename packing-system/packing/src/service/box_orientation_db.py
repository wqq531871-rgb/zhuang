# -*- coding: utf-8 -*-
"""把 packing-system/src/service/box_orientation_db 挂到 packing 的 src.service 下。"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_IMPL_PATH = (
    Path(__file__).resolve().parents[3] / "src" / "service" / "box_orientation_db.py"
)
_MOD_NAME = "_zhuang_box_orientation_db_impl"


def _load_impl():
    if _MOD_NAME in sys.modules:
        return sys.modules[_MOD_NAME]
    if not _IMPL_PATH.is_file():
        raise ImportError(f"找不到 box_orientation_db 实现：{_IMPL_PATH}")
    spec = importlib.util.spec_from_file_location(_MOD_NAME, _IMPL_PATH)
    if spec is None or spec.loader is None:
        raise ImportError(f"无法加载 box_orientation_db：{_IMPL_PATH}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[_MOD_NAME] = mod
    spec.loader.exec_module(mod)
    return mod


_impl = _load_impl()

STATE_NO_ROTATE = _impl.STATE_NO_ROTATE
STATE_ROTATE_90 = _impl.STATE_ROTATE_90
WcsBoxOrientationRepository = _impl.WcsBoxOrientationRepository
build_orientation_rows = _impl.build_orientation_rows
compute_target_orientation_deg = _impl.compute_target_orientation_deg
get_orientation_repo = _impl.get_orientation_repo
judge_rotation_state = _impl.judge_rotation_state
persist_box_orientations = _impl.persist_box_orientations
process_box_arrive_rotation = _impl.process_box_arrive_rotation
load_pallet_demo_rows = _impl.load_pallet_demo_rows

__all__ = [
    "STATE_NO_ROTATE",
    "STATE_ROTATE_90",
    "WcsBoxOrientationRepository",
    "build_orientation_rows",
    "compute_target_orientation_deg",
    "get_orientation_repo",
    "judge_rotation_state",
    "persist_box_orientations",
    "process_box_arrive_rotation",
    "load_pallet_demo_rows",
]
