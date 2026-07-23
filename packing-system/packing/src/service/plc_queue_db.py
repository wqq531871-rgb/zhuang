# -*- coding: utf-8 -*-
"""把 packing-system/src/service/plc_queue_db 挂到 packing 的 src.service 下。"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_IMPL_PATH = (
    Path(__file__).resolve().parents[3] / "src" / "service" / "plc_queue_db.py"
)
_MOD_NAME = "_zhuang_plc_queue_db_impl"


def _load_impl():
    if _MOD_NAME in sys.modules:
        return sys.modules[_MOD_NAME]
    if not _IMPL_PATH.is_file():
        raise ImportError(f"找不到 plc_queue_db 实现：{_IMPL_PATH}")
    spec = importlib.util.spec_from_file_location(_MOD_NAME, _IMPL_PATH)
    if spec is None or spec.loader is None:
        raise ImportError(f"无法加载 plc_queue_db：{_IMPL_PATH}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[_MOD_NAME] = mod
    spec.loader.exec_module(mod)
    return mod


_impl = _load_impl()

STATUS_PENDING = _impl.STATUS_PENDING
STATUS_SENT = _impl.STATUS_SENT
STATUS_FAILED = _impl.STATUS_FAILED
WcsPlcQueueRepository = _impl.WcsPlcQueueRepository
build_plc_command_from_box_row = _impl.build_plc_command_from_box_row
enqueue_plc_after_rotation = _impl.enqueue_plc_after_rotation
get_plc_queue_repo = _impl.get_plc_queue_repo
stub_send_plc_command = _impl.stub_send_plc_command

__all__ = [
    "STATUS_PENDING",
    "STATUS_SENT",
    "STATUS_FAILED",
    "WcsPlcQueueRepository",
    "build_plc_command_from_box_row",
    "enqueue_plc_after_rotation",
    "get_plc_queue_repo",
    "stub_send_plc_command",
]
