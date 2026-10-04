import pytest

from src.main.success_target import SuccessTarget
from src.main.workflow import PackingWorkflow


PALLET = {"length": 10.0, "width": 10.0, "height": 10.0}


def _workflow(target):
    workflow = object.__new__(PackingWorkflow)
    workflow._success_target = target
    workflow._targets = {"A": 192.0}
    return workflow


def test_workflow_fill_mode_projects_volume_target_without_mutating_input():
    workflow = _workflow(SuccessTarget(mode="fill_rate", threshold=0.80))
    boxes = [
        {
            "id": "B1",
            "length": 10.0,
            "width": 10.0,
            "height": 8.0,
            "volume": 800.0,
            "min_pack_multiple": 1.0,
            "pallet_dims": PALLET,
        }
    ]

    working, effective_target, policy = workflow._prepare_group_target("A", boxes)

    assert effective_target == pytest.approx(0.80)
    assert working[0]["min_pack_multiple"] == pytest.approx(0.80)
    assert boxes[0]["min_pack_multiple"] == 1.0
    assert policy.is_reached(working)


def test_workflow_index_mode_keeps_historical_target_and_values():
    workflow = _workflow(SuccessTarget())
    boxes = [
        {
            "id": "B1",
            "volume": 800.0,
            "min_pack_multiple": 12.0,
            "pallet_dims": PALLET,
        }
    ]

    working, effective_target, policy = workflow._prepare_group_target("A", boxes)

    assert effective_target == 192.0
    assert working[0]["min_pack_multiple"] == 12.0
    assert policy.mode == "index"


def test_workflow_restores_index_but_keeps_fill_as_final_status():
    workflow = _workflow(SuccessTarget(mode="fill_rate", threshold=0.75))
    boxes = [
        {
            "id": "B1",
            "volume": 800.0,
            "min_pack_multiple": 12.0,
            "pallet_dims": PALLET,
        }
    ]
    working, _, _ = workflow._prepare_group_target("A", boxes)
    plans = [
        {
            "pallet_type": "A",
            "packed_items": working,
            "mpm_total": 0.8,
            "mpm_target": 0.75,
            "mpm_status": "SUCCESS",
        }
    ]

    workflow._restore_target_plans(plans)

    assert plans[0]["mpm_total"] == 12.0
    assert plans[0]["index_status"] == "FAILED"
    assert plans[0]["fill_rate"] == pytest.approx(0.8)
    assert plans[0]["final_status"] == "SUCCESS"
