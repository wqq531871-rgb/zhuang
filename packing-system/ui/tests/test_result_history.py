import json
import os
from pathlib import Path

from realtime_dashboard_v3_clean import list_result_json_files
from realtime_dashboard_v2 import find_latest_json


def _write_report(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"pallets": []}), encoding="utf-8")


def test_interface_history_prefers_execution_report_and_falls_back(tmp_path):
    project = tmp_path / "packing-system"
    project.mkdir()
    output = tmp_path / "packing-workspace" / "output"
    base_success = output / "success" / "packing_plan_20260721_100000.json"
    execution = output / "success" / "packing_plan_20260721_100000_execution.json"
    base_fallback = output / "fail" / "packing_plan_20260721_110000.json"
    _write_report(base_success)
    _write_report(execution)
    _write_report(base_fallback)

    entries = list_result_json_files(project, limit=10)
    names = [entry.path.name for entry in entries]

    assert execution.name in names
    assert base_success.name not in names
    assert base_fallback.name in names


def test_latest_result_ignores_newer_wcs_artifacts(tmp_path):
    project = tmp_path / "packing-system"
    project.mkdir()
    output = tmp_path / "packing-workspace" / "output"
    execution = output / "success" / "packing_plan_20260721_100000_execution.json"
    wcs_map = output / "success" / "packing_plan_20260721_100000_execution_wcs_map.json"
    _write_report(execution)
    wcs_map.parent.mkdir(parents=True, exist_ok=True)
    wcs_map.write_text(json.dumps({"id": {"packed_items": []}}), encoding="utf-8")
    os.utime(execution, (100, 100))
    os.utime(wcs_map, (200, 200))

    assert find_latest_json(project) == execution


def test_history_hides_exports_base_when_execution_in_success(tmp_path):
    project = tmp_path / "packing-system"
    project.mkdir()
    workspace = tmp_path / "packing-workspace"
    exports = workspace / "runtime" / "packing-realtime" / "exports"
    success = workspace / "output" / "success"
    base = exports / "ui_packing_plan_20260721_130000.json"
    execution = success / "ui_packing_plan_20260721_130000_execution.json"
    _write_report(base)
    _write_report(execution)

    entries = list_result_json_files(project, limit=10)
    names = [entry.path.name for entry in entries]
    assert execution.name in names
    assert base.name not in names

