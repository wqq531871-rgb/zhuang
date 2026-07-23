# -*- coding: utf-8 -*-
"""把 packing-system/src/service/live_stack_bridge 挂到 packing 的 src.service 下。"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_IMPL_PATH = (
    Path(__file__).resolve().parents[3] / "src" / "service" / "live_stack_bridge.py"
)
_MOD_NAME = "_zhuang_live_stack_bridge_impl"


def _load_impl():
    if _MOD_NAME in sys.modules:
        return sys.modules[_MOD_NAME]
    if not _IMPL_PATH.is_file():
        raise ImportError(f"找不到 live_stack_bridge 实现：{_IMPL_PATH}")
    spec = importlib.util.spec_from_file_location(_MOD_NAME, _IMPL_PATH)
    if spec is None or spec.loader is None:
        raise ImportError(f"无法加载 live_stack_bridge：{_IMPL_PATH}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[_MOD_NAME] = mod
    spec.loader.exec_module(mod)
    return mod


_impl = _load_impl()

command_path = _impl.command_path
find_plan_map_for_uid = _impl.find_plan_map_for_uid
read_json = _impl.read_json
runtime_dir = _impl.runtime_dir
session_path = _impl.session_path
write_selected_pallet_session = _impl.write_selected_pallet_session

__all__ = [
    "command_path",
    "find_plan_map_for_uid",
    "read_json",
    "runtime_dir",
    "session_path",
    "write_selected_pallet_session",
]
