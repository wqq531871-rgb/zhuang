"""Conditional GCP/alternative full-path ratchet tests."""

import importlib
from copy import deepcopy

from src.config import ConstraintConfig


PALLET_DIMS = {"length": 200.0, "width": 200.0, "height": 300.0}


def _box(box_id, x, mpm):
    return {
        "id": box_id,
        "type": "T",
        "pallet_type": "MH423C",
        "sales_order_no": "O1",
        "length": 100.0,
        "width": 100.0,
        "height": 100.0,
        "raw_length": 100.0,
        "raw_width": 100.0,
        "raw_height": 100.0,
        "original_length": 100.0,
        "original_width": 100.0,
        "original_height": 100.0,
        "weight": 1.0,
        "min_pack_multiple": float(mpm),
        "case_group": 7,
        "position": {"x": float(x), "y": 0.0, "z": 0.0},
        "pallet_dims": deepcopy(PALLET_DIMS),
        "suction_rect_x_min": float(x),
        "suction_rect_x_max": float(x + 100),
        "suction_rect_y_min": 0.0,
        "suction_rect_y_max": 100.0,
        "suction_box_corner": "x_min_y_min",
        "suction_cup_corner": "x_min_y_min",
        "suction_orientation": "cup_100x_100y",
        "suction_cup_x_size": 100.0,
        "suction_cup_y_size": 100.0,
    }


def _plan(pallet_id, items, target=192.0):
    total = sum(item["min_pack_multiple"] for item in items)
    return {
        "pallet_id": pallet_id,
        "pallet_type": "TEST",
        "sales_order_no": "O1",
        "case_group": 7,
        "packed_items": items,
        "mpm_total": total,
        "mpm_target": target,
        "mpm_gap": target - total,
        "mpm_status": "SUCCESS" if total >= target else "FAILED",
        "stability_checks": {"status": "SUCCESS"},
    }


def test_dual_path_only_triggers_for_uncaptured_index_upper_bound():
    module = importlib.import_module("src.main.alternative_path")

    boxes = [_box("A", 0, 100), _box("B", 0, 100)]

    assert module.has_uncaptured_opportunity(
        boxes,
        [_plan("P1", [boxes[0]]), _plan("P2", [boxes[1]])],
        192,
    )
    assert not module.has_uncaptured_opportunity(
        boxes,
        [_plan("P1", [_box("A", 0, 100), _box("B", 100, 100)])],
        192,
    )


def test_dual_path_rank_is_success_then_pallet_count_then_failed_peak():
    module = importlib.import_module("src.main.alternative_path")
    low_failed = [_plan("P1", [_box("A", 0, 150)])]
    high_failed = [_plan("P1", [_box("A", 0, 180)])]
    one_success = [
        _plan("P1", [_box("A", 0, 100), _box("B", 100, 100)])
    ]
    one_success_plus_tail = one_success + [_plan("P2", [_box("C", 0, 1)])]

    assert module.candidate_rank(one_success) > module.candidate_rank(high_failed)
    assert module.candidate_rank(one_success) > module.candidate_rank(
        one_success_plus_tail
    )
    assert module.candidate_rank(high_failed) > module.candidate_rank(low_failed)


def test_dual_path_rejects_nonconserved_candidate_before_selection():
    module = importlib.import_module("src.main.alternative_path")
    box_a = _box("A", 0, 100)
    box_b = _box("B", 0, 100)
    primary = [_plan("P1", [box_a]), _plan("P2", [box_b])]
    invalid_better = [
        _plan("P1", [_box("A", 0, 100), _box("A", 100, 100)])
    ]

    chosen, source = module.choose_guarded_candidate(
        [box_a, box_b],
        primary,
        invalid_better,
        PALLET_DIMS,
        ConstraintConfig(),
    )

    assert source == "gcp"
    assert chosen is primary


def test_dual_path_accepts_valid_strictly_better_candidate():
    module = importlib.import_module("src.main.alternative_path")
    box_a = _box("A", 0, 100)
    box_b = _box("B", 0, 100)
    primary = [_plan("P1", [box_a]), _plan("P2", [box_b])]
    alternative = [
        _plan("P1", [_box("A", 0, 100), _box("B", 100, 100)])
    ]

    chosen, source = module.choose_guarded_candidate(
        [box_a, box_b],
        primary,
        alternative,
        PALLET_DIMS,
        ConstraintConfig(),
    )

    assert source == "alternative"
    assert chosen == alternative


def test_alternative_full_path_has_hard_process_timeout():
    module = importlib.import_module("src.main.alternative_path")
    boxes = [_box("A", 0, 100), _box("B", 0, 100)]

    result = module.run_alternative_full_path(
        boxes,
        ConstraintConfig(),
        timeout_seconds=0.001,
    )

    assert result["status"] == "timeout"
    assert result["report"] is None


def test_alternative_full_path_returns_complete_report():
    module = importlib.import_module("src.main.alternative_path")
    boxes = [_box("A", 0, 100), _box("B", 0, 100)]

    result = module.run_alternative_full_path(
        boxes,
        ConstraintConfig(
            suction_reachability_enabled=False,
            center_of_mass_tolerance=1.0,
        ),
        timeout_seconds=20.0,
    )

    assert result["status"] == "ok", result.get("error")
    assert result["report"] is not None
    assert result["report"]["pallets"]


def test_workflow_runs_and_adopts_alternative_for_opportunity_group(monkeypatch):
    from src.main.workflow import PackingWorkflow
    import src.main.workflow as workflow_module

    box_a = _box("A", 0, 100)
    box_b = _box("B", 0, 100)
    primary = [_plan("P1", [box_a]), _plan("P2", [box_b])]
    alternative = [
        _plan("P1", [_box("A", 0, 100), _box("B", 100, 100)])
    ]
    monkeypatch.setattr(
        workflow_module,
        "run_alternative_full_path",
        lambda boxes, config, timeout_seconds: {
            "status": "ok",
            "report": {"pallets": alternative},
            "error": None,
            "elapsed_seconds": 0.2,
        },
        raising=False,
    )
    workflow = PackingWorkflow.__new__(PackingWorkflow)
    workflow._constraint_config = ConstraintConfig(
        dual_path_enabled=True,
        dual_path_time_limit_seconds=3.0,
    )

    chosen, diag = workflow._run_dual_path_candidate(
        [box_a, box_b], primary, 192.0, PALLET_DIMS
    )

    assert chosen == alternative
    assert diag["triggered"] is True
    assert diag["adopted"] is True
    assert diag["source"] == "alternative"
