"""Unit tests for wcs_success_box row building (no MySQL required)."""

from src.adapter.wcs_adapter import WcsPlanResult
from src.service.success_box_db import build_success_box_rows


def test_build_success_box_rows_joins_stack_height_and_filters_failed():
    execution_report = {
        "pallets": [
            {
                "pallet_id": "P1",
                "mpm_status": "SUCCESS",
                "sales_order_no": "SO1",
                "pallet_type": "MH423C",
                "packed_items": [
                    {
                        "id": "b1",
                        "raw_length": 100,
                        "raw_width": 50,
                        "raw_height": 40,
                        "position": {"x": 1, "y": 2, "z": 0},
                        "stack_height_before": 12.5,
                        "product_code": 9001,
                        "seq": 1,
                    },
                    {
                        "id": "b2",
                        "original_length": 110,
                        "original_width": 60,
                        "original_height": 45,
                        "position": {"x": 3, "y": 4, "z": 40},
                        "stack_height_before": 40.0,
                        "product_code": "PROD9002",
                        "seq": 2,
                    },
                ],
            },
            {
                "pallet_id": "P_FAIL",
                "mpm_status": "FAILED",
                "packed_items": [
                    {
                        "id": "bf",
                        "raw_length": 1,
                        "raw_width": 1,
                        "raw_height": 1,
                        "position": {"x": 0, "y": 0, "z": 0},
                        "stack_height_before": 99,
                        "product_code": 1,
                        "seq": 1,
                    }
                ],
            },
        ]
    }
    # map 侧通常已 pop stack_height_before；仍带 seq / product_code / position
    plan_by_unique_id = {
        "uid_ok": {
            "pallet_id": "P1",
            "mpm_status": "SUCCESS",
            "sales_order_no": "SO1",
            "pallet_type": "MH423C",
            "packed_items": [
                {
                    "id": "b1",
                    "raw_length": 100,
                    "raw_width": 50,
                    "raw_height": 40,
                    "position": {"x": 1, "y": 2, "z": 0},
                    "product_code": 9001,
                    "seq": 1,
                },
                {
                    "id": "b2",
                    "original_length": 110,
                    "original_width": 60,
                    "original_height": 45,
                    "position": {"x": 3, "y": 4, "z": 40},
                    "product_code": "PROD9002",
                    "seq": 2,
                },
            ],
        },
        "uid_fail": {
            "pallet_id": "P_FAIL",
            "mpm_status": "FAILED",
            "packed_items": [
                {
                    "id": "bf",
                    "seq": 1,
                    "product_code": 1,
                    "raw_length": 1,
                    "raw_width": 1,
                    "raw_height": 1,
                    "position": {"x": 0, "y": 0, "z": 0},
                }
            ],
        },
    }
    rows = build_success_box_rows(
        execution_report,
        WcsPlanResult(cases=[], plan_by_unique_id=plan_by_unique_id),
    )
    assert len(rows) == 2
    r1, r2 = rows
    assert r1[0] == "uid_ok"
    assert r1[1] == 1
    assert r1[2:5] == (100.0, 50.0, 40.0)
    assert r1[5:8] == (1.0, 2.0, 0.0)
    assert r1[8] == 12.5  # from execution_report
    assert r1[9] == 1  # state
    assert r1[10:13] == ("P1", "SO1", "MH423C")
    assert r1[13] == 9001
    assert r2[1] == 2
    assert r2[8] == 40.0
    assert r2[13] == 9002


def test_build_success_box_rows_treats_zero_product_code_as_null():
    execution_report = {
        "pallets": [
            {
                "mpm_status": "SUCCESS",
                "packed_items": [
                    {
                        "id": "a",
                        "raw_length": 1,
                        "raw_width": 1,
                        "raw_height": 1,
                        "position": {"x": 0, "y": 0, "z": 0},
                        "stack_height_before": 0,
                        "product_code": 0,
                        "seq": 1,
                    }
                ],
            }
        ]
    }
    plan = {
        "u1": {
            "mpm_status": "SUCCESS",
            "packed_items": [
                {
                    "id": "a",
                    "raw_length": 1,
                    "raw_width": 1,
                    "raw_height": 1,
                    "position": {"x": 0, "y": 0, "z": 0},
                    "product_code": 0,
                    "seq": 1,
                }
            ],
        }
    }
    rows = build_success_box_rows(
        execution_report, WcsPlanResult(plan_by_unique_id=plan)
    )
    assert len(rows) == 1
    assert rows[0][13] is None  # 入库时再补随机内部码


def test_new_internal_product_code_unique_in_batch():
    from src.service.success_box_db import (
        _INTERNAL_PRODUCT_CODE_MAX,
        _INTERNAL_PRODUCT_CODE_MIN,
        _new_internal_product_code,
    )

    reserved = set()
    codes = [_new_internal_product_code(reserved) for _ in range(200)]
    assert len(codes) == len(set(codes))
    assert all(
        _INTERNAL_PRODUCT_CODE_MIN <= c <= _INTERNAL_PRODUCT_CODE_MAX for c in codes
    )
