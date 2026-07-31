from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_manual_45_prefills_46_pallet_and_sends_current_box(tmp_path):
    workspace = tmp_path / "packing-workspace"
    runtime = workspace / "runtime"
    runtime.mkdir(parents=True)
    script = f"""
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["PACKING_WORKSPACE"] = {str(workspace)!r}
root = Path({str(ROOT)!r})
sys.path[:0] = [str(root / "packing"), str(root / "ui")]

from src.service.pallet_arrival_store import write_latest_pallet_arrival
write_latest_pallet_arrival({{
    "robot_id": "5",
    "station_id": "N12X010",
    "pallet_code": "KDDM24170157",
    "case_type": "",
}})
(Path(os.environ["PACKING_WORKSPACE"]) / "runtime" / "live_stack_command.json").write_text(
    json.dumps({{
        "action": "play_box",
        "box_unique_id": "d33ba85e0c414af19ba853da1d995779",
        "seq": 40,
    }}),
    encoding="utf-8",
)

from PyQt5 import QtWidgets
from wcs_api_maintain_dialog import WcsApiMaintainDialog

app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
dialog = WcsApiMaintainDialog(project_dir=root)
dialog.show()
assert dialog.cmb_45_pallet_code.currentText() == "KDDM24170157"
assert dialog.cmb_45_pallet_code.isEditable()
assert dialog.txt_45_robot_id.text() == "5"
assert dialog.txt_45_station_id.text() == "N12X010"
assert dialog.txt_45_box_unique_id.text() == "d33ba85e0c414af19ba853da1d995779"

wcs_case = {{
    "box_index": 1,
    "box_unique_id": "d33ba85e0c414af19ba853da1d995779",
    "case_group": "0",
    "case_type": "MH423C",
    "layers": [
        {{"cartons": [{{
            "length": 420.0,
            "width": 310.0,
            "height": 280.0,
            "product_code": "30081842",
            "layer_id": 1,
            "seq": 1,
        }}]}}
    ],
}}
sent = []
dialog._load_wcs_case = lambda uid: wcs_case
dialog._load_data_source = lambda: SimpleNamespace(
    effective_api_base_url="http://example.test",
    reqpallet_path="/api/wcs/reqpallet",
    reqpallet_url=lambda: "http://example.test/api/wcs/reqpallet",
)
dialog._confirm_reqpallet = lambda **kwargs: True
dialog._save_reqpallet_snapshot = lambda payload, uid: Path("preview.json")
dialog._send_reqpallet = lambda ds, payload: sent.append(payload) or {{
    "code": 0, "msg": "ok", "data": {{}}
}}
QtWidgets.QMessageBox.information = lambda *args, **kwargs: QtWidgets.QMessageBox.Ok
QtWidgets.QMessageBox.critical = lambda *args, **kwargs: QtWidgets.QMessageBox.Ok

dialog.cmb_45_pallet_code.setEditText("MANUAL-PALLET-001")
dialog._on_send_reqpallet()

assert sent == [{{
    "robot_id": "5",
    "station_id": "N12X010",
    "pallet_code": "MANUAL-PALLET-001",
    "case_type": "MH423C",
    "empty_flag": False,
    "case_data": [{{
        "box_index": 1,
        "box_unique_id": "d33ba85e0c414af19ba853da1d995779",
        "case_group": "0",
        "height": 0,
        "layers": [{{
            "cartons": [{{
                "seq": 1,
                "length": 420.0,
                "width": 310.0,
                "height": 280.0,
                "product_code": "30081842",
            }}]
        }}],
    }}],
}}]
assert "1 层 / 1 箱" in dialog.lbl_45_summary.text()
assert dialog.isVisible()
print("manual-45-ui-ok")
"""
    env = dict(os.environ)
    env["QT_QPA_PLATFORM"] = "offscreen"
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "manual-45-ui-ok" in result.stdout
