# -*- coding: utf-8 -*-
"""把 packing-system/src/service/success_box_db 挂到 packing 的 src.service 下。

UI / WCS 服务以 ``packing/`` 为 ``src`` 根；执行规划脚本以 ``packing-system/src`` 为根。
此处用文件加载避免两套 ``src.service`` 包互相抢占。
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_IMPL_PATH = (
    Path(__file__).resolve().parents[3] / "src" / "service" / "success_box_db.py"
)
_MOD_NAME = "_zhuang_success_box_db_impl"


def _load_impl():
    if _MOD_NAME in sys.modules:
        return sys.modules[_MOD_NAME]
    if not _IMPL_PATH.is_file():
        raise ImportError(f"找不到 success_box_db 实现：{_IMPL_PATH}")
    spec = importlib.util.spec_from_file_location(_MOD_NAME, _IMPL_PATH)
    if spec is None or spec.loader is None:
        raise ImportError(f"无法加载 success_box_db：{_IMPL_PATH}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[_MOD_NAME] = mod
    spec.loader.exec_module(mod)
    return mod


_impl = _load_impl()

IS_SEND_UNSENT = _impl.IS_SEND_UNSENT
IS_SEND_SENT = _impl.IS_SEND_SENT
DatabaseConfig = _impl.DatabaseConfig
WcsSuccessBoxRepository = _impl.WcsSuccessBoxRepository
build_success_box_rows = _impl.build_success_box_rows
build_wcs_case_from_box_rows = _impl.build_wcs_case_from_box_rows
get_success_box_repo = _impl.get_success_box_repo
load_database_config = _impl.load_database_config
load_database_config_from_yaml = _impl.load_database_config_from_yaml
persist_success_boxes = _impl.persist_success_boxes
persist_success_boxes_from_plan_file = _impl.persist_success_boxes_from_plan_file

__all__ = [
    "IS_SEND_UNSENT",
    "IS_SEND_SENT",
    "DatabaseConfig",
    "WcsSuccessBoxRepository",
    "build_success_box_rows",
    "build_wcs_case_from_box_rows",
    "get_success_box_repo",
    "load_database_config",
    "load_database_config_from_yaml",
    "persist_success_boxes",
    "persist_success_boxes_from_plan_file",
]
