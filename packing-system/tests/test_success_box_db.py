"""Unit tests for wcs_success_box row building / WCS case assembly (no MySQL)."""

import json

from src.adapter.wcs_adapter import WcsPlanResult
from src.service.success_box_db import (
    build_success_box_rows,
    build_wcs_case_from_box_rows,
)


def test_build_success_box_rows_joins_stack_height_and_filters_failed():
    execution_report = {
        "pallets": [
            {
                "pallet_id": "P1",
                "mpm_status": "SUCCESS",
                "sales_order_no": "SO1",
                "pallet_type": "MH423C",
                "case_group": 0,
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
    plan_by_unique_id = {
        "uid_ok": {
            "pallet_id": "P1",
            "mpm_status": "SUCCESS",
            "sales_order_no": "SO1",
            "pallet_type": "MH423C",
            "case_group": 0,
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
    assert r1[8] == 12.5
    assert r1[9] is None
    assert r1[10:14] == ("P1", "SO1", "MH423C", "0")
    assert r1[14] == "9001"
    assert r2[1] == 2
    assert r2[8] == 40.0
    assert r2[14] == "9002"


def test_build_success_box_rows_treats_zero_product_code_as_null():
    execution_report = {
        "pallets": [
            {
                "mpm_status": "SUCCESS",
                "case_group": "3",
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
            "case_group": "3",
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
    assert rows[0][13] == "3"
    assert rows[0][14] is None


def test_build_wcs_case_from_box_rows_layers_and_height():
    rows = [
        {
            "seq": 1,
            "raw_length": 700,
            "raw_width": 530,
            "raw_height": 360,
            "pos_x": 0,
            "pos_y": 0,
            "pos_z": 0,
            "order_id": "SO1",
            "case_type": "MH423C",
            "case_group": "0",
            "product_code": "111",
        },
        {
            "seq": 2,
            "raw_length": 700,
            "raw_width": 530,
            "raw_height": 360,
            "pos_x": 0,
            "pos_y": 0,
            "pos_z": 360,
            "order_id": "SO1",
            "case_type": "MH423C",
            "case_group": "0",
            "product_code": "222",
        },
    ]
    case = build_wcs_case_from_box_rows("uid-a", rows, box_index=1)
    assert case["box_unique_id"] == "uid-a"
    assert case["box_index"] == 1
    assert case["total_height"] == 720.0
    assert case["case_group"] == "0"
    assert case["case_source"] == "DH"
    assert len(case["layers"]) == 2
    assert case["layers"][0]["cartons"][0]["seq"] == 1
    assert case["layers"][1]["cartons"][0]["layer_id"] == 2
    assert case["layers"][1]["cartons"][0]["product_code"] == 222


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
        _INTERNAL_PRODUCT_CODE_MIN <= int(c) <= _INTERNAL_PRODUCT_CODE_MAX
        for c in codes
    )


def test_persist_success_boxes_from_plan_file_uses_original_success_pallets(
    tmp_path, monkeypatch
):
    import src.service.success_box_db as mod

    plan = tmp_path / "ui_packing_plan.json"
    plan.write_text(
        json.dumps(
            {
                "pallets": [
                    {
                        "pallet_id": "P-OK",
                        "mpm_status": "SUCCESS",
                        "sales_order_no": "SO1",
                        "pallet_type": "MH423C",
                        "packed_items": [
                            {
                                "id": "b1",
                                "raw_length": 100,
                                "raw_width": 50,
                                "raw_height": 40,
                                "position": {"x": 0, "y": 0, "z": 0},
                                "product_code": 1001,
                                "seq": 1,
                            }
                        ],
                    },
                    {
                        "pallet_id": "P-FAIL",
                        "mpm_status": "FAILED",
                        "packed_items": [
                            {
                                "id": "b2",
                                "raw_length": 10,
                                "raw_width": 10,
                                "raw_height": 10,
                                "position": {"x": 0, "y": 0, "z": 0},
                                "product_code": 1002,
                                "seq": 1,
                            }
                        ],
                    },
                ]
            }
        ),
        encoding="utf-8",
    )

    captured = {}

    def fake_persist(report, wcs_result, *, config_path=None, db_config=None):
        captured["report"] = report
        captured["wcs"] = wcs_result
        return 7

    monkeypatch.setattr(mod, "persist_success_boxes", fake_persist)
    monkeypatch.setattr(
        mod,
        "persist_box_orientations",
        lambda *a, **k: 0,
        raising=False,
    )

    # box_orientation import path inside function
    import types
    import sys

    fake_orient = types.ModuleType("src.service.box_orientation_db")
    fake_orient.persist_box_orientations = lambda *a, **k: 0
    monkeypatch.setitem(sys.modules, "src.service.box_orientation_db", fake_orient)

    n = mod.persist_success_boxes_from_plan_file(plan)
    assert n == 7
    assert len(captured["wcs"].cases) == 1
    assert captured["wcs"].cases[0]["case_type"] == "MH423C"

