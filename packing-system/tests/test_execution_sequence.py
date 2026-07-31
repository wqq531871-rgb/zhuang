"""Independent execution-order planning tests."""

import json
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

import pytest

import run_execution_planning
from src.execution import approach_geometry as approach_geometry_module
from src.execution import publisher as publisher_module
from src.execution import wcs_export as wcs_export_module
from src.execution.approach_geometry import (
    MovingRectPath,
    moving_path_blocked,
    preposition_descent_blocked,
    segment_intersects_rect,
)
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


def test_approach_geometry_segment_intersects_axis_aligned_rectangle():
    assert segment_intersects_rect((0, 0), (2, 2), (0.5, 1.5, 0.5, 1.5))
    assert not segment_intersects_rect((0, 0), (0, 2), (1, 2, 0.5, 1.5))


def test_approach_geometry_near_side_blocker_blocks_diagonal_sweep():
    path = MovingRectPath((0, 100, 0, 100), 35, 35, 0, 100)

    assert moving_path_blocked(path, (100, 200, 0, 100), 0, 100, 0)


def test_approach_geometry_exact_diagonal_corridor_excludes_swept_aabb_corner():
    path = MovingRectPath((0, 100, 0, 100), 35, 35, 0, 100)

    assert not moving_path_blocked(
        path, (130, 140, 0, 5), 0, 100, 0, tolerance=0
    )


def test_approach_geometry_blocker_outside_diagonal_corridor_is_safe():
    path = MovingRectPath((0, 100, 0, 100), 35, 35, 0, 100)

    assert not moving_path_blocked(path, (0, 100, 150, 250), 0, 100, 0)


def test_approach_geometry_blocker_wholly_below_moving_z_interval_is_safe():
    path = MovingRectPath((0, 100, 0, 100), 35, 35, 0, 100)

    assert not moving_path_blocked(path, (100, 200, 0, 100), -100, -1, 0)


def test_approach_geometry_preposition_descent_is_blocked_above_path_bottom():
    path = MovingRectPath((0, 100, 0, 100), 35, 35, 0, 100)

    assert preposition_descent_blocked(path, (100, 200, 100, 200), 25, 0)


def test_approach_geometry_preposition_contact_at_clearance_is_safe():
    path = MovingRectPath((0, 100, 0, 100), 35, 35, 0, 100)

    assert not preposition_descent_blocked(path, (145, 245, 35, 135), 25, 10)


def test_approach_geometry_final_only_far_side_contact_is_safe():
    path = MovingRectPath((0, 100, 0, 100), 35, 35, 0, 100)

    assert not moving_path_blocked(path, (-100, 0, 0, 100), 0, 100, 0)


def test_local_egress_blocks_a_protruding_upper_box_in_the_lift_zone():
    assert approach_geometry_module.local_egress_blocked(
        corridor_rect=(100, 200, 100, 200),
        lower_top=100,
        upper_rect=(0, 96, 0, 96),
        upper_z_min=100,
        upper_z_max=220,
        offset_x=35,
        offset_y=35,
        xy_clearance=5,
        height_tolerance=2,
    )


def test_local_egress_includes_the_configured_clearance_boundary():
    assert approach_geometry_module.local_egress_blocked(
        corridor_rect=(105, 205, 0, 100),
        lower_top=100,
        upper_rect=(0, 100, 0, 100),
        upper_z_min=100,
        upper_z_max=220,
        offset_x=0,
        offset_y=0,
        xy_clearance=5,
        height_tolerance=2,
    )


def test_local_egress_excludes_a_gap_beyond_configured_clearance():
    assert not approach_geometry_module.local_egress_blocked(
        corridor_rect=(105.01, 205.01, 0, 100),
        lower_top=100,
        upper_rect=(0, 100, 0, 100),
        upper_z_min=100,
        upper_z_max=220,
        offset_x=0,
        offset_y=0,
        xy_clearance=5,
        height_tolerance=2,
    )


def test_local_egress_allows_an_upper_box_at_the_same_surface_height():
    assert not approach_geometry_module.local_egress_blocked(
        corridor_rect=(100, 200, 100, 200),
        lower_top=100,
        upper_rect=(0, 96, 0, 96),
        upper_z_min=0,
        upper_z_max=102,
        offset_x=35,
        offset_y=35,
        xy_clearance=5,
        height_tolerance=2,
    )


def test_local_egress_allows_a_distant_protruding_upper_box():
    assert not approach_geometry_module.local_egress_blocked(
        corridor_rect=(100, 200, 100, 200),
        lower_top=100,
        upper_rect=(-500, -400, -500, -400),
        upper_z_min=100,
        upper_z_max=220,
        offset_x=35,
        offset_y=35,
        xy_clearance=5,
        height_tolerance=2,
    )


def test_local_egress_checks_the_directional_exit_sweep():
    assert not approach_geometry_module.local_egress_blocked(
        corridor_rect=(100, 200, 100, 200),
        lower_top=100,
        upper_rect=(210, 220, 210, 220),
        upper_z_min=100,
        upper_z_max=220,
        offset_x=0,
        offset_y=0,
        xy_clearance=5,
        height_tolerance=2,
    )
    assert approach_geometry_module.local_egress_blocked(
        corridor_rect=(100, 200, 100, 200),
        lower_top=100,
        upper_rect=(210, 220, 210, 220),
        upper_z_min=100,
        upper_z_max=220,
        offset_x=35,
        offset_y=35,
        xy_clearance=5,
        height_tolerance=2,
    )


def test_approach_geometry_path_rejects_nonfinite_translated_start():
    with pytest.raises(ValueError):
        MovingRectPath((1e308, 1.1e308, 0, 1), 1e308, 0, 0, 1)


def test_approach_geometry_segment_rejects_nonfinite_slab_delta():
    with pytest.raises(ValueError):
        segment_intersects_rect(
            (-1e308, 0), (1e308, 0), (-1, 1, -1, 1), tolerance=0
        )


def test_approach_geometry_segment_rejects_nonfinite_tolerance_expansion():
    with pytest.raises(ValueError):
        segment_intersects_rect(
            (0, 0), (1, 1), (1e308, 1.1e308, 0, 1), tolerance=1e308
        )


def test_approach_geometry_moving_sweep_rejects_nonfinite_minkowski_bounds():
    path = MovingRectPath((0, 1, 0, 1), 0, 0, 0, 1)

    with pytest.raises(ValueError):
        moving_path_blocked(
            path,
            (1e308, 1.1e308, 0, 1),
            0,
            1,
            1e308,
            tolerance=0,
        )


@pytest.mark.parametrize(
    "args",
    [
        ((0, 0, 0, 100), 35, 35, 0, 100),
        ((0, 100, 0, 100), -1, 35, 0, 100),
        ((0, 100, 0, 100), 35, float("nan"), 0, 100),
        ((0, 100, 0, 100), 35, 35, 100, 100),
    ],
)
def test_approach_geometry_path_rejects_invalid_geometry(args):
    with pytest.raises(ValueError):
        MovingRectPath(*args)


@pytest.mark.parametrize(
    "call",
    [
        lambda: segment_intersects_rect(
            (0, 0), (float("inf"), 1), (0, 1, 0, 1)
        ),
        lambda: segment_intersects_rect((0, 0), (1, 1), (0, 0, 0, 1)),
        lambda: segment_intersects_rect(
            (0, 0), (1, 1), (0, 1, 0, 1), tolerance=-1
        ),
        lambda: preposition_descent_blocked(
            MovingRectPath((0, 1, 0, 1), 1, 1, 0, 1),
            (0, 1, 0, 1),
            float("nan"),
            0,
        ),
        lambda: moving_path_blocked(
            MovingRectPath((0, 1, 0, 1), 1, 1, 0, 1),
            (0, 1, 0, 1),
            1,
            0,
            0,
        ),
        lambda: moving_path_blocked(
            MovingRectPath((0, 1, 0, 1), 1, 1, 0, 1),
            (0, 1, 0, 1),
            0,
            1,
            -1,
        ),
    ],
)
def test_approach_geometry_functions_reject_invalid_geometry(call):
    with pytest.raises(ValueError):
        call()


def test_support_boxes_precede_the_box_they_support():
    base = _box("base", 0, 0, 0)
    top = _box("top", 0, 0, 100)

    ordered = sequence_pallet_items(_pallet([top, base]))

    assert _ids(ordered) == ["base", "top"]


def test_approach_dependency_keeps_far_box_before_near_side_blocker():
    far = _box("far", 0, 0, 0)
    near = _box("near", 100, 0, 0)

    ordered = sequence_pallet_items(
        _pallet([near, far]),
        ExecutionSequenceConfig(
            path_gate_mode="hard",
            origin="x_max_y_min",
            preserve_open_direction=False,
        ),
    )

    assert _ids(ordered) == ["far", "near"]


def test_direct_approach_edges_use_exact_diagonal_corridor():
    far = _box("far", 0, 0, 0)
    near = _box("near", 100, 0, 0)
    outside = _box("outside", 130, 0, 0, length=10, width=5)
    items = [far, near, outside]
    edges = [set() for _item in items]
    indegree = [0 for _item in items]

    sequence_planner_module._add_approach_edges(
        items,
        ExecutionSequenceConfig(),
        edges,
        indegree,
        PALLET_DIMS,
    )

    assert 1 in edges[0]
    assert 0 not in edges[1]
    assert 2 not in edges[0]


def test_approach_edges_preserve_direct_support_dependency():
    base = _box("base", 0, 0, 0)
    top = _box("top", 0, 0, 100)
    items = [top, base]
    edges, indegree, _supports = sequence_planner_module._support_edges(
        items, 1e-6
    )

    sequence_planner_module._add_approach_edges(
        items,
        ExecutionSequenceConfig(),
        edges,
        indegree,
        PALLET_DIMS,
    )

    assert edges == [set(), {0}]


def test_approach_replay_rejects_manually_unsafe_prefix():
    far = _box("far", 0, 0, 0)
    near = _box("near", 100, 0, 0)

    with pytest.raises(
        ExecutionSequenceError,
        match="far.*near.*approach|far.*near.*pre-position",
    ):
        sequence_planner_module._assert_approach_replay_safe(
            [far, near],
            [1, 0],
            ExecutionSequenceConfig(),
            PALLET_DIMS,
        )


def test_clearance_edge_building_honors_the_sequence_deadline():
    items = [_box("A", 0, 0, 0), _box("B", 100, 0, 0)]
    edges = [set(), set()]
    indegree = [0, 0]

    with pytest.raises(
        sequence_planner_module._ExecutionSequenceDeadlineExceeded
    ):
        sequence_planner_module._add_clearance_edges(
            items,
            ExecutionSequenceConfig(),
            edges,
            indegree,
            deadline=sequence_planner_module.time.monotonic() - 1.0,
        )


def test_support_that_blocks_shifted_suction_preposition_creates_cycle():
    support = _box("support", 80, 80, 0)
    target = _box(
        "target",
        0,
        0,
        100,
        cup_rect={"x_min": 30, "x_max": 50, "y_min": 30, "y_max": 50},
    )

    with pytest.raises(ExecutionSequenceError, match="cyclic") as exc_info:
        sequence_pallet_items(
            _pallet([support, target]),
            ExecutionSequenceConfig(
                path_gate_mode="hard",
                suction_z_clearance_mm=150.0,
                approach_offset_x_mm=35.0,
                approach_offset_y_mm=35.0,
                approach_suction_xy_clearance_mm=2.0,
            ),
        )

    assert "support" in str(exc_info.value)
    assert "target" in str(exc_info.value)


def test_force_publish_falls_back_to_support_safe_wave_after_gate_cycle(
    caplog,
):
    support = _box("support", 80, 80, 0)
    target = _box(
        "target",
        0,
        0,
        100,
        cup_rect={"x_min": 30, "x_max": 50, "y_min": 30, "y_max": 50},
    )
    pallet = _pallet([support, target])
    pallet.update(
        {
            "sequence_status": "GEOMETRICALLY_FEASIBLE",
            "geometric_sequence_feasible": True,
        }
    )
    report = {"pallets": [pallet]}
    config = ExecutionSequenceConfig(
        path_gate_mode="hard",
        suction_z_clearance_mm=150.0,
        approach_offset_x_mm=35.0,
        approach_offset_y_mm=35.0,
        approach_suction_xy_clearance_mm=2.0,
        force_publish_on_gate_failure=True,
    )

    with caplog.at_level("WARNING", logger=sequence_planner_module.__name__):
        result = plan_execution_report(report, config=config)

    result_pallet = result["pallets"][0]
    items = result_pallet["packed_items"]
    assert _ids(items) == ["support", "target"]
    assert [item["seq"] for item in items] == [1, 2]
    assert [item["stack_height_before"] for item in items] == [0.0, 100.0]
    assert (
        result_pallet["sequence_status"]
        == "FORCED_EXECUTION_AFTER_GATE_FAILURE"
    )
    assert result_pallet["geometric_sequence_feasible"] is False
    assert "forced execution order" in caplog.text
    assert "cyclic execution dependencies" in caplog.text


def test_public_force_publish_keeps_support_and_relaxes_the_cyclic_path_edge(
    caplog,
):
    """The forced fallback drops the path edge, never the support edge.

    ``suction_z_clearance_mm=150`` makes the cup descent of ``upper`` conflict
    with its own support, so the hard graph holds a two-node cycle. Exactly one
    of the two edges can survive. ``adjacent-base`` sits on the retreat side of
    ``upper`` and is constrained by neither edge, so its position only reflects
    the ground-first wave preference; the retained approach-side egress edge is
    covered by the next test.
    """

    origin_base = _box("origin-base", 0, 0, 0, length=80, width=80)
    adjacent_base = _box("adjacent-base", 105, 0, 0)
    upper = _box(
        "upper",
        0,
        0,
        100,
        cup_rect={"x_min": 30, "x_max": 50, "y_min": 30, "y_max": 50},
    )
    report = {"pallets": [_pallet([upper, origin_base, adjacent_base])]}
    config = ExecutionSequenceConfig(
        path_gate_mode="hard",
        suction_z_clearance_mm=150.0,
        approach_offset_x_mm=35.0,
        approach_offset_y_mm=35.0,
        approach_suction_xy_clearance_mm=2.0,
        force_publish_on_gate_failure=True,
    )

    with caplog.at_level("WARNING", logger=sequence_planner_module.__name__):
        result = plan_execution_report(report, config=config)

    positions = {
        item["id"]: item["seq"]
        for item in result["pallets"][0]["packed_items"]
    }
    assert positions == {"origin-base": 1, "adjacent-base": 2, "upper": 3}
    assert (
        "forced execution relaxed 1 boundary/path safety dependencies"
        in caplog.text
    )
    assert "forced execution order" in caplog.text


def test_public_force_publish_retains_an_approach_side_height_egress_edge(
    caplog,
):
    adjacent_base = _box("adjacent-base", 0, 0, 0)
    column_base = _box("column-base", 105, 0, 0, length=80, width=80)
    upper = _box(
        "upper",
        105,
        0,
        100,
        length=80,
        width=80,
        cup_rect={"x_min": 130, "x_max": 150, "y_min": 30, "y_max": 50},
    )
    report = {"pallets": [_pallet([upper, column_base, adjacent_base])]}
    config = ExecutionSequenceConfig(
        path_gate_mode="hard",
        suction_z_clearance_mm=150.0,
        approach_offset_x_mm=35.0,
        approach_offset_y_mm=35.0,
        approach_suction_xy_clearance_mm=2.0,
        force_publish_on_gate_failure=True,
    )

    with caplog.at_level("WARNING", logger=sequence_planner_module.__name__):
        result = plan_execution_report(report, config=config)

    positions = {
        item["id"]: item["seq"]
        for item in result["pallets"][0]["packed_items"]
    }
    assert positions["column-base"] < positions["upper"]
    assert positions["adjacent-base"] < positions["upper"]


def test_forced_wave_retains_a_noncyclic_approach_predecessor():
    origin = _box("origin", 0, 0, 0, length=10, width=10, height=10)
    y_anchor = _box("y-anchor", 0, 200, 0, length=10, width=10, height=10)
    x_anchor = _box("x-anchor", 20, 800, 0, length=10, width=10, height=10)
    x_small = _box(
        "x-small",
        0,
        600,
        0,
        length=100,
        width=200,
        height=50,
        cup_rect={"x_min": 0, "x_max": 250, "y_min": 600, "y_max": 900},
    )
    x_large = _box(
        "x-large",
        200,
        450,
        0,
        length=100,
        width=200,
        height=100,
        cup_rect={
            "x_min": 200,
            "x_max": 450,
            "y_min": 450,
            "y_max": 750,
        },
    )

    ordered = sequence_planner_module._force_sequence_pallet_items(
        _pallet([origin, y_anchor, x_anchor, x_small, x_large]),
        ExecutionSequenceConfig(path_gate_mode="hard"),
    )

    positions = {item["id"]: item["seq"] for item in ordered}
    assert positions["x-small"] < positions["x-large"]


def test_safety_edge_selection_preserves_an_unschedulable_result():
    items = [{"id": "A"}, {"id": "B"}]
    edges = [set(), set()]
    blockers = [
        {"x-": set(), "x+": {1}, "y-": set(), "y+": set()},
        {"x-": set(), "x+": set(), "y-": set(), "y+": {0}},
    ]

    _edges, _indegree, ordered_indices, _relaxed = (
        sequence_planner_module._select_feasible_safety_edges(
            base_edges=edges,
            full_edges=edges,
            forward_keys=[(0,), (1,)],
            items=items,
            config=ExecutionSequenceConfig(),
            blockers=blockers,
            deadline=sequence_planner_module.time.monotonic() + 1.0,
        )
    )

    assert ordered_indices is None


def test_safety_edge_selection_keeps_the_primary_wave_seed():
    origin = _box("origin", 0, 0, 0)
    later_boundary = _box("later-boundary", 100, 0, 0)
    empty_blockers = [
        {"x-": set(), "x+": set(), "y-": set(), "y+": set()},
        {"x-": set(), "x+": set(), "y-": set(), "y+": set()},
    ]

    retained, _indegree, ordered_indices, relaxed = (
        sequence_planner_module._select_feasible_safety_edges(
            base_edges=[set(), set()],
            full_edges=[set(), {0}],
            forward_keys=[(0,), (1,)],
            items=[origin, later_boundary],
            config=ExecutionSequenceConfig(),
            blockers=empty_blockers,
            deadline=sequence_planner_module.time.monotonic() + 1.0,
            priority_safety_edges={(1, 0)},
        )
    )

    assert ordered_indices == [0, 1]
    assert retained == [set(), set()]
    assert relaxed == 1


def test_safety_edge_selection_keeps_the_nearest_feasible_wave_seed():
    origin_target = _box("origin-target", 0, 0, 0)
    origin_prerequisite = _box("origin-prerequisite", 100, 0, 0)
    later_boundary = _box("later-boundary", 200, 0, 0)
    empty_blockers = [
        {"x-": set(), "x+": set(), "y-": set(), "y+": set()}
        for _item in range(3)
    ]

    retained, _indegree, ordered_indices, relaxed = (
        sequence_planner_module._select_feasible_safety_edges(
            base_edges=[set(), {0}, set()],
            full_edges=[set(), {0}, {1}],
            forward_keys=[(0,), (1,), (2,)],
            items=[origin_target, origin_prerequisite, later_boundary],
            config=ExecutionSequenceConfig(),
            blockers=empty_blockers,
            deadline=sequence_planner_module.time.monotonic() + 1.0,
            priority_safety_edges={(2, 1)},
        )
    )

    assert ordered_indices == [1, 0, 2]
    assert retained == [set(), {0}, set()]
    assert relaxed == 1


def test_safety_edge_selection_can_reorder_after_the_primary_wave_seed():
    origin = _box("origin", 0, 0, 0)
    middle = _box("middle", 100, 0, 0)
    later_boundary = _box("later-boundary", 200, 0, 0)
    empty_blockers = [
        {"x-": set(), "x+": set(), "y-": set(), "y+": set()}
        for _item in range(3)
    ]

    retained, _indegree, ordered_indices, relaxed = (
        sequence_planner_module._select_feasible_safety_edges(
            base_edges=[set(), set(), set()],
            full_edges=[set(), set(), {1}],
            forward_keys=[(0,), (1,), (2,)],
            items=[origin, middle, later_boundary],
            config=ExecutionSequenceConfig(),
            blockers=empty_blockers,
            deadline=sequence_planner_module.time.monotonic() + 1.0,
            priority_safety_edges={(2, 1)},
        )
    )

    assert ordered_indices == [0, 2, 1]
    assert retained == [set(), set(), {1}]
    assert relaxed == 0


def test_x_min_clamp_edge_precedes_a_conflicting_wave_preference():
    x_min_target = _box("x-min-target", 0, 0, 0)
    x_plus_blocker = _box("x-plus-blocker", 100, 0, 0)
    empty_blockers = [
        {"x-": set(), "x+": set(), "y-": set(), "y+": set()},
        {"x-": set(), "x+": set(), "y-": set(), "y+": set()},
    ]

    retained, _indegree, ordered_indices, relaxed = (
        sequence_planner_module._select_feasible_safety_edges(
            base_edges=[set(), set()],
            full_edges=[{1}, {0}],
            forward_keys=[(0,), (1,)],
            items=[x_min_target, x_plus_blocker],
            config=ExecutionSequenceConfig(),
            blockers=empty_blockers,
            deadline=sequence_planner_module.time.monotonic() + 1.0,
        )
    )

    assert ordered_indices == [0, 1]
    assert retained == [{1}, set()]
    assert relaxed == 1


@pytest.mark.parametrize(
    "origin, target_position, blocker_position, expected_edge",
    [
        ("x_min_y_min", (0, 300), (100, 300), (0, 1)),
        ("x_min_y_min", (300, 0), (300, 100), (0, 1)),
        ("x_max_y_max", (900, 300), (800, 300), (0, 1)),
        ("x_max_y_max", (300, 900), (300, 800), (0, 1)),
    ],
)
def test_far_boundary_clamp_dependencies_follow_configured_origin(
    origin,
    target_position,
    blocker_position,
    expected_edge,
):
    target = _box("target", target_position[0], target_position[1], 0)
    blocker = _box(
        "blocker", blocker_position[0], blocker_position[1], 0
    )

    dependencies = sequence_planner_module._far_boundary_clamp_dependencies(
        [target, blocker],
        ExecutionSequenceConfig(origin=origin),
        PALLET_DIMS,
    )

    assert dependencies == {expected_edge}


@pytest.mark.parametrize("path_gate_mode", ["score_only", "hard"])
def test_planner_keeps_far_boundary_box_before_inward_neighbor(
    path_gate_mode,
):
    target = _box("target", 0, 0, 0)
    blocker = _box("blocker", 100, 0, 0)

    ordered = sequence_pallet_items(
        _pallet([blocker, target]),
        ExecutionSequenceConfig(
            path_gate_mode=path_gate_mode,
            approach_offset_x_mm=0.0,
            approach_offset_y_mm=0.0,
            approach_z_clearance_mm=0.0,
            preserve_open_direction=False,
            scan_column_tolerance_mm=200.0,
        ),
    )

    assert _ids(ordered) == ["target", "blocker"]


@pytest.mark.parametrize("path_gate_mode", ["score_only", "hard"])
def test_forced_planner_keeps_far_boundary_box_before_inward_neighbor(
    path_gate_mode,
):
    target = _box("target", 0, 0, 0)
    blocker = _box("blocker", 100, 0, 0)

    ordered = sequence_planner_module._force_sequence_pallet_items(
        _pallet([blocker, target]),
        ExecutionSequenceConfig(
            path_gate_mode=path_gate_mode,
            approach_offset_x_mm=0.0,
            approach_offset_y_mm=0.0,
            approach_z_clearance_mm=0.0,
            preserve_open_direction=False,
            scan_column_tolerance_mm=200.0,
        ),
    )

    assert _ids(ordered) == ["target", "blocker"]


def test_boundary_clamp_diagnostics_reports_a_reversed_dependency():
    target = _box("target", 0, 0, 0)
    blocker = _box("blocker", 100, 0, 0)

    diagnostics = sequence_planner_module._boundary_clamp_diagnostics(
        [target, blocker],
        [blocker, target],
        ExecutionSequenceConfig(),
    )

    assert diagnostics == {
        "boundary_clamp_relaxed_count": 1,
        "boundary_clamp_relaxations": [
            {
                "target_box_id": "target",
                "blocker_box_id": "blocker",
            }
        ],
    }


def test_forced_wave_keeps_an_upper_target_out_of_a_three_sided_pocket():
    target = _box("target", 0, 300, 100, width=200)
    far_base = _box("far-base", 0, 100, 0, width=200, height=200)
    side_base = _box("side-base", 100, 200, 0, width=200, height=200)
    support = _box("support", 0, 300, 0, width=200)
    pocket_wall = _box(
        "pocket-wall", 0, 500, 0, width=200, height=200
    )
    prerequisite = _box(
        "prerequisite", 100, 495, 0, width=200
    )
    items = [
        target,
        far_base,
        side_base,
        support,
        pocket_wall,
        prerequisite,
    ]
    config = ExecutionSequenceConfig(
        path_gate_mode="hard",
        preserve_open_direction=True,
        force_publish_on_gate_failure=True,
        max_occupied_directions=2,
        side_neighbor_clearance_mm=5.0,
    )

    ordered = sequence_planner_module._force_sequence_pallet_items(
        _pallet(items), config
    )

    positions = {item["id"]: item["seq"] for item in ordered}
    assert positions["target"] < positions["side-base"]
    assert positions["target"] < positions["pocket-wall"]

    blockers = sequence_planner_module._direction_blocker_map(
        [sequence_planner_module._physical_geometry(item) for item in items],
        config,
    )
    index_by_id = {item["id"]: idx for idx, item in enumerate(items)}
    ordered_indices = [index_by_id[item["id"]] for item in ordered]
    sequence_planner_module._assert_open_direction_replay(
        items, ordered_indices, config, blockers
    )


def test_force_publish_does_not_bypass_duplicate_box_ids():
    report = {
        "pallets": [_pallet([_box("same", 0, 0, 0), _box("same", 100, 0, 0)])]
    }

    with pytest.raises(ExecutionSequenceError, match="present and unique"):
        plan_execution_report(
            report,
            config=ExecutionSequenceConfig(
                force_publish_on_gate_failure=True,
            ),
        )


def test_force_publish_does_not_bypass_pallet_bounds():
    report = {"pallets": [_pallet([_box("outside", 950, 0, 0)])]}

    with pytest.raises(ExecutionSequenceError, match="outside pallet bounds"):
        plan_execution_report(
            report,
            config=ExecutionSequenceConfig(
                force_publish_on_gate_failure=True,
            ),
        )


@pytest.mark.parametrize(
    "mutate_suction, error_match",
    [
        (
            lambda item: [
                item.pop(name)
                for name in (
                    "suction_rect_x_min",
                    "suction_rect_x_max",
                    "suction_rect_y_min",
                    "suction_rect_y_max",
                )
            ],
            "missing suction rectangle",
        ),
        (
            lambda item: item.pop("suction_rect_y_max"),
            "missing suction rectangle",
        ),
        (
            lambda item: item.update(
                {"suction_rect_x_min": float("nan")}
            ),
            "suction rectangle values must be finite",
        ),
        (
            lambda item: item.update(
                {"suction_rect_x_max": item["suction_rect_x_min"]}
            ),
            "invalid suction rectangle",
        ),
    ],
    ids=("missing", "partial", "non_finite", "degenerate"),
)
def test_force_publish_does_not_bypass_required_suction_pose(
    mutate_suction,
    error_match,
):
    item = _box("flat", 0, 0, 0)
    mutate_suction(item)
    report = {"pallets": [_pallet([item])]}

    with pytest.raises(ExecutionSequenceError, match=error_match):
        plan_execution_report(
            report,
            config=ExecutionSequenceConfig(
                require_suction_pose=True,
                force_publish_on_gate_failure=True,
            ),
        )


def test_approach_z_clearance_passes_above_low_blocker_without_suction_pose():
    far = _box("far", 0, 0, 0)
    low_near = _box("low-near", 100, 0, 0, height=20)
    suction_names = (
        "suction_rect_x_min",
        "suction_rect_x_max",
        "suction_rect_y_min",
        "suction_rect_y_max",
    )
    for item in (far, low_near):
        for name in suction_names:
            item.pop(name)

    ordered = sequence_pallet_items(
        _pallet([far, low_near]),
        ExecutionSequenceConfig(
            origin="x_max_y_min",
            approach_z_clearance_mm=20.0,
            require_suction_pose=False,
            preserve_open_direction=False,
        ),
    )

    assert _ids(ordered) == ["low-near", "far"]


def test_final_box_descent_adds_edge_and_replay_rejects_unsafe_prefix():
    blocker = _box("blocker", 0, 0, 0, length=99, height=20)
    target = _box("target", 100, 0, 0)
    suction_names = (
        "suction_rect_x_min",
        "suction_rect_x_max",
        "suction_rect_y_min",
        "suction_rect_y_max",
    )
    for item in (blocker, target):
        for name in suction_names:
            item.pop(name)
    items = [blocker, target]
    config = ExecutionSequenceConfig(
        approach_z_clearance_mm=20.0,
        approach_box_xy_clearance_mm=2.0,
        require_suction_pose=False,
        preserve_open_direction=False,
    )
    edges = [set() for _item in items]
    indegree = [0 for _item in items]

    sequence_planner_module._add_approach_edges(
        items, config, edges, indegree, PALLET_DIMS
    )

    assert 0 in edges[1]
    with pytest.raises(ExecutionSequenceError, match="box final descent"):
        sequence_planner_module._assert_approach_replay_safe(
            items, [0, 1], config, PALLET_DIMS
        )


def test_final_box_descent_cycle_is_rejected_by_public_planner():
    blocker = _box("blocker", 0, 0, 0, length=99, height=20)
    target = _box("target", 100, 0, 0)
    for item in (blocker, target):
        for name in (
            "suction_rect_x_min",
            "suction_rect_x_max",
            "suction_rect_y_min",
            "suction_rect_y_max",
        ):
            item.pop(name)

    with pytest.raises(ExecutionSequenceError, match="cyclic"):
        sequence_pallet_items(
            _pallet([blocker, target]),
            ExecutionSequenceConfig(
                path_gate_mode="hard",
                approach_z_clearance_mm=20.0,
                approach_box_xy_clearance_mm=2.0,
                require_suction_pose=False,
                preserve_open_direction=False,
            ),
        )


def test_score_only_path_gate_records_risk_without_reordering():
    blocker = _box("blocker", 0, 0, 0, length=99, height=20)
    target = _box("target", 100, 0, 0)
    for item in (blocker, target):
        for name in (
            "suction_rect_x_min",
            "suction_rect_x_max",
            "suction_rect_y_min",
            "suction_rect_y_max",
        ):
            item.pop(name)

    result = plan_execution_report(
        {"pallets": [_pallet([target, blocker])]},
        ExecutionSequenceConfig(
            path_gate_mode="score_only",
            approach_z_clearance_mm=20.0,
            approach_box_xy_clearance_mm=2.0,
            require_suction_pose=False,
            preserve_open_direction=False,
        ),
    )

    pallet = result["pallets"][0]
    assert _ids(pallet["packed_items"]) == ["blocker", "target"]
    assert pallet["execution_sequence_diagnostics"] == {
        "path_gate_mode": "score_only",
        "soft_path_risk_count": 1,
        "soft_path_risks": [
            {
                "target_box_id": "target",
                "blocker_box_id": "blocker",
                "target_seq": 2,
                "phase": "box final descent",
            }
        ],
        "boundary_clamp_relaxed_count": 0,
        "boundary_clamp_relaxations": [],
        "pocket_violation_count": 0,
        "pocket_violations": [],
    }


@pytest.mark.parametrize(
    "diagnostic_name, error_field",
    [
        ("_collect_path_risks", "soft_path_evaluation_error"),
        ("_boundary_clamp_diagnostics", "boundary_clamp_evaluation_error"),
        ("_pocket_diagnostics", "pocket_evaluation_error"),
    ],
)
def test_diagnostic_failure_does_not_block_execution_publish(
    monkeypatch, diagnostic_name, error_field
):
    def reject_diagnostics(*_args, **_kwargs):
        raise ExecutionSequenceError("diagnostic sentinel")

    monkeypatch.setattr(
        sequence_planner_module,
        diagnostic_name,
        reject_diagnostics,
    )

    result = plan_execution_report(
        {"pallets": [_pallet([_box("only", 0, 0, 0)])]},
        ExecutionSequenceConfig(preserve_open_direction=False),
    )

    diagnostics = result["pallets"][0]["execution_sequence_diagnostics"]
    assert diagnostics["soft_path_risk_count"] == 0
    assert diagnostics["boundary_clamp_relaxed_count"] == 0
    assert diagnostics["boundary_clamp_relaxations"] == []
    assert diagnostics[error_field] == "diagnostic sentinel"
    assert diagnostics["pocket_violation_count"] == 0
    assert diagnostics["pocket_violations"] == []
    wcs_result = wcs_export_module.execution_report_to_plan_result(result)
    assert len(wcs_result.cases) == 1
    assert all(
        "execution_sequence_diagnostics" not in pallet
        for pallet in wcs_result.plan_by_unique_id.values()
    )


def test_score_only_reuses_the_order_returned_by_safety_selection(monkeypatch):
    def selected_order(*_args, **_kwargs):
        return [set()], [0], [0], 0

    def reject_duplicate_schedule(*_args, **_kwargs):
        raise sequence_planner_module._ExecutionSequenceDeadlineExceeded

    monkeypatch.setattr(
        sequence_planner_module,
        "_select_feasible_safety_edges",
        selected_order,
    )
    monkeypatch.setattr(
        sequence_planner_module,
        "_stable_forward_order",
        reject_duplicate_schedule,
    )

    ordered = sequence_pallet_items(
        _pallet([_box("only", 0, 0, 0)]),
        ExecutionSequenceConfig(
            path_gate_mode="score_only",
            preserve_open_direction=False,
        ),
    )

    assert _ids(ordered) == ["only"]


def test_centered_layout_gate_calls_approach_replay(monkeypatch):
    item = _box("centered", 450, 450, 0)

    def reject_approach_replay(*_args, **_kwargs):
        raise ExecutionSequenceError("approach replay sentinel")

    monkeypatch.setattr(
        sequence_planner_module,
        "_assert_approach_replay_safe",
        reject_approach_replay,
    )

    with pytest.raises(ExecutionSequenceError, match="approach replay sentinel"):
        sequence_planner_module._assert_final_execution_layout(
            [item], ExecutionSequenceConfig()
        )


def test_approach_edge_scan_checks_deadline_during_pair_loops(monkeypatch):
    items = [
        _box("left", 0, 0, 0),
        _box("middle", 300, 0, 0),
        _box("right", 600, 0, 0),
    ]
    checks = []
    monkeypatch.setattr(
        sequence_planner_module,
        "_check_deadline",
        lambda deadline: checks.append(deadline),
    )

    sequence_planner_module._add_approach_edges(
        items,
        ExecutionSequenceConfig(),
        [set() for _item in items],
        [0 for _item in items],
        PALLET_DIMS,
        deadline=123.0,
    )

    expected_minimum = 2 * len(items) + len(items) + len(items) ** 2
    assert len(checks) >= expected_minimum
    assert set(checks) == {123.0}


def test_approach_replay_checks_deadline_during_pair_loops(monkeypatch):
    items = [
        _box("left", 0, 0, 0),
        _box("middle", 300, 0, 0),
        _box("right", 600, 0, 0),
    ]
    checks = []
    monkeypatch.setattr(
        sequence_planner_module,
        "_check_deadline",
        lambda deadline: checks.append(deadline),
    )

    sequence_planner_module._assert_approach_replay_safe(
        items,
        [0, 1, 2],
        ExecutionSequenceConfig(),
        PALLET_DIMS,
        deadline=456.0,
    )

    pair_count = sum(range(len(items)))
    expected_minimum = 2 * len(items) + len(items) + pair_count
    assert len(checks) >= expected_minimum
    assert set(checks) == {456.0}


def test_final_layout_forwards_deadline_to_approach_gates(monkeypatch):
    calls = []

    def record_edges(
        _items,
        _config,
        _edges,
        _indegree,
        _pallet_dims=None,
        deadline=None,
    ):
        calls.append(("edges", deadline))

    def record_replay(
        _items,
        _ordered_indices,
        _config,
        _pallet_dims=None,
        deadline=None,
    ):
        calls.append(("replay", deadline))

    monkeypatch.setattr(
        sequence_planner_module, "_add_approach_edges", record_edges
    )
    monkeypatch.setattr(
        sequence_planner_module,
        "_assert_approach_replay_safe",
        record_replay,
    )

    deadline = sequence_planner_module.time.monotonic() + 789.0
    sequence_planner_module._assert_final_execution_layout(
        [_box("centered", 450, 450, 0)],
        ExecutionSequenceConfig(preserve_open_direction=False),
        deadline=deadline,
    )

    assert calls == [("edges", deadline), ("replay", deadline)]


def test_directed_wave_origin_progress_precedes_resulting_top_height():
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
        ExecutionSequenceConfig(
            origin=origin,
            approach_offset_x_mm=0.0,
            approach_offset_y_mm=0.0,
            approach_suction_xy_clearance_mm=0.0,
        ),
    )

    assert _ids(ordered) == expected


@pytest.mark.parametrize("preserve_open_direction", [True, False])
def test_directed_wave_scans_x_ranks_then_y(preserve_open_direction):
    boxes = [
        _box("c10", 140, 0, 0, length=101, width=41, height=61),
        _box("c01", 0, 160, 0, length=59, width=73, height=61),
        _box("c00", 0, 0, 0, length=83, width=47, height=61),
    ]

    ordered = sequence_pallet_items(
        _pallet(boxes),
        ExecutionSequenceConfig(
            preserve_open_direction=preserve_open_direction,
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
        ),
    )

    assert _ids(ordered) == [
        "near_origin",
        "far_shifted_left",
        "next_column",
    ]


def test_directed_wave_keeps_input_order_at_same_coordinate_ranks():
    boxes = [
        _box("x4_first", 104.0, 100.0, 0, length=1.0, width=1.0),
        _box("x0_second", 100.0, 100.0, 0, length=1.0, width=1.0),
    ]

    ordered = sequence_pallet_items(
        _pallet(boxes),
        ExecutionSequenceConfig(
            preserve_open_direction=False,
            scan_column_tolerance_mm=5.0,
        ),
    )

    assert _ids(ordered) == ["x4_first", "x0_second"]


def test_directed_wave_coordinate_ranks_are_global_across_support_tiers():
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
            max_occupied_directions=2,
            scan_column_tolerance_mm=5.0,
        ),
    )

    assert _ids(ordered) == [
        "support",
        "same_column_y200",
        "same_column_y0",
    ]


def test_hard_dependency_promotes_the_far_targets_prerequisite(caplog):
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
                ExecutionSequenceConfig(path_gate_mode="hard"),
        )

    assert _ids(ordered) == ["C", "A", "B"]
    assert "execution scan deviation" in caplog.text
    assert "expected='A'" in caplog.text
    assert "selected='C'" in caplog.text
    assert "reason=hard_dependency" in caplog.text
    assert "reason=open_direction" not in caplog.text
    deviation_warnings = [
        record.getMessage()
        for record in caplog.records
        if "execution scan deviation" in record.getMessage()
    ]
    assert len(deviation_warnings) == 1
    assert "count=1" in deviation_warnings[0]


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


def test_hard_prerequisite_inherits_the_far_targets_scan_priority():
    items = [
        {"id": "far-target"},
        {"id": "unrelated-near"},
        {"id": "far-prerequisite"},
    ]
    edges = [set(), set(), {0}]

    ordered_indices = sequence_planner_module._stable_forward_order(
        items=items,
        edges=edges,
        config=ExecutionSequenceConfig(preserve_open_direction=False),
        forward_keys=[(0,), (1,), (2,)],
        blockers=None,
        deadline=sequence_planner_module.time.monotonic() + 1.0,
        pallet_id="P-inherited-priority",
    )

    assert ordered_indices == [2, 0, 1]


def test_forward_scheduler_skips_locally_safe_candidate_when_residual_is_blocked(
    caplog,
):
    items = [{"id": "A"}, {"id": "B"}, {"id": "C"}]
    edges = [set(), {2}, set()]
    blockers = [
        {"x-": set(), "x+": set(), "y-": set(), "y+": set()},
        {"x-": set(), "x+": {0}, "y-": set(), "y+": set()},
        {"x-": set(), "x+": set(), "y-": set(), "y+": set()},
    ]

    with caplog.at_level("WARNING", logger=sequence_planner_module.__name__):
        ordered_indices = sequence_planner_module._stable_forward_order(
            items=items,
            edges=edges,
            config=ExecutionSequenceConfig(),
            forward_keys=[(0,), (1,), (2,)],
            blockers=blockers,
            deadline=sequence_planner_module.time.monotonic() + 1.0,
            pallet_id="P-lookahead",
        )

    assert ordered_indices == [1, 0, 2]
    assert "expected='A'" in caplog.text
    assert "selected='B'" in caplog.text
    assert "reason=open_direction" in caplog.text
    assert "lookahead=true" in caplog.text


def test_open_direction_scan_deviation_is_logged_with_specific_reason(caplog):
    boxes = [
        _box("center", 400, 400, 0),
        _box("left", 300, 400, 0),
        _box("below", 350, 300, 0),
        _box("above", 350, 500, 0),
    ]

    with caplog.at_level("WARNING", logger=sequence_planner_module.__name__):
        ordered = sequence_pallet_items(
            _pallet(boxes),
            ExecutionSequenceConfig(
                approach_offset_x_mm=0.0,
                approach_offset_y_mm=0.0,
                approach_suction_xy_clearance_mm=0.0,
                preserve_open_direction=True,
                max_occupied_directions=2,
            ),
        )

    assert _ids(ordered) == ["below", "left", "center", "above"]
    assert "box='left' after='below'" in caplog.text
    assert "box='above' after='center'" in caplog.text
    assert "reason=open_direction" in caplog.text


def test_disabling_open_direction_keeps_scan_order_without_the_gate():
    boxes = [
        _box("center", 400, 400, 0),
        _box("left", 300, 400, 0),
        _box("below", 350, 300, 0),
        _box("above", 350, 500, 0),
    ]

    ordered = sequence_pallet_items(
        _pallet(boxes),
        ExecutionSequenceConfig(
            approach_offset_x_mm=0.0,
            approach_offset_y_mm=0.0,
            approach_suction_xy_clearance_mm=0.0,
            preserve_open_direction=False,
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


def _single_blocker_map(occupied):
    return [
        {"x-": set(), "x+": set(), "y-": set(), "y+": set()},
        {
            direction: {0} if direction in occupied else set()
            for direction in ("x-", "x+", "y-", "y+")
        },
    ]


@pytest.mark.parametrize(
    "occupied",
    [
        {"x-", "x+"},
        {"y-", "y+"},
        {"x-", "x+", "y-"},
    ],
    ids=("opposite-x", "opposite-y", "three-sided"),
)
def test_legacy_open_corner_replay_rejects_non_corner_patterns(occupied):
    with pytest.raises(ExecutionSequenceError, match="scheduled into a pocket"):
        sequence_planner_module._assert_open_direction_replay(
            [{"id": "blocker"}, {"id": "target"}],
            [0, 1],
            ExecutionSequenceConfig(
                pocket_rule="open_corner", max_occupied_directions=2
            ),
            _single_blocker_map(occupied),
        )


def test_legacy_open_corner_replay_accepts_two_adjacent_sides():
    sequence_planner_module._assert_open_direction_replay(
        [{"id": "blocker"}, {"id": "target"}],
        [0, 1],
        ExecutionSequenceConfig(
            pocket_rule="open_corner", max_occupied_directions=2
        ),
        _single_blocker_map({"x-", "y-"}),
    )


@pytest.mark.parametrize(
    "occupied",
    [
        {"x+"},
        {"y+"},
        {"x+", "y+"},
        {"x-", "y+"},
        {"x+", "y-"},
    ],
    ids=("x-plus", "y-plus", "both-approach", "x-minus-and-y-plus",
         "x-plus-and-y-minus"),
)
def test_directional_replay_rejects_any_occupied_approach_direction(occupied):
    with pytest.raises(ExecutionSequenceError, match="scheduled into a pocket"):
        sequence_planner_module._assert_open_direction_replay(
            [{"id": "blocker"}, {"id": "target"}],
            [0, 1],
            ExecutionSequenceConfig(),
            _single_blocker_map(occupied),
        )


@pytest.mark.parametrize(
    "occupied",
    [set(), {"x-"}, {"y-"}, {"x-", "y-"}],
    ids=("free", "x-minus", "y-minus", "both-retreat"),
)
def test_directional_replay_accepts_a_fully_occupied_retreat_corner(occupied):
    sequence_planner_module._assert_open_direction_replay(
        [{"id": "blocker"}, {"id": "target"}],
        [0, 1],
        ExecutionSequenceConfig(),
        _single_blocker_map(occupied),
    )


@pytest.mark.parametrize(
    ("origin", "approach"),
    [
        ("x_min_y_min", {"x+", "y+"}),
        ("x_min_y_max", {"x+", "y-"}),
        ("x_max_y_min", {"x-", "y+"}),
        ("x_max_y_max", {"x-", "y-"}),
    ],
)
def test_approach_directions_follow_the_execution_origin(origin, approach):
    config = ExecutionSequenceConfig(origin=origin)

    assert sequence_planner_module._approach_directions(config) == approach
    assert sequence_planner_module._is_pocket_free(
        {"x-", "x+", "y-", "y+"} - approach, config
    )
    for direction in approach:
        assert not sequence_planner_module._is_pocket_free(
            {direction}, config
        )


def test_pocket_rule_rejects_an_unknown_value():
    with pytest.raises(ValueError, match="pocket_rule must be one of"):
        ExecutionSequenceConfig(pocket_rule="whatever")


def test_lower_side_boxes_do_not_enclose_a_taller_box():
    below = _box("below", 100, 200, 0, height=100)
    left = _box("left", 0, 300, 0, height=100)
    right = _box("right", 200, 100, 0, width=300, height=100)
    center = _box("center", 100, 300, 0, height=200)

    ordered = sequence_pallet_items(
        _pallet([center, left, right, below]),
        ExecutionSequenceConfig(
            approach_offset_x_mm=0.0,
            approach_offset_y_mm=0.0,
            approach_suction_xy_clearance_mm=0.0,
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


def test_lower_side_boxes_occupy_all_directions_above_target_bottom():
    left = _box("left", 0, 100, 0, height=100)
    right = _box("right", 200, 100, 0, height=100)
    below = _box("below", 100, 0, 0, height=100)
    above = _box("above", 100, 200, 0, height=100)
    target = _box("target", 100, 100, 0, height=200)
    items = [left, right, below, above, target]
    config = ExecutionSequenceConfig(
        max_occupied_directions=2,
        side_neighbor_clearance_mm=5.0,
        side_height_tolerance_mm=2.0,
    )

    blockers = sequence_planner_module._direction_blocker_map(
        [sequence_planner_module._physical_geometry(item) for item in items],
        config,
    )
    occupied = sequence_planner_module._occupied_from_blocker_map(
        4,
        {0, 1, 2, 3},
        blockers,
    )

    assert occupied == {"x-", "x+", "y-", "y+"}
    assert not sequence_planner_module._is_pocket_free(
        occupied,
        config,
    )


def test_coordinate_ranks_cluster_each_axis_from_cluster_anchor():
    geometry = [
        (0.0, 0.0, 0.0, 1.0, 1.0, 100.0),
        (4.0, 4.0, 0.0, 1.0, 1.0, 100.0),
        (9.0, 9.0, 0.0, 1.0, 1.0, 100.0),
    ]

    ranks = sequence_planner_module._coordinate_ranks(
        geometry,
        ExecutionSequenceConfig(scan_column_tolerance_mm=5.0),
        PALLET_DIMS,
    )

    assert ranks == [(0, 0), (0, 0), (1, 1)]


def test_directed_wave_keys_rank_support_tiers_behind_the_ground_ring():
    geometry = [
        (100.0, 100.0, 0.0, 100.0, 100.0, 100.0),
        (0.0, 100.0, 0.0, 100.0, 100.0, 100.0),
        (100.0, 0.0, 0.0, 100.0, 100.0, 100.0),
        (0.0, 0.0, 100.0, 100.0, 100.0, 100.0),
        (0.0, 0.0, 0.0, 100.0, 100.0, 100.0),
    ]
    supports = [set(), set(), set(), {4}, set()]

    keys = sequence_planner_module._directed_wave_keys(
        geometry,
        supports,
        ExecutionSequenceConfig(),
        PALLET_DIMS,
    )

    assert keys == [
        (1, 0, 1, 1, 1, 0),
        (1, 0, 1, 0, 1, 1),
        (1, 0, 1, 1, 0, 2),
        (2, 1, 0, 0, 0, 3),
        (0, 0, 0, 0, 0, 4),
    ]
    assert sorted(range(len(keys)), key=keys.__getitem__) == [4, 1, 2, 0, 3]


def test_directed_wave_keeps_the_ground_front_two_rings_ahead():
    """A supported box waits for the ground ring two steps past its own."""

    geometry = [
        (0.0, 0.0, 0.0, 100.0, 100.0, 100.0),
        (0.0, 0.0, 100.0, 100.0, 100.0, 100.0),
        (100.0, 0.0, 0.0, 100.0, 100.0, 100.0),
        (200.0, 0.0, 0.0, 100.0, 100.0, 100.0),
        (300.0, 0.0, 0.0, 100.0, 100.0, 100.0),
    ]
    supports = [set(), {0}, set(), set(), set()]

    keys = sequence_planner_module._directed_wave_keys(
        geometry,
        supports,
        ExecutionSequenceConfig(),
        PALLET_DIMS,
    )

    origin_upper_wave = keys[1][0]
    ground_waves = {index: keys[index][0] for index in (0, 2, 3, 4)}
    assert ground_waves == {0: 0, 2: 1, 3: 2, 4: 3}
    assert origin_upper_wave == 2
    assert sorted(range(len(keys)), key=keys.__getitem__) == [0, 2, 3, 1, 4]


def test_support_tiers_handle_a_deep_reverse_indexed_chain_iteratively():
    item_count = 1200
    supports = [{idx + 1} for idx in range(item_count - 1)] + [set()]

    tiers = sequence_planner_module._support_tiers(supports)

    assert tiers[-1] == 0
    assert tiers[0] == item_count - 1
    assert all(
        tiers[idx] == tiers[idx + 1] + 1
        for idx in range(item_count - 1)
    )


@pytest.mark.parametrize(
    "supports, message",
    [
        ([{1}], "support dependency index .* out of range"),
        ([{1}, {0}], "support dependency graph contains a cycle"),
    ],
)
def test_support_tiers_reject_malformed_dependency_graphs(supports, message):
    with pytest.raises(ExecutionSequenceError, match=message):
        sequence_planner_module._support_tiers(supports)


def test_directed_wave_expands_shuffled_irregular_grid_by_square_rings():
    coordinates = [
        (215.0, 97.0),
        (0.0, 211.0),
        (103.0, 0.0),
        (215.0, 211.0),
        (0.0, 0.0),
        (103.0, 211.0),
        (0.0, 97.0),
        (215.0, 0.0),
        (103.0, 97.0),
    ]
    geometry = [
        (x, y, 0.0, 40.0 + idx, 50.0 + idx, 100.0)
        for idx, (x, y) in enumerate(coordinates)
    ]

    keys = sequence_planner_module._directed_wave_keys(
        geometry,
        [set() for _entry in geometry],
        ExecutionSequenceConfig(scan_column_tolerance_mm=5.0),
        PALLET_DIMS,
    )

    ordered_indices = sorted(range(9), key=keys.__getitem__)

    assert [coordinates[idx] for idx in ordered_indices] == [
        (0.0, 0.0),
        (0.0, 97.0),
        (103.0, 0.0),
        (103.0, 97.0),
        (0.0, 211.0),
        (103.0, 211.0),
        (215.0, 0.0),
        (215.0, 97.0),
        (215.0, 211.0),
    ]


@pytest.mark.parametrize(
    "origin, expected",
    [
        (
            "x_min_y_min",
            [(0.0, 0.0), (0.0, 100.0), (100.0, 0.0), (100.0, 100.0)],
        ),
        (
            "x_max_y_max",
            [(100.0, 100.0), (100.0, 0.0), (0.0, 100.0), (0.0, 0.0)],
        ),
    ],
)
def test_directed_wave_reverses_progress_from_configured_origin(origin, expected):
    coordinates = [
        (100.0, 0.0),
        (0.0, 100.0),
        (0.0, 0.0),
        (100.0, 100.0),
    ]
    geometry = [
        (x, y, 0.0, 100.0, 100.0, 100.0)
        for x, y in coordinates
    ]

    keys = sequence_planner_module._directed_wave_keys(
        geometry,
        [set() for _entry in geometry],
        ExecutionSequenceConfig(origin=origin),
        PALLET_DIMS,
    )

    assert [
        coordinates[idx]
        for idx in sorted(range(len(geometry)), key=keys.__getitem__)
    ] == expected


def test_coordinate_ranking_checks_deadline_through_progress_and_axis_loops(
    monkeypatch,
):
    checks = []
    monkeypatch.setattr(
        sequence_planner_module,
        "_check_deadline",
        lambda deadline: checks.append(deadline),
    )
    geometry = [
        (0.0, 0.0, 0.0, 100.0, 100.0, 100.0),
        (100.0, 100.0, 0.0, 100.0, 100.0, 100.0),
    ]

    sequence_planner_module._coordinate_ranks(
        geometry,
        ExecutionSequenceConfig(),
        PALLET_DIMS,
        deadline=123.0,
    )

    assert len(checks) >= len(geometry) * 3
    assert set(checks) == {123.0}


FIELD_PALLET_DIMS = {"length": 1440.0, "width": 2240.0, "height": 720.0}


def _field_box(box_id, x, y, z, length, width, height):
    """Build a box carrying the delivered 600x800 cup anchored at x_min_y_min."""

    item = _box(
        box_id,
        x,
        y,
        z,
        length=length,
        width=width,
        height=height,
        cup_rect={
            "x_min": x,
            "x_max": x + 600.0,
            "y_min": y,
            "y_max": y + 800.0,
        },
    )
    item["pallet_dims"] = deepcopy(FIELD_PALLET_DIMS)
    item["suction_orientation"] = "cup_600x_800y"
    return item


def _field_pocket_pallet():
    """Reproduce the pallet-11 prefix that used to descend into pockets."""

    return _pallet([
        _field_box("74", 0.0, 6.5, 0.0, 350.0, 265.0, 120.0),
        _field_box("75", 0.0, 6.5, 120.0, 350.0, 265.0, 120.0),
        _field_box("665", 0.0, 271.5, 0.0, 350.0, 530.0, 240.0),
        _field_box("168", 0.0, 801.5, 0.0, 350.0, 530.0, 120.0),
        _field_box("169", 0.0, 801.5, 120.0, 350.0, 530.0, 120.0),
        _field_box("635", 0.0, 1331.5, 0.0, 350.0, 530.0, 240.0),
        _field_box("644", 350.0, 1.5, 0.0, 350.0, 530.0, 240.0),
        _field_box("647", 350.0, 531.5, 0.0, 350.0, 530.0, 240.0),
        _field_box("62", 350.0, 1061.5, 0.0, 350.0, 265.0, 120.0),
        _field_box("82", 350.0, 1326.5, 0.0, 350.0, 530.0, 120.0),
    ])


FIELD_GRID_X = (17.0, 369.0, 721.0, 1073.0)
FIELD_GRID_Y = (54.0, 588.0, 1122.0, 1656.0)


def _field_grid_pallet():
    """Reproduce pallet 1: a 4x4 ground grid plus the origin column's top box."""

    items = [
        _field_box(
            "g%d%d" % (x_rank, y_rank), x, y, 0.0, 350.0, 530.0, 480.0
        )
        for x_rank, x in enumerate(FIELD_GRID_X)
        for y_rank, y in enumerate(FIELD_GRID_Y)
    ]
    items.append(
        _field_box(
            "origin_upper",
            FIELD_GRID_X[0],
            FIELD_GRID_Y[0],
            480.0,
            350.0,
            530.0,
            240.0,
        )
    )
    return _pallet(items)


def test_field_grid_lays_two_ground_rings_before_the_origin_column_rises():
    """Pallet 1 used to lift the origin column at seq 2, ahead of any spread."""

    config = ExecutionSequenceConfig(force_publish_on_gate_failure=True)
    ordered_items = sequence_pallet_items(_field_grid_pallet(), config)
    ordered = _ids(ordered_items)

    ring_two_ground = ["g02", "g12", "g20", "g21", "g22"]
    ring_three_ground = ["g03", "g13", "g23", "g30", "g31", "g32", "g33"]

    assert ordered[:4] == ["g00", "g01", "g10", "g11"]
    assert ordered.index("origin_upper") == 9
    assert set(ordered[4:9]) == set(ring_two_ground)
    assert set(ordered[10:]) == set(ring_three_ground)
    assert (
        sequence_planner_module._collect_path_risks(ordered_items, config) == []
    )


def test_field_pocket_layout_places_every_box_before_its_approach_neighbors():
    config = ExecutionSequenceConfig(force_publish_on_gate_failure=True)

    ordered = sequence_pallet_items(_field_pocket_pallet(), config)

    seq = {item["id"]: item["seq"] for item in ordered}
    assert seq["644"] < seq["647"]
    assert seq["647"] < seq["62"]
    assert seq["62"] < seq["82"]
    assert seq["635"] < seq["82"]
    assert seq["169"] < seq["635"]


def test_field_pocket_layout_leaves_no_modeled_path_risk():
    config = ExecutionSequenceConfig(force_publish_on_gate_failure=True)

    ordered = sequence_pallet_items(_field_pocket_pallet(), config)

    assert sequence_planner_module._collect_path_risks(ordered, config) == []


def test_legacy_open_corner_rule_still_produces_the_old_pocket_risk():
    config = ExecutionSequenceConfig(
        pocket_rule="open_corner",
        max_occupied_directions=2,
        force_publish_on_gate_failure=True,
    )

    ordered = sequence_pallet_items(_field_pocket_pallet(), config)

    assert sequence_planner_module._collect_path_risks(ordered, config)


def test_public_planner_spreads_the_ground_ring_before_the_origin_column():
    boxes = [
        _box("diagonal_base", 100, 100, 0),
        _box("y_base", 0, 100, 0),
        _box("x_base", 100, 0, 0),
        _box("origin_upper", 0, 0, 100),
        _box("origin_base", 0, 0, 0),
    ]

    ordered = sequence_pallet_items(
        _pallet(boxes),
        ExecutionSequenceConfig(
            approach_offset_x_mm=0.0,
            approach_offset_y_mm=0.0,
            approach_suction_xy_clearance_mm=0.0,
            preserve_open_direction=False,
            max_occupied_directions=2,
        ),
    )

    assert _ids(ordered) == [
        "origin_base",
        "y_base",
        "x_base",
        "diagonal_base",
        "origin_upper",
    ]


def _height_egress_edges(items, config):
    edges, indegree, supports = sequence_planner_module._support_edges(
        items, config.coordinate_tolerance_mm
    )
    sequence_planner_module._add_height_egress_edges(
        items, config, edges, indegree, supports, PALLET_DIMS
    )
    return edges


def test_height_egress_skips_a_retreat_side_upper_column():
    boxes = [
        _box("adjacent_base", 105, 0, 0),
        _box("origin_upper", 0, 0, 100),
        _box("origin_base", 0, 0, 0),
    ]
    config = ExecutionSequenceConfig(
        approach_offset_x_mm=0.0,
        approach_offset_y_mm=0.0,
        approach_suction_xy_clearance_mm=0.0,
        side_neighbor_clearance_mm=5.0,
        preserve_open_direction=False,
    )

    edges = _height_egress_edges(boxes, config)
    ordered = sequence_pallet_items(_pallet(boxes), config)

    assert 1 not in edges[0]
    assert 0 not in edges[1]
    # Neither box constrains the other, so the ground-first wave decides.
    assert _ids(ordered) == [
        "origin_base",
        "adjacent_base",
        "origin_upper",
    ]


def test_height_egress_delays_an_approach_side_upper_column():
    boxes = [
        _box("origin_base", 0, 0, 0),
        _box("far_base", 105, 0, 0),
        _box("far_upper", 105, 0, 100),
    ]
    config = ExecutionSequenceConfig(
        approach_offset_x_mm=0.0,
        approach_offset_y_mm=0.0,
        approach_suction_xy_clearance_mm=0.0,
        side_neighbor_clearance_mm=5.0,
        preserve_open_direction=False,
    )

    edges = _height_egress_edges(boxes, config)

    assert 2 in edges[0]


def test_height_egress_uses_box_frontier_when_suction_is_inset():
    boxes = [
        _box(
            "origin_base",
            0,
            0,
            0,
            cup_rect={
                "x_min": 25,
                "x_max": 75,
                "y_min": 25,
                "y_max": 75,
            },
        ),
        _box("far_base", 105, 0, 0),
        _box("far_upper", 105, 0, 100),
    ]
    config = ExecutionSequenceConfig(
        approach_offset_x_mm=0.0,
        approach_offset_y_mm=0.0,
        approach_suction_xy_clearance_mm=0.0,
        side_neighbor_clearance_mm=5.0,
        preserve_open_direction=False,
    )

    edges = _height_egress_edges(boxes, config)

    assert 2 in edges[0]


def test_height_egress_does_not_delay_an_equal_top_far_column():
    boxes = [
        _box("diagonal_base", 100, 100, 0, height=200),
        _box("y_base", 0, 100, 0, height=200),
        _box("x_base", 100, 0, 0, height=200),
        _box("origin_upper", 0, 0, 100),
        _box("origin_base", 0, 0, 0),
    ]

    ordered = sequence_pallet_items(
        _pallet(boxes),
        ExecutionSequenceConfig(
            approach_offset_x_mm=0.0,
            approach_offset_y_mm=0.0,
            approach_suction_xy_clearance_mm=0.0,
            preserve_open_direction=False,
            max_occupied_directions=2,
        ),
    )

    assert _ids(ordered) == [
        "origin_base",
        "origin_upper",
        "y_base",
        "x_base",
        "diagonal_base",
    ]


def test_height_egress_adds_an_edge_for_directional_exit_only():
    lower = _box("lower", 0, 0, 0)
    upper_base = _box(
        "upper_base", 110, 110, 0, length=15, width=15
    )
    upper = _box(
        "upper", 110, 110, 100, length=15, width=15, height=120
    )
    items = [lower, upper_base, upper]
    edges, indegree, supports = sequence_planner_module._support_edges(
        items, 1e-6
    )

    sequence_planner_module._add_height_egress_edges(
        items,
        ExecutionSequenceConfig(
            path_gate_mode="hard",
            approach_offset_x_mm=20.0,
            approach_offset_y_mm=20.0,
            preserve_open_direction=False,
        ),
        edges,
        indegree,
        supports,
        PALLET_DIMS,
    )

    assert 2 in edges[0]


def test_score_only_height_egress_ignores_directional_offset_model():
    lower = _box("lower", 0, 0, 0)
    upper_base = _box(
        "upper_base", 110, 110, 0, length=15, width=15
    )
    upper = _box(
        "upper", 110, 110, 100, length=15, width=15, height=120
    )
    items = [lower, upper_base, upper]
    edges, indegree, supports = sequence_planner_module._support_edges(
        items, 1e-6
    )

    sequence_planner_module._add_height_egress_edges(
        items,
        ExecutionSequenceConfig(
            path_gate_mode="score_only",
            approach_offset_x_mm=20.0,
            approach_offset_y_mm=20.0,
            preserve_open_direction=False,
        ),
        edges,
        indegree,
        supports,
        PALLET_DIMS,
    )

    assert 2 not in edges[0]


@pytest.mark.parametrize(
    "name",
    [
        "_classify_staircase_wave",
        "_uses_staircase_wave",
        "_staircase_shells",
        "_stable_staircase_order",
        "_greedy_staircase_order",
        "_stable_regular_order",
        "_greedy_reverse_order",
    ],
)
def test_obsolete_ordering_helpers_are_absent(name):
    assert not hasattr(sequence_planner_module, name)


def test_public_planner_emits_no_mode_classification_log(caplog):
    boxes = [
        _box("origin", 0, 0, 0),
        _box("far", 100, 100, 0),
    ]

    with caplog.at_level("INFO", logger=sequence_planner_module.__name__):
        sequence_pallet_items(
            _pallet(boxes),
            ExecutionSequenceConfig(preserve_open_direction=False),
        )

    assert "execution sequence classification" not in caplog.text


def test_removed_adaptive_config_fields_are_not_exposed():
    obsolete_fields = {
        "prefer_adjacent_occupied_sides",
        "adaptive_staircase_enabled",
        "staircase_height_difference_threshold_mm",
        "staircase_transition_ratio_threshold",
        "staircase_min_transition_edges",
    }

    assert obsolete_fields.isdisjoint(
        ExecutionSequenceConfig.__dataclass_fields__
    )


def test_approach_config_defaults_are_explicit():
    config = ExecutionSequenceConfig()

    assert config.approach_offset_x_mm == 20.0
    assert config.approach_offset_y_mm == 20.0
    assert config.approach_z_clearance_mm == 20.0
    assert config.approach_box_xy_clearance_mm == 0.0
    assert config.approach_suction_xy_clearance_mm == 0.0


@pytest.mark.parametrize(
    "field",
    [
        "approach_offset_x_mm",
        "approach_offset_y_mm",
        "approach_z_clearance_mm",
        "approach_box_xy_clearance_mm",
        "approach_suction_xy_clearance_mm",
    ],
)
@pytest.mark.parametrize(
    "value, message",
    [
        (True, "finite number"),
        (-1.0, "non-negative"),
        (float("nan"), "finite"),
        (float("inf"), "finite"),
    ],
)
def test_invalid_approach_config_values_are_rejected(field, value, message):
    with pytest.raises(ValueError, match=message):
        ExecutionSequenceConfig(**{field: value})


def test_require_suction_pose_must_be_boolean():
    with pytest.raises(ValueError, match="require_suction_pose must be a boolean"):
        ExecutionSequenceConfig(require_suction_pose="false")


def test_approach_config_rejects_integer_too_large_for_float():
    with pytest.raises(ValueError, match="finite number"):
        ExecutionSequenceConfig(approach_offset_x_mm=10**10000)


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


def test_approach_timeout_uses_existing_public_error(monkeypatch):
    observed_deadlines = []

    def timeout_during_approach(
        _items,
        _config,
        _edges,
        _indegree,
        _pallet_dims=None,
        deadline=None,
    ):
        observed_deadlines.append(deadline)
        raise sequence_planner_module._ExecutionSequenceDeadlineExceeded

    monkeypatch.setattr(sequence_planner_module.time, "monotonic", lambda: 10.0)
    monkeypatch.setattr(
        sequence_planner_module,
        "_add_approach_edges",
        timeout_during_approach,
    )

    with pytest.raises(
        ExecutionSequenceError,
        match="no execution order within 1.000s",
    ):
        sequence_pallet_items(
            _pallet([_box("only", 0, 0, 0)]),
                ExecutionSequenceConfig(
                    path_gate_mode="hard",
                    preserve_open_direction=False,
                max_sequence_search_seconds_per_pallet=1.0,
            ),
        )

    assert observed_deadlines == [11.0]


def test_force_publish_uses_its_independent_safety_deadline(monkeypatch):
    observed_deadlines = []

    def fail_normal_planning(_pallet, config=None):
        raise ExecutionSequenceError("normal gate failed")

    def timeout_during_forced_height_egress(
        _items,
        _config,
        _edges,
        _indegree,
        _supports,
        _pallet_dims=None,
        deadline=None,
    ):
        observed_deadlines.append(deadline)
        raise sequence_planner_module._ExecutionSequenceDeadlineExceeded

    monkeypatch.setattr(sequence_planner_module.time, "monotonic", lambda: 10.0)
    monkeypatch.setattr(
        sequence_planner_module,
        "sequence_pallet_items",
        fail_normal_planning,
    )
    monkeypatch.setattr(
        sequence_planner_module,
        "_add_height_egress_edges",
        timeout_during_forced_height_egress,
    )

    with pytest.raises(
        ExecutionSequenceError,
        match="forced execution order exceeded 2.500s",
    ):
        plan_execution_report(
            {"pallets": [_pallet([_box("only", 0, 0, 0)])]},
            ExecutionSequenceConfig(
                force_publish_on_gate_failure=True,
                forced_sequence_search_seconds_per_pallet=2.5,
            ),
        )

    assert observed_deadlines == [12.5]


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


def test_box_clearance_rejects_pair_with_no_safe_vertical_order():
    target = _box("target", 0, 0, 0, height=300)
    nearby_blocker = _box("blocker", 110, 0, 0, height=100)

    with pytest.raises(ExecutionSequenceError, match="cyclic"):
        sequence_pallet_items(
            _pallet([nearby_blocker, target]),
                ExecutionSequenceConfig(
                    path_gate_mode="hard",
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
                ExecutionSequenceConfig(
                    path_gate_mode="hard",
                    suction_z_clearance_mm=1.0,
                ),
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
        ("max_occupied_directions", 3, "integer from 0 to 2"),
        ("max_occupied_directions", True, "integer from 0 to 2"),
        ("side_neighbor_clearance_mm", -1.0, "non-negative"),
        ("side_neighbor_clearance_mm", True, "finite number"),
        ("side_height_tolerance_mm", float("inf"), "finite"),
        ("side_height_tolerance_mm", False, "finite number"),
        ("preserve_open_direction", "true", "boolean"),
        ("max_sequence_search_seconds_per_pallet", 0.0, "positive"),
        ("max_sequence_search_seconds_per_pallet", True, "finite number"),
        ("forced_sequence_search_seconds_per_pallet", 0.0, "positive"),
        ("forced_sequence_search_seconds_per_pallet", True, "finite number"),
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
    assert set(result["pallets"][0]) == set(source["pallets"][0]).union(
        {"execution_sequence_diagnostics"}
    )
    assert result["pallets"][0]["execution_sequence_diagnostics"] == {
        "path_gate_mode": "score_only",
        "soft_path_risk_count": 0,
        "soft_path_risks": [],
        "boundary_clamp_relaxed_count": 0,
        "boundary_clamp_relaxations": [],
        "pocket_violation_count": 0,
        "pocket_violations": [],
    }
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


def test_wcs_seq_follows_execution_order_and_layer_id_is_fixed():
    tall = _box("tall", 0, 0, 0, height=300)
    tall["product_code"] = 1
    top = _box("top", 0, 0, 300, height=100)
    top["product_code"] = 2
    report = {
        "pallets": [
            {
                **_pallet([top, tall]),
                "mpm_status": "FAILED",
                "case_group": 0,
            }
        ]
    }

    result = report_to_execution_plan_result(report)

    assert len(result.cases) == 1
    assert len(result.cases[0]["layers"]) == 2
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
    assert "execution_sequence_diagnostics" not in mapped
    assert _ids(mapped["packed_items"]) == ["tall", "top"]
    assert all(
        "stack_height_before" not in item
        for item in mapped["packed_items"]
    )


def test_execution_bundle_plans_once_and_reuses_the_same_seq(
    tmp_path, monkeypatch
):
    report = _cli_report()
    original_path = tmp_path / "packing_plan.json"
    calls = []
    real_planner = plan_execution_report

    def counted_planner(input_report, config=None):
        calls.append(input_report)
        return real_planner(input_report, config=config)

    monkeypatch.setattr(
        publisher_module, "plan_execution_report", counted_planner
    )
    monkeypatch.setattr(
        wcs_export_module, "plan_execution_report", counted_planner
    )

    paths = publisher_module.publish_execution_bundle(
        report,
        original_path,
        ExecutionSequenceConfig(),
    )

    assert len(calls) == 1
    execution = json.loads(paths.execution.read_text(encoding="utf-8"))
    cases = json.loads(paths.wcs_cases.read_text(encoding="utf-8"))
    plan_map = json.loads(paths.wcs_map.read_text(encoding="utf-8"))
    unique_id = cases[0]["box_unique_id"]
    execution_items = execution["pallets"][0]["packed_items"]
    mapped_items = plan_map[unique_id]["packed_items"]
    cartons = [
        carton
        for layer in cases[0]["layers"]
        for carton in layer["cartons"]
    ]
    assert [item["seq"] for item in execution_items] == [1, 2]
    assert [item["seq"] for item in mapped_items] == [1, 2]
    assert [carton["seq"] for carton in sorted(
        cartons, key=lambda carton: carton["seq"]
    )] == [1, 2]
    assert all("stack_height_before" in item for item in execution_items)
    assert all("stack_height_before" not in item for item in mapped_items)


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


def test_cli_passes_approach_config_to_planner(tmp_path, monkeypatch):
    source = tmp_path / "packing.json"
    output = tmp_path / "packing_execution.json"
    config_path = tmp_path / "packing_config.yaml"
    report = _cli_report()
    source.write_text(json.dumps(report), encoding="utf-8")
    config_path.write_text(
        "execution_sequence:\n"
        "  enabled: true\n"
        "  path_gate_mode: hard\n"
        "  approach_offset_x_mm: 41\n"
        "  approach_offset_y_mm: 42\n"
        "  approach_z_clearance_mm: 43\n"
        "  approach_box_xy_clearance_mm: 44\n"
        "  approach_suction_xy_clearance_mm: 45\n",
        encoding="utf-8",
    )
    captured = {}

    def capture_config(input_report, config):
        captured["config"] = config
        return deepcopy(input_report)

    monkeypatch.setattr(
        run_execution_planning, "plan_execution_report", capture_config
    )

    result = run_execution_planning.main(
        [
            str(source),
            "--config",
            str(config_path),
            "--output",
            str(output),
        ]
    )

    assert result == 0
    planner_config = captured["config"]
    assert planner_config.path_gate_mode == "hard"
    assert planner_config.approach_offset_x_mm == 41.0
    assert planner_config.approach_offset_y_mm == 42.0
    assert planner_config.approach_z_clearance_mm == 43.0
    assert planner_config.approach_box_xy_clearance_mm == 44.0
    assert planner_config.approach_suction_xy_clearance_mm == 45.0


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


def test_cli_rejects_removed_adaptive_flag(tmp_path):
    source = tmp_path / "packing.json"
    source.write_text(json.dumps(_cli_report()), encoding="utf-8")
    script = Path(__file__).resolve().parents[1] / "run_execution_planning.py"

    completed = subprocess.run(
        [
            sys.executable,
            str(script),
            str(source),
            "--adaptive-staircase-enabled",
        ],
        cwd=str(script.parent),
        capture_output=True,
        text=True,
    )

    assert completed.returncode != 0
    assert "unrecognized arguments" in completed.stderr


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
