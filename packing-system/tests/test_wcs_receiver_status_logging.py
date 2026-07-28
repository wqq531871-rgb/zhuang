from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace


RECEIVER_ROOT = Path(__file__).resolve().parents[1] / "local_wcs_receiver"
if str(RECEIVER_ROOT) not in sys.path:
    sys.path.insert(0, str(RECEIVER_ROOT))

from app.handlers import handle_boxarrive, handle_palletarrive, handle_status


def _settings(tmp_path: Path) -> SimpleNamespace:
    return SimpleNamespace(
        log_dir=tmp_path / "logs",
        save_requests=True,
        device_status=0,
        status_path="/api/status",
        boxarrive_path="/adaptor/api/wcs/boxarrive",
        palletarrive_path="/adaptor/api/wcs/palletarrive",
    )


def test_status_poll_does_not_write_request_file(tmp_path, monkeypatch):
    monkeypatch.setenv("PACKING_WORKSPACE", str(tmp_path / "workspace"))
    settings = _settings(tmp_path)

    response = handle_status(settings)

    assert response == {
        "code": 0,
        "msg": "success",
        "data": {"status": 0},
    }
    assert not list(settings.log_dir.glob("*.json"))


def test_non_status_request_still_writes_request_file(tmp_path):
    settings = _settings(tmp_path)

    handle_boxarrive(settings, {})

    files = list(settings.log_dir.glob("*_adaptor_api_wcs_boxarrive.json"))
    assert len(files) == 1


def test_palletarrive_persists_latest_physical_pallet(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    monkeypatch.setenv("PACKING_WORKSPACE", str(workspace))
    body = {
        "robot_id": "5",
        "station_id": "N12X010",
        "pallet_code": "KDDM24170157",
        "case_type": "",
    }

    response = handle_palletarrive(_settings(tmp_path), body)

    saved = (
        workspace / "runtime" / "wcs_latest_pallet_arrival.json"
    ).read_text(encoding="utf-8")
    assert '"pallet_code": "KDDM24170157"' in saved
    assert response["code"] == 0
    assert response["data"]["pallet_arrival"]["ok"] is True
