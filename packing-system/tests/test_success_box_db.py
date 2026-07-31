"""Unit tests for wcs_success_box row building / WCS case assembly (no MySQL)."""

import json
from contextlib import contextmanager

import pytest

from src.adapter.wcs_adapter import WcsPlanResult
from src.service.success_box_db import (
    DatabaseConfig,
    WcsSuccessBoxRepository,
    build_success_box_rows,
    build_wcs_case_from_box_rows,
    layout_state_from_raw_dims,
)


_SUCCESS_BOX_COLUMNS = (
    "box_unique_id",
    "seq",
    "raw_length",
    "raw_width",
    "raw_height",
    "pos_x",
    "pos_y",
    "pos_z",
    "stack_height_before",
    "state",
    "pallet_id",
    "order_id",
    "case_type",
    "case_group",
    "product_code",
    "box_num",
    "is_send",
)


class _StatefulSuccessBoxCursor:
    """Small in-memory substitute for the MySQL operations used by insert_rows."""

    def __init__(self, rows):
        self.rows = [dict(row) for row in rows]
        self.rowcount = 0
        self._fetched = []

    def execute(self, sql, params=None):
        normalized = " ".join(sql.split()).upper()
        values = [str(value) for value in (params or [])]
        if normalized.startswith("UPDATE WCS_SUCCESS_BOX SET IS_SEND"):
            assert "WHERE IS_SEND = %S OR IS_SEND IS NULL" in normalized
            assert "TRIM(IFNULL(IS_SEND,'')) = ''" in normalized
            sent_value, unsent_value = values
            updated = 0
            for row in self.rows:
                current = str(row.get("is_send") or "").strip()
                if current in (unsent_value, ""):
                    row["is_send"] = sent_value
                    updated += 1
            self.rowcount = updated
            self._fetched = []
            return

        if normalized.startswith("SELECT") and "WHERE PRODUCT_CODE IN" in normalized:
            matches = [
                row
                for row in self.rows
                if str(row.get("product_code")) in set(values)
            ]
            if "BOX_UNIQUE_ID" in normalized:
                self._fetched = [
                    {"box_unique_id": row["box_unique_id"]} for row in matches
                ]
            else:
                self._fetched = [
                    {"product_code": row["product_code"]} for row in matches
                ]
            self.rowcount = len(self._fetched)
            return

        if normalized.startswith("DELETE FROM WCS_SUCCESS_BOX"):
            old_uids = set(values)
            before = len(self.rows)
            self.rows[:] = [
                row
                for row in self.rows
                if str(row.get("box_unique_id")) not in old_uids
            ]
            self.rowcount = before - len(self.rows)
            self._fetched = []
            return

        raise AssertionError(f"unexpected SQL: {sql}")

    def executemany(self, sql, rows):
        normalized = " ".join(sql.split()).upper()
        if not normalized.startswith("INSERT INTO WCS_SUCCESS_BOX"):
            raise AssertionError(f"unexpected SQL: {sql}")
        prepared = list(rows)
        self.rows.extend(
            dict(zip(_SUCCESS_BOX_COLUMNS, row)) for row in prepared
        )
        self.rowcount = len(prepared)
        self._fetched = []

    def fetchall(self):
        return list(self._fetched)


def _success_box_row(
    box_unique_id,
    seq,
    product_code,
    *,
    pallet_id,
    pos_x,
    box_num=2,
):
    return (
        box_unique_id,
        seq,
        100.0,
        50.0,
        40.0,
        pos_x,
        2.0,
        3.0,
        4.0,
        2,
        pallet_id,
        "SO1",
        "MH423C",
        "0",
        product_code,
        box_num,
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
    # raw 100x50 → width < length → state=2；110x60 同理
    assert r1[9] == 2
    assert r1[10:14] == ("P1", "SO1", "MH423C", "0")
    assert r1[14] == "9001"
    assert r1[15] == 2
    assert r2[1] == 2
    assert r2[8] == 40.0
    assert r2[9] == 2
    assert r2[14] == "9002"
    assert r2[15] == 2


def test_insert_rows_replaces_entire_old_pallet_when_product_code_moves(
    monkeypatch,
):
    cursor = _StatefulSuccessBoxCursor(
        [
            {
                "box_unique_id": "old-uid",
                "seq": 1,
                "product_code": "A",
                "pallet_id": "OLD-PALLET",
                "is_send": "1",
            },
            {
                "box_unique_id": "old-uid",
                "seq": 2,
                "product_code": "B",
                "pallet_id": "OLD-PALLET",
                "is_send": "1",
            },
            {
                "box_unique_id": "unrelated-uid",
                "seq": 1,
                "product_code": "D",
                "pallet_id": "UNCHANGED-PALLET",
                "is_send": "2",
            },
        ]
    )
    repo = WcsSuccessBoxRepository(DatabaseConfig())

    @contextmanager
    def fake_cursor():
        yield None, cursor

    monkeypatch.setattr(repo, "_cursor", fake_cursor)

    inserted = repo.insert_rows(
        [
            _success_box_row(
                "new-uid",
                1,
                "A",
                pallet_id="NEW-PALLET",
                pos_x=101.0,
            ),
            _success_box_row(
                "new-uid",
                2,
                "C",
                pallet_id="NEW-PALLET",
                pos_x=202.0,
            ),
        ]
    )

    by_code = {str(row["product_code"]): row for row in cursor.rows}
    assert inserted == 2
    assert set(by_code) == {"A", "C", "D"}
    assert by_code["A"]["box_unique_id"] == "new-uid"
    assert by_code["A"]["pallet_id"] == "NEW-PALLET"
    assert by_code["A"]["pos_x"] == 101.0
    assert by_code["A"]["is_send"] == "2"
    assert by_code["C"]["box_unique_id"] == "new-uid"
    assert by_code["D"]["box_unique_id"] == "unrelated-uid"
    assert by_code["D"]["is_send"] == "1"


def test_insert_rows_archives_only_old_unsent_or_blank_rows(monkeypatch):
    cursor = _StatefulSuccessBoxCursor(
        [
            {"box_unique_id": "u-2", "product_code": "B", "is_send": "2"},
            {"box_unique_id": "u-null", "product_code": "C", "is_send": None},
            {"box_unique_id": "u-empty", "product_code": "D", "is_send": ""},
            {"box_unique_id": "u-blank", "product_code": "E", "is_send": "  "},
            {"box_unique_id": "u-1", "product_code": "F", "is_send": "1"},
        ]
    )
    repo = WcsSuccessBoxRepository(DatabaseConfig())

    @contextmanager
    def fake_cursor():
        yield None, cursor

    monkeypatch.setattr(repo, "_cursor", fake_cursor)

    repo.insert_rows(
        [_success_box_row("new-uid", 1, "A", pallet_id="NEW", pos_x=1.0)]
    )

    by_code = {str(row["product_code"]): row for row in cursor.rows}
    assert {by_code[code]["is_send"] for code in ("B", "C", "D", "E", "F")} == {"1"}
    assert by_code["A"]["is_send"] == "2"


def test_insert_rows_rejects_duplicate_product_codes_in_current_batch(
    monkeypatch,
):
    cursor = _StatefulSuccessBoxCursor([])
    repo = WcsSuccessBoxRepository(DatabaseConfig())

    @contextmanager
    def fake_cursor():
        yield None, cursor

    monkeypatch.setattr(repo, "_cursor", fake_cursor)

    with pytest.raises(ValueError, match="本批 product_code 重复.*A"):
        repo.insert_rows(
            [
                _success_box_row(
                    "new-uid-1",
                    1,
                    "A",
                    pallet_id="NEW-PALLET-1",
                    pos_x=101.0,
                ),
                _success_box_row(
                    "new-uid-2",
                    1,
                    "A",
                    pallet_id="NEW-PALLET-2",
                    pos_x=202.0,
                ),
            ]
        )

    assert cursor.rows == []


def test_layout_state_from_raw_dims_matches_robot_rule():
    assert layout_state_from_raw_dims(100, 50) == 2
    assert layout_state_from_raw_dims(50, 100) == 1
    assert layout_state_from_raw_dims(80, 80) == 1
    assert layout_state_from_raw_dims(0, 10) == 1


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
    assert rows[0][15] == 1


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
    assert [
        carton["layer_id"]
        for layer in case["layers"]
        for carton in layer["cartons"]
    ] == [1, 1]
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
