# -*- coding: utf-8 -*-
"""把顶层 device_status_store 挂到 packing 的 src.service 下。

UI 和 WCS 服务统一使用 packing/src 作为 ``src`` 根；实际设备状态实现仍
保留在 packing-system/src/service 中。使用唯一模块名加载可避免两套
``src.service`` 在运行期间互相替换。
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_IMPL_PATH = (
    Path(__file__).resolve().parents[3] / "src" / "service" / "device_status_store.py"
)
_MOD_NAME = "_zhuang_device_status_store_impl"


def _load_impl():
    if _MOD_NAME in sys.modules:
        return sys.modules[_MOD_NAME]
    if not _IMPL_PATH.is_file():
        raise ImportError(f"找不到 device_status_store 实现：{_IMPL_PATH}")
    spec = importlib.util.spec_from_file_location(_MOD_NAME, _IMPL_PATH)
    if spec is None or spec.loader is None:
        raise ImportError(f"无法加载 device_status_store：{_IMPL_PATH}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[_MOD_NAME] = mod
    spec.loader.exec_module(mod)
    return mod


_impl = _load_impl()

STATUS_READY = _impl.STATUS_READY
STATUS_BUSY = _impl.STATUS_BUSY
STATUS_ERROR = _impl.STATUS_ERROR
workspace_root = _impl.workspace_root
runtime_dir = _impl.runtime_dir
device_status_path = _impl.device_status_path
write_device_status = _impl.write_device_status
read_device_status = _impl.read_device_status
mark_busy_on_palletarrive = _impl.mark_busy_on_palletarrive
mark_ready_on_kongxian_idle = _impl.mark_ready_on_kongxian_idle

__all__ = [
    "STATUS_READY",
    "STATUS_BUSY",
    "STATUS_ERROR",
    "workspace_root",
    "runtime_dir",
    "device_status_path",
    "write_device_status",
    "read_device_status",
    "mark_busy_on_palletarrive",
    "mark_ready_on_kongxian_idle",
]
