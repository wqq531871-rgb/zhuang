from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_interface_maintenance_keeps_packing_src_for_wcs_import():
    """接口维护不能把 UI 的规范 src 从 packing/src 切到顶层 src。"""
    script = f"""
import sys
from pathlib import Path
from types import SimpleNamespace

root = Path({str(ROOT)!r})
packing = root / "packing"
ui = root / "ui"
sys.path[:0] = [str(ui), str(root), str(packing)]

from realtime_dashboard_v3_clean import IndustrialPackingWorkbenchClean

dummy = SimpleNamespace(project_dir=root)
resolved = IndustrialPackingWorkbenchClean._ensure_packing_import_path(dummy)
assert resolved == packing.resolve()
assert Path(sys.path[0]).resolve() == packing.resolve()

from wcs_api_maintain_dialog import _ensure_device_status_import

store = _ensure_device_status_import(root)
assert store.STATUS_READY == 0

import src.service

service_dir = Path(src.service.__file__).resolve().parent
assert service_dir == (packing / "src" / "service").resolve()

import src.service.wcs_service

print(src.service.wcs_service.__file__)
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
