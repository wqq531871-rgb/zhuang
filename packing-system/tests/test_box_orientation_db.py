"""Unit tests for wcs_box_orientation row building / rotation judge (no MySQL)."""

from src.adapter.wcs_adapter import WcsPlanResult
from src.service.box_orientation_db import (
    STATE_NO_ROTATE,
    STATE_ROTATE_90,
    build_orientation_rows,
    compute_target_orientation_deg,
    judge_rotation_state,
)


def test_compute_target_orientation_from_suction_string():
    assert compute_target_orientation_deg("cup_600x_800y") == 0
    assert compute_target_orientation_deg("cup_800x_600y") == 90


def test_compute_target_orientation_from_cup_sizes():
    assert compute_target_orientation_deg(None, 600, 800) == 0
    assert compute_target_orientation_deg(None, 800, 600) == 90


def test_judge_rotation_state():
    assert judge_rotation_state(0, 0) == STATE_NO_ROTATE
    assert judge_rotation_state(90, 90) == STATE_NO_ROTATE
    assert judge_rotation_state(0, 90) == STATE_ROTATE_90
    assert judge_rotation_state(90, 0) == STATE_ROTATE_90


def test_build_orientation_rows_success_only():
    plan = {
        "uid_ok": {
            "mpm_status": "SUCCESS",
            "packed_items": [
                {
                    "id": "WCS-b1",
                    "seq": 1,
                    "product_code": 5,
                    "suction_orientation": "cup_600x_800y",
                    "suction_cup_x_size": 600.0,
                    "suction_cup_y_size": 800.0,
                },
                {
                    "id": "WCS-b2",
                    "seq": 2,
                    "product_code": 6,
                    "suction_orientation": "cup_800x_600y",
                    "suction_cup_x_size": 800.0,
                    "suction_cup_y_size": 600.0,
                },
            ],
        },
        "uid_fail": {
            "mpm_status": "FAILED",
            "packed_items": [
                {
                    "id": "bf",
                    "seq": 1,
                    "suction_orientation": "cup_600x_800y",
                }
            ],
        },
    }
    rows = build_orientation_rows(
        WcsPlanResult(cases=[], plan_by_unique_id=plan)
    )
    assert len(rows) == 2
    assert rows[0][0] == "uid_ok"
    assert rows[0][1] == 1
    assert rows[0][2] == "WCS-b1"
    assert rows[0][3] == "5"
    assert rows[0][4] == "cup_600x_800y"
    assert rows[0][7] == 0
    assert rows[1][1] == 2
    assert rows[1][7] == 90
