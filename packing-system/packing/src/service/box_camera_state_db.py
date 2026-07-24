# -*- coding: utf-8 -*-
"""把 packing-system/src/service/box_camera_state_db 挂到 packing 的 src.service 下。"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_IMPL_PATH = (
    Path(__file__).resolve().parents[3] / "src" / "service" / "box_camera_state_db.py"
)
_MOD_NAME = "_zhuang_box_camera_state_db_impl"


def _load_impl():
    if _MOD_NAME in sys.modules:
        return sys.modules[_MOD_NAME]
    if not _IMPL_PATH.is_file():
        raise ImportError(f"找不到 box_camera_state_db 实现：{_IMPL_PATH}")
    spec = importlib.util.spec_from_file_location(_MOD_NAME, _IMPL_PATH)
    if spec is None or spec.loader is None:
        raise ImportError(f"无法加载 box_camera_state_db：{_IMPL_PATH}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[_MOD_NAME] = mod
    spec.loader.exec_module(mod)
    return mod


_impl = _load_impl()

STATE_MISMATCH = _impl.STATE_MISMATCH
STATE_NO_ROTATE = _impl.STATE_NO_ROTATE
STATE_ROTATE_90 = _impl.STATE_ROTATE_90
DEFAULT_DIM_TOLERANCE_MM = _impl.DEFAULT_DIM_TOLERANCE_MM
WcsCameraStateRepository = _impl.WcsCameraStateRepository
judge_state_from_dims = _impl.judge_state_from_dims
camera_dims_complete = _impl.camera_dims_complete
apply_camera_dims_and_judge = _impl.apply_camera_dims_and_judge
write_camera_dims_only = _impl.write_camera_dims_only
auto_judge_pending_camera_rows = _impl.auto_judge_pending_camera_rows

__all__ = [
    "STATE_MISMATCH",
    "STATE_NO_ROTATE",
    "STATE_ROTATE_90",
    "DEFAULT_DIM_TOLERANCE_MM",
    "WcsCameraStateRepository",
    "judge_state_from_dims",
    "camera_dims_complete",
    "apply_camera_dims_and_judge",
    "write_camera_dims_only",
    "auto_judge_pending_camera_rows",
]
