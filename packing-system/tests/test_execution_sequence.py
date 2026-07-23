"""Independent execution-order planning tests."""

import json
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

import pytest

from src.execution import sequence_planner as sequence_planner_module
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


def test_layerwise_origin_scan_precedes_resulting_top_height():
    tall_at_origin = _box("tall", 0, 0, 0, height=300)
    short_farther = _box("short", 200, 0, 0, height=100)

    ordered = sequence_pallet_items(
        _pallet([tall_at_origin, short_farther]),
        ExecutionSequenceConfig(origin="x_min_y_min"),
    )

    assert _ids(ordered) == ["tall", "short"]


@pytest.mark.parametrize(
    "origin, expected",
    [
        ("x_min_y_min", ["00", "01", "10", "11"]),
        ("x_max_y_max", ["11", "10", "01", "00"]),
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


@pytest.mark.parametrize("preserve_open_direction", [True, False])
def test_regular_mode_scans_x_columns_then_y(preserve_open_direction):
    boxes = [
        _box("c10", 140, 0, 0, length=101, width=41, height=61),
        _box("c01", 0, 160, 0, length=59, width=73, height=61),
        _box("c00", 0, 0, 0, length=83, width=47, height=61),
    ]

    ordered = sequence_pallet_items(
        _pallet(boxes),
        ExecutionSequenceConfig(
            preserve_open_direction=preserve_open_direction,
            adaptive_staircase_enabled=False,
        ),
    )

    assert _ids(ordered) == ["c00", "c01", "c10"]


def test_origin_scan_groups_nearby_x_coordinates_into_one_column():
    boxes = [
        _box("same_column_y200", 0.0, 200.0, 0),
        _box("same_column_y0", 1.0, 0.0, 0),
        _box("next_column", 150.0, 0.0, 0),
    ]

    ordered = sequence_pallet_items(
        _pallet(boxes),
        ExecutionSequenceConfig(
            preserve_open_direction=True,
            adaptive_staircase_enabled=False,
            scan_column_tolerance_mm=2.0,
        ),
    )

    assert _ids(ordered) == [
        "same_column_y0",
        "same_column_y200",
        "next_column",
    ]


def test_default_scan_column_tolerance_groups_five_mm_layout_offset():
    boxes = [
        _box("far_shifted_left", 0.0, 200.0, 0),
        _box("near_origin", 5.0, 0.0, 0),
        _box("next_column", 150.0, 0.0, 0),
    ]

    ordered = sequence_pallet_items(
        _pallet(boxes),
        ExecutionSequenceConfig(
            preserve_open_direction=True,
            adaptive_staircase_enabled=False,
        ),
    )

    assert _ids(ordered) == [
        "near_origin",
        "far_shifted_left",
        "next_column",
    ]


def test_regular_scan_keeps_input_order_at_same_column_and_y():
    boxes = [
        _box("x4_first", 4.0, 0.0, 0, length=1.0, width=1.0),
        _box("x0_second", 0.0, 0.0, 0, length=1.0, width=1.0),
    ]

    ordered = sequence_pallet_items(
        _pallet(boxes),
        ExecutionSequenceConfig(
            preserve_open_direction=False,
            adaptive_staircase_enabled=False,
            scan_column_tolerance_mm=5.0,
        ),
    )

    assert _ids(ordered) == ["x4_first", "x0_second"]


def test_regular_scan_columns_are_anchored_per_geometric_layer():
    support = _box(
        "support",
        0,
        0,
        0,
        length=20,
        width=300,
        height=100,
    )
    same_column_y200 = _box(
        "same_column_y200",
        4,
        200,
        100,
        length=1,
        width=1,
    )
    same_column_y0 = _box(
        "same_column_y0",
        9,
        0,
        100,
        length=1,
        width=1,
    )

    ordered = sequence_pallet_items(
        _pallet([same_column_y200, same_column_y0, support]),
        ExecutionSequenceConfig(
            preserve_open_direction=True,
            adaptive_staircase_enabled=False,
            max_occupied_directions=4,
            scan_column_tolerance_mm=5.0,
        ),
    )

    assert _ids(ordered) == [
        "support",
        "same_column_y0",
        "same_column_y200",
    ]


def test_hard_dependency_resumes_stable_forward_scan_without_open_reason(caplog):
    scan_first = _box("A", 0, 0, 0, height=300)
    scan_middle = _box("B", 200, 0, 0, height=100)
    scan_last = _box(
        "C",
        400,
        0,
        0,
        height=200,
        cup_rect={"x_min": 50, "x_max": 500, "y_min": 0, "y_max": 100},
    )
    boxes = [scan_first, scan_middle, scan_last]
    edges, indegree, _supports = sequence_planner_module._support_edges(
        boxes, 0.001
    )
    sequence_planner_module._add_clearance_edges(
        boxes, ExecutionSequenceConfig(), edges, indegree
    )

    assert edges == [set(), set(), {0}]

    with caplog.at_level("WARNING", logger=sequence_planner_module.__name__):
        ordered = sequence_pallet_items(
            _pallet(boxes),
            ExecutionSequenceConfig(adaptive_staircase_enabled=False),
        )

    assert _ids(ordered) == ["B", "C", "A"]
    assert "execution scan deviation" in caplog.text
    assert "expected='A'" in caplog.text
    assert "selected='B'" in caplog.text
    assert "reason=hard_dependency" in caplog.text
    assert "reason=open_direction" not in caplog.text
    deviation_warnings = [
        record.getMessage()
        for record in caplog.records
        if "execution scan deviation" in record.getMessage()
    ]
    assert len(deviation_warnings) == 1
    assert "count=1" in deviation_warnings[0]
    assert "selected='C'" not in deviation_warnings[0]


def test_scan_deviations_use_one_warning_and_preview_at_most_eight(caplog):
    pair_count = 9
    items = []
    edges = [set() for _idx in range(pair_count * 2)]
    forward_keys = []
    expected_order = []
    for pair_idx in range(pair_count):
        expected_idx = pair_idx * 2
        prerequisite_idx = expected_idx + 1
        items.extend(
            [
                {"id": "A%d" % (pair_idx + 1)},
                {"id": "B%d" % (pair_idx + 1)},
            ]
        )
        edges[prerequisite_idx].add(expected_idx)
        forward_keys.extend([(expected_idx,), (prerequisite_idx,)])
        expected_order.extend([prerequisite_idx, expected_idx])

    with caplog.at_level("WARNING", logger=sequence_planner_module.__name__):
        ordered_indices = sequence_planner_module._stable_forward_order(
            items=items,
            edges=edges,
            config=ExecutionSequenceConfig(preserve_open_direction=False),
            forward_keys=forward_keys,
            blockers=None,
            deadline=sequence_planner_module.time.monotonic() + 1.0,
            pallet_id="P-log-limit",
        )

    assert ordered_indices == expected_order
    deviation_warnings = [
        record.getMessage()
        for record in caplog.records
        if "execution scan deviation" in record.getMessage()
    ]
    assert len(deviation_warnings) == 1
    assert "count=9" in deviation_warnings[0]
    assert "expected='A8'" in deviation_warnings[0]
    assert "expected='A9'" not in deviation_warnings[0]


def test_forward_scheduler_skips_locally_safe_candidate_when_residual_is_blocked(
    caplog,
):
    scan_first = _box("A", 0, 0, 0, height=300)
    support = _box("B", 100, 0, 0, height=100)
    supported = _box("C", 100, 0, 100, height=100)

    with caplog.at_level("WARNING", logger=sequence_planner_module.__name__):
        ordered = sequence_pallet_items(
            _pallet([scan_first, support, supported]),
            ExecutionSequenceConfig(
                adaptive_staircase_enabled=False,
                max_occupied_directions=0,
            ),
        )

    assert _ids(ordered) == ["B", "C", "A"]
    assert "expected='A'" in caplog.text
    assert "selected='B'" in caplog.text
    assert "reason=open_direction" in caplog.text
    assert "lookahead=true" in caplog.text


def test_open_direction_scan_deviation_is_logged_with_specific_reason(caplog):
    boxes = [
        _box("center", 100, 100, 0),
        _box("left", 0, 100, 0),
        _box("below", 50, 0, 0),
        _box("above", 50, 200, 0),
    ]

    with caplog.at_level("WARNING", logger=sequence_planner_module.__name__):
        ordered = sequence_pallet_items(
            _pallet(boxes),
            ExecutionSequenceConfig(
                preserve_open_direction=True,
                adaptive_staircase_enabled=False,
                max_occupied_directions=2,
            ),
        )

    assert _ids(ordered) == ["left", "below", "center", "above"]
    assert "box='above' after='center'" in caplog.text
    assert "reason=open_direction" in caplog.text


def test_disabling_open_direction_keeps_scan_order_without_the_gate():
    boxes = [
        _box("center", 100, 100, 0),
        _box("left", 0, 100, 0),
        _box("below", 50, 0, 0),
        _box("above", 50, 200, 0),
    ]

    ordered = sequence_pallet_items(
        _pallet(boxes),
        ExecutionSequenceConfig(
            preserve_open_direction=False,
            adaptive_staircase_enabled=False,
            max_occupied_directions=2,
        ),
    )

    assert _ids(ordered) == ["left", "below", "above", "center"]


def test_wavefront_does_not_fill_a_three_sided_pocket():
    below = _box("below", 100, 200, 0)
    left = _box("left", 0, 300, 0)
    right = _box("right", 200, 100, 0, width=300)
    center = _box("center", 100, 300, 0)

    ordered = sequence_pallet_items(
        _pallet([center, left, right, below]),
        ExecutionSequenceConfig(
            origin="x_min_y_min",
            max_occupied_directions=2,
            side_neighbor_clearance_mm=5.0,
        ),
    )

    positions = {item["id"]: item["seq"] for item in ordered}
    placed_neighbors = sum(
        positions[box_id] < positions["center"]
        for box_id in ("below", "left", "right")
    )
    assert placed_neighbors <= 2


def test_lower_side_boxes_do_not_enclose_a_taller_box():
    below = _box("below", 100, 200, 0, height=100)
    left = _box("left", 0, 300, 0, height=100)
    right = _box("right", 200, 100, 0, width=300, height=100)
    center = _box("center", 100, 300, 0, height=200)

    ordered = sequence_pallet_items(
        _pallet([center, left, right, below]),
        ExecutionSequenceConfig(
            max_occupied_directions=2,
            side_neighbor_clearance_mm=5.0,
            side_height_tolerance_mm=2.0,
        ),
    )

    positions = {item["id"]: item["seq"] for item in ordered}
    placed_neighbors = sum(
        positions[box_id] < positions["center"]
        for box_id in ("below", "left", "right")
    )
    assert placed_neighbors <= 2


def _mixed_height_staircase_boxes():
    return [
        _box("far_tall", 200, 0, 0, height=200),
        _box("outer_base", 100, 0, 0, height=100),
        _box("origin_top", 0, 0, 100, height=100),
        _box("origin_base", 0, 0, 0, height=100),
    ]


def test_disabled_adaptive_staircase_keeps_mixed_pallet_layerwise():
    ordered = sequence_pallet_items(
        _pallet(_mixed_height_staircase_boxes()),
        ExecutionSequenceConfig(
            adaptive_staircase_enabled=False,
            staircase_height_difference_threshold_mm=100.0,
        ),
    )

    assert _ids(ordered).index("outer_base") < _ids(ordered).index("origin_top")


@pytest.mark.parametrize("preserve_open_direction", [True, False])
def test_enabled_adaptive_staircase_lays_outer_foundation_before_raising(
    preserve_open_direction,
):
    ordered = sequence_pallet_items(
        _pallet(_mixed_height_staircase_boxes()),
        ExecutionSequenceConfig(
            preserve_open_direction=preserve_open_direction,
            adaptive_staircase_enabled=True,
            staircase_height_difference_threshold_mm=100.0,
            staircase_transition_ratio_threshold=0.5,
            staircase_min_transition_edges=1,
        ),
    )

    assert _ids(ordered)[:3] == ["origin_base", "outer_base", "origin_top"]


def test_enabled_adaptive_staircase_keeps_regular_pallet_layerwise():
    boxes = [
        _box("outer_base", 100, 0, 0, height=100),
        _box("origin_top", 0, 0, 100, height=100),
        _box("origin_base", 0, 0, 0, height=100),
    ]

    ordered = sequence_pallet_items(
        _pallet(boxes),
        ExecutionSequenceConfig(
            adaptive_staircase_enabled=True,
            staircase_height_difference_threshold_mm=100.0,
        ),
    )

    assert _ids(ordered) == ["origin_base", "outer_base", "origin_top"]


def test_height_difference_below_threshold_remains_layerwise():
    boxes = _mixed_height_staircase_boxes()
    boxes[0] = _box("far_tall", 200, 0, 0, height=150)

    ordered = sequence_pallet_items(
        _pallet(boxes),
        ExecutionSequenceConfig(
            adaptive_staircase_enabled=True,
            staircase_height_difference_threshold_mm=100.0,
        ),
    )

    assert _ids(ordered).index("outer_base") < _ids(ordered).index("origin_top")


def test_adaptive_staircase_ignores_height_spread_between_flat_layers():
    geometry = [
        (0.0, 0.0, 0.0, 100.0, 100.0, 200.0),
        (100.0, 0.0, 0.0, 100.0, 100.0, 200.0),
        (0.0, 0.0, 200.0, 100.0, 100.0, 100.0),
        (100.0, 0.0, 200.0, 100.0, 100.0, 100.0),
    ]

    assert sequence_planner_module._uses_staircase_wave(
        geometry,
        ExecutionSequenceConfig(
            adaptive_staircase_enabled=True,
            staircase_height_difference_threshold_mm=100.0,
        ),
    ) is False


def test_adaptive_staircase_requires_ratio_when_transition_count_is_met():
    geometry = []
    for x in range(3):
        for y in range(3):
            height = 200.0 if (x, y) == (0, 0) else 100.0
            geometry.append(
                (x * 100.0, y * 100.0, 0.0, 100.0, 100.0, height)
            )

    assert sequence_planner_module._uses_staircase_wave(
        geometry,
        ExecutionSequenceConfig(
            adaptive_staircase_enabled=True,
            staircase_height_difference_threshold_mm=100.0,
            staircase_transition_ratio_threshold=0.25,
            staircase_min_transition_edges=2,
        ),
    ) is False


def test_adaptive_staircase_requires_count_when_transition_ratio_is_met():
    geometry = [
        (0.0, 0.0, 0.0, 100.0, 100.0, 200.0),
        (100.0, 0.0, 0.0, 100.0, 100.0, 100.0),
    ]

    assert sequence_planner_module._uses_staircase_wave(
        geometry,
        ExecutionSequenceConfig(
            adaptive_staircase_enabled=True,
            staircase_height_difference_threshold_mm=100.0,
            staircase_transition_ratio_threshold=1.0,
            staircase_min_transition_edges=2,
        ),
    ) is False


def test_adaptive_staircase_detects_frequent_layer_height_transitions():
    geometry = []
    for x in range(3):
        for y in range(3):
            height = 200.0 if (x + y) % 2 == 0 else 100.0
            geometry.append(
                (x * 100.0, y * 100.0, 0.0, 100.0, 100.0, height)
            )

    assert sequence_planner_module._uses_staircase_wave(
        geometry,
        ExecutionSequenceConfig(
            adaptive_staircase_enabled=True,
            staircase_height_difference_threshold_mm=100.0,
        ),
    ) is True


def test_adaptive_classification_logs_mode_trigger_and_edge_counts(caplog):
    boxes = [
        _box("tall", 0, 0, 0, height=200),
        _box("short", 100, 0, 0, height=100),
    ]

    with caplog.at_level("INFO", logger=sequence_planner_module.__name__):
        sequence_pallet_items(
            _pallet(boxes),
            ExecutionSequenceConfig(
                preserve_open_direction=False,
                adaptive_staircase_enabled=True,
                staircase_height_difference_threshold_mm=100.0,
                staircase_transition_ratio_threshold=1.0,
                staircase_min_transition_edges=1,
            ),
        )

    assert "classification pallet='P-1'" in caplog.text
    assert "selected_mode=staircase" in caplog.text
    assert "trigger_layer=0.0" in caplog.text
    assert "adjacent_count=1" in caplog.text
    assert "transition_count=1" in caplog.text
    assert "transition_ratio=1.000" in caplog.text


def test_staircase_uses_configured_origin_corner():
    ordered = sequence_pallet_items(
        _pallet(_mixed_height_staircase_boxes()),
        ExecutionSequenceConfig(
            origin="x_max_y_min",
            adaptive_staircase_enabled=True,
            staircase_height_difference_threshold_mm=100.0,
            staircase_transition_ratio_threshold=0.5,
            staircase_min_transition_edges=1,
        ),
    )

    assert _ids(ordered)[0] == "far_tall"


def test_adaptive_staircase_counts_lower_boxes_when_preventing_pockets():
    below = _box("below", 100, 200, 0, height=100)
    left = _box("left", 0, 300, 0, height=100)
    right = _box("right", 200, 100, 0, width=300, height=100)
    center = _box("center", 100, 300, 0, height=200)

    ordered = sequence_pallet_items(
        _pallet([center, left, right, below]),
        ExecutionSequenceConfig(
            adaptive_staircase_enabled=True,
            staircase_height_difference_threshold_mm=100.0,
            staircase_transition_ratio_threshold=0.5,
            staircase_min_transition_edges=1,
            max_occupied_directions=2,
            side_neighbor_clearance_mm=5.0,
        ),
    )

    positions = {item["id"]: item["seq"] for item in ordered}
    placed_neighbors = sum(
        positions[box_id] < positions["center"]
        for box_id in ("below", "left", "right")
    )
    assert placed_neighbors <= 2


def test_staircase_places_equal_phase_diagonal_base_before_inner_upper():
    boxes = [
        _box("origin_upper", 0, 0, 240, height=120),
        _box("diagonal_base", 100, 100, 0, height=240),
        _box("y_base", 0, 100, 0, height=240),
        _box("x_base", 100, 0, 0, height=240),
        _box("origin_mid", 0, 0, 120, height=120),
        _box("origin_base", 0, 0, 0, height=120),
    ]

    ordered = sequence_pallet_items(
        _pallet(boxes),
        ExecutionSequenceConfig(
            adaptive_staircase_enabled=True,
            staircase_height_difference_threshold_mm=120.0,
            staircase_transition_ratio_threshold=0.5,
            staircase_min_transition_edges=1,
            max_occupied_directions=4,
        ),
    )

    positions = {item["id"]: item["seq"] for item in ordered}
    assert positions["diagonal_base"] < positions["origin_upper"]


def test_staircase_scan_columns_are_anchored_per_phase_and_tier(monkeypatch):
    geometry = [
        (0.0, 0.0, 0.0, 1.0, 1.0, 100.0),
        (4.0, 200.0, 0.0, 1.0, 1.0, 100.0),
        (9.0, 0.0, 0.0, 1.0, 1.0, 100.0),
    ]
    shells = {
        sequence_planner_module._footprint(geometry[0]): 0,
        sequence_planner_module._footprint(geometry[1]): 1,
        sequence_planner_module._footprint(geometry[2]): 1,
    }
    monkeypatch.setattr(
        sequence_planner_module,
        "_staircase_shells",
        lambda *_args, **_kwargs: shells,
    )
    blockers = [
        {"x-": set(), "x+": set(), "y-": set(), "y+": set()}
        for _entry in geometry
    ]

    ordered_indices = sequence_planner_module._greedy_staircase_order(
        [{"id": "other_phase"}, {"id": "y200"}, {"id": "y0"}],
        [set(), set(), set()],
        [set(), set(), set()],
        ExecutionSequenceConfig(
            max_occupied_directions=4,
            scan_column_tolerance_mm=5.0,
        ),
        PALLET_DIMS,
        geometry,
        blockers,
        blockers,
        sequence_planner_module.time.monotonic() + 1.0,
    )

    assert ordered_indices == [0, 2, 1]


def test_staircase_scan_keeps_input_order_at_same_column_and_y(monkeypatch):
    geometry = [
        (4.0, 0.0, 0.0, 1.0, 1.0, 100.0),
        (0.0, 0.0, 0.0, 1.0, 1.0, 100.0),
    ]
    shells = {
        sequence_planner_module._footprint(entry): 0
        for entry in geometry
    }
    monkeypatch.setattr(
        sequence_planner_module,
        "_staircase_shells",
        lambda *_args, **_kwargs: shells,
    )
    blockers = [
        {"x-": set(), "x+": set(), "y-": set(), "y+": set()},
        {"x-": set(), "x+": set(), "y-": set(), "y+": set()},
    ]

    ordered_indices = sequence_planner_module._greedy_staircase_order(
        [{"id": "x4_first"}, {"id": "x0_second"}],
        [set(), set()],
        [set(), set()],
        ExecutionSequenceConfig(
            preserve_open_direction=False,
            scan_column_tolerance_mm=5.0,
        ),
        PALLET_DIMS,
        geometry,
        blockers,
        blockers,
        sequence_planner_module.time.monotonic() + 1.0,
    )

    assert ordered_indices == [0, 1]


def test_staircase_scan_precedes_lower_neighbor_risk_within_same_phase(
    monkeypatch,
):
    geometry = [
        (200.0, 0.0, 0.0, 100.0, 100.0, 200.0),
        (0.0, 0.0, 0.0, 100.0, 100.0, 200.0),
    ]
    footprints = {
        sequence_planner_module._footprint(entry): 0
        for entry in geometry
    }
    monkeypatch.setattr(
        sequence_planner_module,
        "_staircase_shells",
        lambda *_args, **_kwargs: footprints,
    )
    empty_blockers = [
        {"x-": set(), "x+": set(), "y-": set(), "y+": set()},
        {"x-": set(), "x+": set(), "y-": set(), "y+": set()},
    ]
    vertical_blockers = deepcopy(empty_blockers)
    vertical_blockers[0] = {
        "x-": {1},
        "x+": {1},
        "y-": {1},
        "y+": set(),
    }

    ordered_indices = sequence_planner_module._greedy_staircase_order(
        [{"id": "riskier"}, {"id": "safer"}],
        [set(), set()],
        [set(), set()],
        ExecutionSequenceConfig(),
        PALLET_DIMS,
        geometry,
        empty_blockers,
        vertical_blockers,
        sequence_planner_module.time.monotonic() + 1.0,
    )

    assert ordered_indices == [1, 0]


def test_open_direction_time_limit_is_reported_by_public_planner(monkeypatch):
    boxes = [
        _box("00", 0, 0, 0),
        _box("10", 100, 0, 0),
        _box("01", 0, 100, 0),
        _box("11", 100, 100, 0),
    ]
    timestamps = iter((0.0, 2.0, 2.0))
    monkeypatch.setattr(
        sequence_planner_module.time,
        "monotonic",
        lambda: next(timestamps, 2.0),
    )

    with pytest.raises(ExecutionSequenceError, match="within 1.000s"):
        sequence_pallet_items(
            _pallet(boxes),
            ExecutionSequenceConfig(
                max_sequence_search_seconds_per_pallet=1.0,
            ),
        )


def test_blocker_map_checks_deadline_inside_pair_scan(monkeypatch):
    timestamps = iter((0.0, 0.0, 2.0))
    monkeypatch.setattr(
        sequence_planner_module.time,
        "monotonic",
        lambda: next(timestamps, 2.0),
    )

    with pytest.raises(
        sequence_planner_module._ExecutionSequenceDeadlineExceeded
    ):
        sequence_planner_module._direction_blocker_map(
            [
                (0.0, 0.0, 0.0, 100.0, 100.0, 100.0),
                (100.0, 0.0, 0.0, 100.0, 100.0, 100.0),
            ],
            ExecutionSequenceConfig(),
            deadline=1.0,
        )


def test_staircase_shells_check_deadline_inside_pair_scan(monkeypatch):
    timestamps = iter((0.0, 0.0, 2.0))
    monkeypatch.setattr(
        sequence_planner_module.time,
        "monotonic",
        lambda: next(timestamps, 2.0),
    )

    with pytest.raises(
        sequence_planner_module._ExecutionSequenceDeadlineExceeded
    ):
        sequence_planner_module._staircase_shells(
            [
                (0.0, 0.0, 0.0, 100.0, 100.0, 100.0),
                (100.0, 0.0, 0.0, 100.0, 100.0, 100.0),
                (200.0, 0.0, 0.0, 100.0, 100.0, 100.0),
            ],
            ExecutionSequenceConfig(),
            PALLET_DIMS,
            deadline=1.0,
        )


def test_staircase_candidate_scoring_checks_deadline(monkeypatch):
    geometry = [
        (100.0, 0.0, 0.0, 100.0, 100.0, 200.0),
        (0.0, 0.0, 0.0, 100.0, 100.0, 200.0),
    ]
    shells = {
        sequence_planner_module._footprint(entry): 0
        for entry in geometry
    }
    monkeypatch.setattr(
        sequence_planner_module,
        "_staircase_shells",
        lambda *_args, **_kwargs: shells,
    )
    timestamps = iter((0.0, 0.0, 0.0, 2.0))
    monkeypatch.setattr(
        sequence_planner_module.time,
        "monotonic",
        lambda: next(timestamps, 2.0),
    )
    blockers = [
        {"x-": set(), "x+": set(), "y-": set(), "y+": set()},
        {"x-": set(), "x+": set(), "y-": set(), "y+": set()},
    ]

    with pytest.raises(
        sequence_planner_module._ExecutionSequenceDeadlineExceeded
    ):
        sequence_planner_module._greedy_staircase_order(
                [{"id": "far"}, {"id": "near"}],
                [set(), set()],
                [set(), set()],
                ExecutionSequenceConfig(),
            PALLET_DIMS,
            geometry,
            blockers,
            blockers,
            deadline=1.0,
        )


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


@pytest.mark.parametrize(
    "field, value, message",
    [
        ("max_occupied_directions", 5, "integer from 0 to 4"),
        ("max_occupied_directions", True, "integer from 0 to 4"),
        ("side_neighbor_clearance_mm", -1.0, "non-negative"),
        ("side_neighbor_clearance_mm", True, "finite number"),
        ("side_height_tolerance_mm", float("inf"), "finite"),
        ("side_height_tolerance_mm", False, "finite number"),
        ("preserve_open_direction", "true", "boolean"),
        ("max_sequence_search_seconds_per_pallet", 0.0, "positive"),
        ("max_sequence_search_seconds_per_pallet", True, "finite number"),
        ("adaptive_staircase_enabled", "true", "boolean"),
        (
            "staircase_height_difference_threshold_mm",
            -1.0,
            "non-negative",
        ),
        ("staircase_transition_ratio_threshold", 1.1, "between 0 and 1"),
        ("staircase_min_transition_edges", 0, "positive integer"),
        ("scan_column_tolerance_mm", -1.0, "non-negative"),
    ],
)
def test_invalid_open_direction_settings_are_rejected(field, value, message):
    with pytest.raises(ValueError, match=message):
        ExecutionSequenceConfig(**{field: value})


def test_report_business_values_are_preserved_while_execution_fields_change():
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
    assert _ids(result["pallets"][0]["packed_items"]) == ["tall", "short"]
    source_by_id = {item["id"]: item for item in source["pallets"][0]["packed_items"]}
    for seq, item in enumerate(result["pallets"][0]["packed_items"], 1):
        expected = deepcopy(source_by_id[item["id"]])
        expected.pop("original_packing_sequence")
        expected.pop("robot_packing_sequence")
        expected["seq"] = seq
        actual_business = deepcopy(item)
        expected_business = deepcopy(expected)
        for value in (actual_business, expected_business):
            value.pop("position")
            value.pop("suction_rect_x_min")
            value.pop("suction_rect_x_max")
            value.pop("suction_rect_y_min")
            value.pop("suction_rect_y_max")
            value.pop("stack_height_before", None)
        assert actual_business == expected_business


def test_execution_layout_is_centered_and_suction_coordinates_move_with_boxes():
    left = _box("left", 0, 0, 0)
    right = _box("right", 200, 0, 0)
    source = {"pallets": [_pallet([right, left])]}

    result = plan_execution_report(source)

    by_id = {
        item["id"]: item
        for item in result["pallets"][0]["packed_items"]
    }
    assert by_id["left"]["position"] == {"x": 350.0, "y": 450.0, "z": 0.0}
    assert by_id["right"]["position"] == {"x": 550.0, "y": 450.0, "z": 0.0}
    assert by_id["left"]["suction_rect_x_min"] == 350.0
    assert by_id["left"]["suction_rect_x_max"] == 450.0
    assert by_id["left"]["suction_rect_y_min"] == 450.0
    assert by_id["left"]["suction_rect_y_max"] == 550.0


def test_execution_layout_does_not_shift_an_axis_with_no_remaining_space():
    full_length = _box("full", 0, 0, 0, length=1000.0, width=100.0)

    result = plan_execution_report({"pallets": [_pallet([full_length])]})

    item = result["pallets"][0]["packed_items"][0]
    assert item["position"] == {"x": 0.0, "y": 450.0, "z": 0.0}
    assert item["suction_rect_x_min"] == 0.0
    assert item["suction_rect_x_max"] == 1000.0
    assert item["suction_rect_y_min"] == 450.0
    assert item["suction_rect_y_max"] == 550.0


def test_execution_layout_recomputes_robot_depth_after_centering():
    item = _box("centered", 0, 0, 0)
    item.update({
        "robot_reference": "x_min_y_min",
        "robot_depth": 0.05,
        "robot_depth_band": 0,
    })
    pallet = {
        **_pallet([item]),
        "robot_reference": "x_min_y_min",
        "depth_band_count": 4,
    }

    result = plan_execution_report({"pallets": [pallet]})

    centered = result["pallets"][0]["packed_items"][0]
    assert centered["robot_depth"] == 0.5
    assert centered["robot_depth_band"] == 2


def test_each_execution_item_records_stack_height_before_placement():
    base = _box("base", 0, 0, 0, height=100.0)
    top = _box("top", 0, 0, 100.0, height=80.0)

    result = plan_execution_report({"pallets": [_pallet([top, base])]})

    items = result["pallets"][0]["packed_items"]
    assert _ids(items) == ["base", "top"]
    assert [item["stack_height_before"] for item in items] == [0.0, 100.0]


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
    assert [carton["product_code"] for carton in cartons_by_seq] == [1, 2]
    assert all("stack_height_before" not in carton for carton in cartons_by_seq)
    assert {carton["layer_id"] for carton in cartons_by_seq} == {1}
    mapped = next(iter(result.plan_by_unique_id.values()))
    assert _ids(mapped["packed_items"]) == ["tall", "short"]
    assert all(
        "stack_height_before" not in item
        for item in mapped["packed_items"]
    )


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
    assert _ids(execution["pallets"][0]["packed_items"]) == ["tall", "short"]
    assert [
        item["stack_height_before"]
        for item in execution["pallets"][0]["packed_items"]
    ] == [0.0, 300.0]
    cases = json.loads(wcs_output.read_text(encoding="utf-8"))
    cartons = [
        carton
        for layer in cases[0]["layers"]
        for carton in layer["cartons"]
    ]
    assert [c["product_code"] for c in sorted(cartons, key=lambda c: c["seq"])] \
        == [1, 2]
    assert all("stack_height_before" not in carton for carton in cartons)
    map_output = wcs_output.with_name(wcs_output.stem + "_map.json")
    persisted_map = json.loads(map_output.read_text(encoding="utf-8"))
    unique_id = cases[0]["box_unique_id"]
    mapped_items = persisted_map[unique_id]["packed_items"]
    assert _ids(mapped_items) == ["tall", "short"]
    assert mapped_items[0]["position"] == {"x": 350.0, "y": 450.0, "z": 0.0}
    assert all("stack_height_before" not in item for item in mapped_items)
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
