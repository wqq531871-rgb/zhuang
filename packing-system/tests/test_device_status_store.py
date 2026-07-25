# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path

from src.service.device_status_store import (
    STATUS_BUSY,
    STATUS_READY,
    mark_busy_on_palletarrive,
    mark_ready_on_kongxian_idle,
    read_device_status,
    write_device_status,
)


def test_palletarrive_sets_busy_then_kongxian_sets_ready(tmp_path: Path):
    write_device_status(STATUS_READY, source="init", workspace=tmp_path)
    assert read_device_status(workspace=tmp_path) == STATUS_READY

    mark_busy_on_palletarrive(workspace=tmp_path)
    assert read_device_status(workspace=tmp_path) == STATUS_BUSY

    # 非 0 不改
    assert mark_ready_on_kongxian_idle(1, workspace=tmp_path) is None
    assert read_device_status(workspace=tmp_path) == STATUS_BUSY

    mark_ready_on_kongxian_idle(0, workspace=tmp_path)
    assert read_device_status(workspace=tmp_path) == STATUS_READY

    # 已是 0 不重复写
    assert mark_ready_on_kongxian_idle(0, workspace=tmp_path) is None


def test_missing_file_uses_default(tmp_path: Path):
    assert read_device_status(default=STATUS_BUSY, workspace=tmp_path) == STATUS_BUSY
