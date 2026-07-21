"""Independent execution-order planning tests."""

import json
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

import pytest

from src.execution.sequence_planner import (
    ExecutionSequenceConfig,
    ExecutionSequenceError,
    plan_execution_report,
    sequence_pallet_items,
)
from src.execution.wcs_export import report_to_execution_plan_result
from run_execution_planning import _publish_json_files


PALLET_DIMS = {"length": 1000.0, "width": 1000.0, "height": 1000.0}


def _box(
    box_id,
    x,
    y,
    z,
    *,
    length=100.0,
    width=100.0,
    height=100.0,
    cup_rect=None,
):
    cup = cup_rect or {
        "x_min": x,
        "x_max": x + length,
        "y_min": y,
        "y_max": y + width,
    }
    return {
        "id": box_id,
        "type": "T",
        "length": float(length),
        "width": float(width),
        "height": float(height),
        "raw_length": float(length),
        "raw_width": float(width),
        "raw_height": float(height),
        "original_length": float(length),
        "original_width": float(width),
        "original_height": float(height),
        "weight": 1.0,
        "position": {"x": float(x), "y": float(y), "z": float(z)},
        "pallet_dims": deepcopy(PALLET_DIMS),
        "suction_box_corner": "x_min_y_min",
        "suction_cup_corner": "x_min_y_min",
        "suction_orientation": "cup_100x_100y",
        "suction_cup_x_size": cup["x_max"] - cup["x_min"],
        "suction_cup_y_size": cup["y_max"] - cup["y_min"],
        "suction_rect_x_min": float(cup["x_min"]),
        "suction_rect_x_max": float(cup["x_max"]),
        "suction_rect_y_min": float(cup["y_min"]),
        "suction_rect_y_max": float(cup["y_max"]),
    }


def _pallet(items):
    return {
        "pallet_id": "P-1",
        "pallet_type": "TEST",
        "sales_order_no": "O-1",
        "packed_items": items,
    }


def _ids(items):
    return [item["id"] for item in items]


def test_support_boxes_precede_the_box_they_support():
    base = _box("base", 0, 0, 0)
    top = _box("top", 0, 0, 100)

    ordered = sequence_pallet_items(_pallet([top, base]))

    assert _ids(ordered) == ["base", "top"]


def test_low_height_wavefront_prefers_shorter_resulting_top():
    tall_at_origin = _box("tall", 0, 0, 0, height=300)
    short_farther = _box("short", 200, 0, 0, height=100)

    ordered = sequence_pallet_items(
        _pallet([tall_at_origin, short_farther]),
        ExecutionSequenceConfig(origin="x_min_y_min"),
    )

    assert _ids(ordered) == ["short", "tall"]


@pytest.mark.parametrize(
    "origin, expected",
    [
        ("x_min_y_min", ["00", "10", "01", "11"]),
        ("x_max_y_max", ["11", "01", "10", "00"]),
    ],
)
def test_equal_height_boxes_expand_outward_from_configured_origin(origin, expected):
    boxes = [
        _box("11", 100, 100, 0),
        _box("01", 0, 100, 0),
        _box("10", 100, 0, 0),
        _box("00", 0, 0, 0),
    ]

    ordered = sequence_pallet_items(
        _pallet(boxes),
        ExecutionSequenceConfig(origin=origin),
    )

    assert _ids(ordered) == expected


def test_box_clearance_rejects_pair_with_no_safe_vertical_order():
    target = _box("target", 0, 0, 0, height=300)
    nearby_blocker = _box("blocker", 110, 0, 0, height=100)

    with pytest.raises(ExecutionSequenceError, match="cyclic"):
        sequence_pallet_items(
            _pallet([nearby_blocker, target]),
            ExecutionSequenceConfig(
                origin="x_min_y_min",
                box_xy_clearance_mm=20.0,
            ),
        )


def test_box_clearance_uses_physical_dims_not_padded_occupancy_dims():
    left = _box("left", 0, 0, 0)
    left["length"] = 102.0
    left["width"] = 102.0
    right = _box("right", 102, 0, 0)
    right["length"] = 102.0
    right["width"] = 102.0

    ordered = sequence_pallet_items(
        _pallet([right, left]),
        ExecutionSequenceConfig(box_xy_clearance_mm=1.0),
    )

    assert _ids(ordered) == ["left", "right"]


def test_suction_clearance_dependency_overrides_low_height_priority():
    target = _box(
        "target",
        0,
        0,
        0,
        height=300,
        cup_rect={"x_min": 0, "x_max": 220, "y_min": 0, "y_max": 100},
    )
    blocker = _box("blocker", 120, 0, 0, height=200)

    ordered = sequence_pallet_items(
        _pallet([blocker, target]),
        ExecutionSequenceConfig(suction_z_clearance_mm=150.0),
    )

    assert _ids(ordered) == ["target", "blocker"]


def test_mutual_suction_blocking_is_rejected_instead_of_falling_back():
    left = _box(
        "left",
        0,
        0,
        0,
        cup_rect={"x_min": 0, "x_max": 130, "y_min": 0, "y_max": 100},
    )
    right = _box(
        "right",
        110,
        0,
        0,
        cup_rect={"x_min": 80, "x_max": 210, "y_min": 0, "y_max": 100},
    )

    with pytest.raises(ExecutionSequenceError, match="cyclic") as exc_info:
        sequence_pallet_items(
            _pallet([left, right]),
            ExecutionSequenceConfig(suction_z_clearance_mm=1.0),
        )
    assert "left" in str(exc_info.value)
    assert "right" in str(exc_info.value)


def test_non_base_box_without_direct_support_is_rejected():
    floating = _box("floating", 0, 0, 100)

    with pytest.raises(ExecutionSequenceError, match="direct support"):
        sequence_pallet_items(_pallet([floating]))


def test_padded_overlap_does_not_count_as_physical_direct_support():
    lower = _box("lower", 0, 0, 0)
    lower["length"] = 102.0
    upper = _box("upper", 101, 0, 100)
    upper["length"] = 102.0

    with pytest.raises(ExecutionSequenceError, match="direct support"):
        sequence_pallet_items(_pallet([lower, upper]))


@pytest.mark.parametrize(
    "mutator, message",
    [
        (lambda item: item["position"].update({"x": float("nan")}), "finite"),
        (lambda item: item["position"].update({"x": -1.0}), "bounds"),
        (lambda item: item["position"].update({"x": 950.0}), "bounds"),
    ],
)
def test_non_finite_or_out_of_pallet_coordinates_are_rejected(mutator, message):
    item = _box("bad", 0, 0, 0)
    mutator(item)

    with pytest.raises(ExecutionSequenceError, match=message):
        sequence_pallet_items(_pallet([item]))


@pytest.mark.parametrize(
    "field, value",
    [
        ("coordinate_tolerance_mm", float("inf")),
        ("box_xy_clearance_mm", float("nan")),
        ("suction_xy_clearance_mm", float("inf")),
        ("suction_z_clearance_mm", float("nan")),
    ],
)
def test_non_finite_execution_clearances_are_rejected(field, value):
    with pytest.raises(ValueError, match="finite"):
        ExecutionSequenceConfig(**{field: value})


def test_report_schema_and_item_values_are_preserved_while_order_changes():
    tall = _box("tall", 0, 0, 0, height=300)
    short = _box("short", 200, 0, 0, height=100)
    tall.update({
        "seq": 1,
        "original_packing_sequence": 1,
        "robot_packing_sequence": 2,
    })
    short.update({
        "seq": 2,
        "original_packing_sequence": 2,
        "robot_packing_sequence": 1,
    })
    source = {
        "packing_plan_id": None,
        "total_runtime_seconds": 1.25,
        "summary": {"total_pallets": 1},
        "pallets": [
            {
                **_pallet([tall, short]),
                "mpm_total": 10.0,
                "mpm_target": 192.0,
                "mpm_status": "FAILED",
                "custom_field": {"preserve": True},
            }
        ],
    }
    original = deepcopy(source)

    result = plan_execution_report(source)

    assert source == original, "source report must remain immutable"
    assert set(result) == set(source)
    assert set(result["pallets"][0]) == set(source["pallets"][0])
    assert _ids(result["pallets"][0]["packed_items"]) == ["short", "tall"]
    source_by_id = {item["id"]: item for item in source["pallets"][0]["packed_items"]}
    for seq, item in enumerate(result["pallets"][0]["packed_items"], 1):
        expected = deepcopy(source_by_id[item["id"]])
        expected.pop("original_packing_sequence")
        expected.pop("robot_packing_sequence")
        expected["seq"] = seq
        assert item == expected


def test_wcs_seq_follows_execution_order_while_layer_id_remains_geometric():
    tall = _box("tall", 0, 0, 0, height=300)
    tall["product_code"] = 1
    short = _box("short", 200, 0, 0, height=100)
    short["product_code"] = 2
    report = {
        "pallets": [
            {
                **_pallet([tall, short]),
                "mpm_status": "FAILED",
                "case_group": 0,
            }
        ]
    }

    result = report_to_execution_plan_result(report)

    assert len(result.cases) == 1
    cartons = [
        carton
        for layer in result.cases[0]["layers"]
        for carton in layer["cartons"]
    ]
    cartons_by_seq = sorted(cartons, key=lambda carton: carton["seq"])
    assert [carton["seq"] for carton in cartons_by_seq] == [1, 2]
    assert [carton["product_code"] for carton in cartons_by_seq] == [2, 1]
    assert {carton["layer_id"] for carton in cartons_by_seq} == {1}
    mapped = next(iter(result.plan_by_unique_id.values()))
    assert _ids(mapped["packed_items"]) == ["short", "tall"]


def _cli_report():
    tall = _box("tall", 0, 0, 0, height=300)
    tall["product_code"] = 1
    short = _box("short", 200, 0, 0, height=100)
    short["product_code"] = 2
    return {
        "packing_plan_id": None,
        "summary": {"total_pallets": 1},
        "pallets": [
            {
                **_pallet([tall, short]),
                "mpm_status": "FAILED",
                "case_group": 0,
            }
        ],
    }


def test_cli_writes_same_schema_execution_and_optional_wcs_files(tmp_path):
    source = tmp_path / "packing.json"
    output = tmp_path / "packing_execution.json"
    wcs_output = tmp_path / "packing_wcs.json"
    report = _cli_report()
    source.write_text(json.dumps(report), encoding="utf-8")
    script = Path(__file__).resolve().parents[1] / "run_execution_planning.py"

    completed = subprocess.run(
        [
            sys.executable,
            str(script),
            str(source),
            "--output",
            str(output),
            "--wcs-output",
            str(wcs_output),
            "--origin",
            "x_min_y_min",
        ],
        cwd=str(script.parent),
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    assert json.loads(source.read_text(encoding="utf-8")) == report
    execution = json.loads(output.read_text(encoding="utf-8"))
    assert set(execution) == set(report)
    assert _ids(execution["pallets"][0]["packed_items"]) == ["short", "tall"]
    cases = json.loads(wcs_output.read_text(encoding="utf-8"))
    cartons = [
        carton
        for layer in cases[0]["layers"]
        for carton in layer["cartons"]
    ]
    assert [c["product_code"] for c in sorted(cartons, key=lambda c: c["seq"])] \
        == [2, 1]
    map_output = wcs_output.with_name(wcs_output.stem + "_map.json")
    persisted_map = json.loads(map_output.read_text(encoding="utf-8"))
    unique_id = cases[0]["box_unique_id"]
    mapped_items = persisted_map[unique_id]["packed_items"]
    assert _ids(mapped_items) == ["short", "tall"]
    assert mapped_items[0]["position"] == {"x": 200.0, "y": 0.0, "z": 0.0}
    assert mapped_items[0]["suction_orientation"] == "cup_100x_100y"


def test_cli_skips_execution_outputs_when_config_disables_planning(tmp_path):
    source = tmp_path / "packing.json"
    output = tmp_path / "packing_execution.json"
    config = tmp_path / "packing_config.yaml"
    source.write_text(json.dumps(_cli_report()), encoding="utf-8")
    config.write_text(
        "execution_sequence:\n  enabled: false\n",
        encoding="utf-8",
    )
    script = Path(__file__).resolve().parents[1] / "run_execution_planning.py"

    completed = subprocess.run(
        [
            sys.executable,
            str(script),
            str(source),
            "--output",
            str(output),
            "--config",
            str(config),
        ],
        cwd=str(script.parent),
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    assert "disabled" in completed.stdout
    assert not output.exists()


def test_cli_uses_execution_origin_from_config(tmp_path):
    source = tmp_path / "packing.json"
    output = tmp_path / "packing_execution.json"
    config = tmp_path / "packing_config.yaml"
    left = _box("left", 0, 0, 0)
    right = _box("right", 200, 0, 0)
    report = {"pallets": [_pallet([left, right])]}
    source.write_text(json.dumps(report), encoding="utf-8")
    config.write_text(
        "execution_sequence:\n"
        "  enabled: true\n"
        "  origin: x_max_y_min\n",
        encoding="utf-8",
    )
    script = Path(__file__).resolve().parents[1] / "run_execution_planning.py"

    completed = subprocess.run(
        [
            sys.executable,
            str(script),
            str(source),
            "--output",
            str(output),
            "--config",
            str(config),
        ],
        cwd=str(script.parent),
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    execution = json.loads(output.read_text(encoding="utf-8"))
    assert _ids(execution["pallets"][0]["packed_items"]) == ["right", "left"]


def test_cli_rejects_invalid_boolean_config_without_output(tmp_path):
    source = tmp_path / "packing.json"
    output = tmp_path / "packing_execution.json"
    config = tmp_path / "packing_config.yaml"
    source.write_text(json.dumps(_cli_report()), encoding="utf-8")
    config.write_text(
        "execution_sequence:\n  enabled: 'false'\n",
        encoding="utf-8",
    )
    script = Path(__file__).resolve().parents[1] / "run_execution_planning.py"

    completed = subprocess.run(
        [
            sys.executable,
            str(script),
            str(source),
            "--output",
            str(output),
            "--config",
            str(config),
        ],
        cwd=str(script.parent),
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 1
    assert "enabled must be a boolean" in completed.stderr
    assert not output.exists()


def test_cli_refuses_to_overwrite_source_json(tmp_path):
    source = tmp_path / "packing.json"
    report = _cli_report()
    source.write_text(json.dumps(report), encoding="utf-8")
    script = Path(__file__).resolve().parents[1] / "run_execution_planning.py"

    completed = subprocess.run(
        [
            sys.executable,
            str(script),
            str(source),
            "--output",
            str(source),
        ],
        cwd=str(script.parent),
        capture_output=True,
        text=True,
    )

    assert completed.returncode != 0
    assert "must not overwrite" in completed.stderr
    assert json.loads(source.read_text(encoding="utf-8")) == report


def test_cli_rejects_nan_clearance_without_writing_output(tmp_path):
    source = tmp_path / "packing.json"
    output = tmp_path / "execution.json"
    source.write_text(json.dumps(_cli_report()), encoding="utf-8")
    script = Path(__file__).resolve().parents[1] / "run_execution_planning.py"

    completed = subprocess.run(
        [
            sys.executable,
            str(script),
            str(source),
            "--output",
            str(output),
            "--xy-clearance-mm",
            "nan",
        ],
        cwd=str(script.parent),
        capture_output=True,
        text=True,
    )

    assert completed.returncode != 0
    assert "finite" in completed.stderr
    assert not output.exists()


def test_wcs_cases_are_not_published_when_release_replace_fails(
    tmp_path, monkeypatch
):
    execution = tmp_path / "execution.json"
    plan_map = tmp_path / "cases_map.json"
    cases = tmp_path / "cases.json"
    execution.write_text(json.dumps({"old": "execution"}), encoding="utf-8")
    plan_map.write_text(json.dumps({"old": "map"}), encoding="utf-8")
    cases.write_text(json.dumps([{"old": True}]), encoding="utf-8")
    original_replace = Path.replace
    failed = {"value": False}

    def fail_cases_replace(path, target):
        if (
            Path(target) == cases
            and ".tmp-" in Path(path).name
            and not failed["value"]
        ):
            failed["value"] = True
            raise OSError("simulated release failure")
        return original_replace(path, target)

    monkeypatch.setattr(Path, "replace", fail_cases_replace)

    with pytest.raises(OSError, match="simulated"):
        _publish_json_files(
            [
                (execution, {"new": "execution"}),
                (plan_map, {"new": "map"}),
                (cases, [{"new": "cases"}]),
            ],
            release_path=cases,
        )

    assert json.loads(cases.read_text(encoding="utf-8")) == [{"old": True}]
    assert json.loads(plan_map.read_text(encoding="utf-8")) == {"old": "map"}
    assert json.loads(execution.read_text(encoding="utf-8")) == {
        "old": "execution"
    }
