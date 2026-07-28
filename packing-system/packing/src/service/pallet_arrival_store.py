# -*- coding: utf-8 -*-
"""Bridge the shared 4.6 pallet-arrival store into packing/src."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_IMPL_PATH = (
    Path(__file__).resolve().parents[3] / "src" / "service" / "pallet_arrival_store.py"
)
_MOD_NAME = "_zhuang_pallet_arrival_store_impl"


def _load_impl():
    if _MOD_NAME in sys.modules:
        return sys.modules[_MOD_NAME]
    spec = importlib.util.spec_from_file_location(_MOD_NAME, _IMPL_PATH)
    if spec is None or spec.loader is None:
        raise ImportError(f"无法加载 pallet_arrival_store：{_IMPL_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[_MOD_NAME] = module
    spec.loader.exec_module(module)
    return module


_impl = _load_impl()

workspace_root = _impl.workspace_root
runtime_dir = _impl.runtime_dir
latest_pallet_arrival_path = _impl.latest_pallet_arrival_path
write_latest_pallet_arrival = _impl.write_latest_pallet_arrival
read_latest_pallet_arrival = _impl.read_latest_pallet_arrival
list_recent_pallet_arrivals = _impl.list_recent_pallet_arrivals

__all__ = [
    "workspace_root",
    "runtime_dir",
    "latest_pallet_arrival_path",
    "write_latest_pallet_arrival",
    "read_latest_pallet_arrival",
    "list_recent_pallet_arrivals",
]
