from src.main.output_split import (
    FAIL_DIR_NAME,
    SUCCESS_DIR_NAME,
    ensure_success_fail_dirs,
    split_report_by_status,
)


def test_split_report_by_status_separates_pallets_and_summary():
    report = {
        "packing_plan_id": "x",
        "summary": {"overall": {"total_pallets": 3}},
        "pallets": [
            {"pallet_id": "S1", "mpm_status": "SUCCESS", "mpm_gap": 0},
            {"pallet_id": "F1", "mpm_status": "FAILED", "mpm_gap": 8},
            {"pallet_id": "U1", "mpm_status": "UNKNOWN", "mpm_gap": 1},
        ],
    }
    success, fail = split_report_by_status(report)
    assert [p["pallet_id"] for p in success["pallets"]] == ["S1"]
    assert [p["pallet_id"] for p in fail["pallets"]] == ["F1", "U1"]
    assert success["summary"]["overall"]["success_pallets"] == 1
    assert success["summary"]["overall"]["failed_pallets"] == 0
    assert fail["summary"]["overall"]["success_pallets"] == 0
    assert fail["summary"]["overall"]["failed_pallets"] == 2


def test_ensure_success_fail_dirs(tmp_path):
    success_dir, fail_dir = ensure_success_fail_dirs(tmp_path / "output")
    assert success_dir.name == SUCCESS_DIR_NAME
    assert fail_dir.name == FAIL_DIR_NAME
    assert success_dir.is_dir()
    assert fail_dir.is_dir()
