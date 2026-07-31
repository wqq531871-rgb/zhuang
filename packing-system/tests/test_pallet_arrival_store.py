from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def test_latest_pallet_arrival_round_trips_documented_fields(tmp_path):
    from src.service.pallet_arrival_store import (
        latest_pallet_arrival_path,
        read_latest_pallet_arrival,
        write_latest_pallet_arrival,
    )

    saved = write_latest_pallet_arrival(
        {
            "robot_id": "5",
            "station_id": "N12X010",
            "pallet_code": "KDDM24170157",
            "case_type": "",
            "ignored": "not persisted",
        },
        workspace=tmp_path,
    )

    assert saved["robot_id"] == "5"
    assert saved["station_id"] == "N12X010"
    assert saved["pallet_code"] == "KDDM24170157"
    assert saved["case_type"] == ""
    assert saved["source"] == "palletarrive"
    assert saved["received_at"]
    assert "ignored" not in saved
    assert read_latest_pallet_arrival(workspace=tmp_path) == saved

    disk = json.loads(
        latest_pallet_arrival_path(tmp_path).read_text(encoding="utf-8")
    )
    assert disk == saved
    assert not latest_pallet_arrival_path(tmp_path).with_suffix(".json.tmp").exists()


def test_latest_pallet_arrival_returns_empty_for_missing_or_invalid_file(tmp_path):
    from src.service.pallet_arrival_store import (
        latest_pallet_arrival_path,
        read_latest_pallet_arrival,
    )

    assert read_latest_pallet_arrival(workspace=tmp_path) == {}
    path = latest_pallet_arrival_path(tmp_path)
    path.write_text("{broken", encoding="utf-8")
    assert read_latest_pallet_arrival(workspace=tmp_path) == {}


def test_latest_pallet_arrival_falls_back_to_newest_legacy_46_log(tmp_path):
    from src.service.pallet_arrival_store import read_latest_pallet_arrival

    log_dir = tmp_path / "receiver-logs"
    log_dir.mkdir()
    older = {
        "time": "20260725_101921_198667",
        "body": {
            "robot_id": "5",
            "station_id": "N12X010",
            "pallet_code": "KDDM24170076",
            "case_type": "MH423C",
        },
    }
    newest = {
        "time": "20260726_150014_911272",
        "body": {
            "robot_id": "5",
            "station_id": "N12X010",
            "pallet_code": "KDDM24170157",
            "case_type": "",
        },
    }
    (log_dir / "20260725_101921_198667_adaptor_api_wcs_palletarrive.json").write_text(
        json.dumps(older), encoding="utf-8"
    )
    (log_dir / "20260726_150014_911272_adaptor_api_wcs_palletarrive.json").write_text(
        json.dumps(newest), encoding="utf-8"
    )

    loaded = read_latest_pallet_arrival(
        workspace=tmp_path / "empty-workspace",
        legacy_log_dir=log_dir,
    )

    assert loaded["pallet_code"] == "KDDM24170157"
    assert loaded["robot_id"] == "5"
    assert loaded["station_id"] == "N12X010"
    assert loaded["source"] == "palletarrive_log"
    assert loaded["received_at"] == "2026-07-26 15:00:14"


def test_list_recent_pallet_arrivals_returns_distinct_editable_choices(tmp_path):
    from src.service.pallet_arrival_store import list_recent_pallet_arrivals

    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    records = [
        (
            "20260725_101921_198667",
            "KDDM24170076",
            "N12X009",
        ),
        (
            "20260726_150014_911272",
            "KDDM24170157",
            "N12X010",
        ),
        (
            "20260726_160014_911272",
            "KDDM24170157",
            "N12X011",
        ),
    ]
    for stamp, pallet_code, station_id in records:
        payload = {
            "time": stamp,
            "body": {
                "robot_id": "5",
                "station_id": station_id,
                "pallet_code": pallet_code,
                "case_type": "",
            },
        }
        (log_dir / f"{stamp}_adaptor_api_wcs_palletarrive.json").write_text(
            json.dumps(payload), encoding="utf-8"
        )

    arrivals = list_recent_pallet_arrivals(
        workspace=tmp_path / "empty-workspace",
        legacy_log_dir=log_dir,
    )

    assert [item["pallet_code"] for item in arrivals] == [
        "KDDM24170157",
        "KDDM24170076",
    ]
    assert arrivals[0]["station_id"] == "N12X011"
