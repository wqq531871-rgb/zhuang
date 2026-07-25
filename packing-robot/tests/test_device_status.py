from __future__ import annotations

from types import SimpleNamespace

from packing_ui.device_status import (
    STATUS_BUSY,
    STATUS_READY,
    device_status_path,
    mark_ready_on_kongxian_idle,
    read_device_status,
    write_device_status,
)
from packing_ui.plc_controller import PlcController


def test_device_status_kongxian_ready(tmp_path, monkeypatch):
    monkeypatch.setenv("PACKING_WORKSPACE", str(tmp_path))
    write_device_status(STATUS_BUSY, source="test")
    assert read_device_status() == STATUS_BUSY
    assert mark_ready_on_kongxian_idle(0) is not None
    assert read_device_status() == STATUS_READY
    assert device_status_path().is_file()


def test_plc_controller_status_writes_ready_on_idle(tmp_path, monkeypatch):
    monkeypatch.setenv("PACKING_WORKSPACE", str(tmp_path))
    write_device_status(STATUS_BUSY, source="test")
    ctrl = PlcController(lock_path=tmp_path / "plc.lock")
    ctrl._on_plc_status(
        SimpleNamespace(fp=0, fp_over=0, idle=0, dh_over=0, request_seq=1)
    )
    assert read_device_status() == STATUS_READY
