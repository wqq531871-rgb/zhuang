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


def test_fill_mode_partitions_with_fill_contributions_and_threshold():
    class RecordingGcp:
        def __init__(self):
            self.calls = []

        def partition_suitable(self, boxes, target):
            self.calls.append((boxes, target))
            return list(boxes), []

        def suits_group(self, boxes, target):
            return True

    workflow = _workflow(SuccessTarget(mode="fill_rate", threshold=0.80))
    workflow._gcp_packer = RecordingGcp()
    original = [{
        "id": "B1",
        "length": 10.0,
        "width": 10.0,
        "height": 8.0,
        "volume": 800.0,
        "min_pack_multiple": 12.0,
        "pallet_dims": PALLET,
    }]

    grouped = workflow._partition_groups({("A", "ORDER-1"): original})

    seen_boxes, seen_target = workflow._gcp_packer.calls[0]
    assert seen_target == pytest.approx(0.80)
    assert seen_boxes[0]["min_pack_multiple"] == pytest.approx(0.80)
    assert original[0]["min_pack_multiple"] == 12.0
    assert grouped[("A", "ORDER-1")][0]["_index_min_pack_multiple"] == 12.0


def test_refresh_index_summary_gaps_uses_restored_index_values():
    workflow = _workflow(SuccessTarget(mode="fill_rate", threshold=0.80))
    plans = [{
        "pallet_type": "A",
        "sales_order_no": "ORDER-1",
        "index_status": "FAILED",
        "mpm_status": "FAILED",
        "mpm_gap": 188.0,
    }]
    stats = {"A__ORDER-1": {
        "pallet_type": "A",
        "sales_order_no": "ORDER-1",
        "avg_mpm_gap": 0.79,
        "max_mpm_gap": 0.79,
    }}

    workflow._refresh_index_summary_gaps(plans, stats)

    assert stats["A__ORDER-1"]["avg_mpm_gap"] == 188.0
    assert stats["A__ORDER-1"]["max_mpm_gap"] == 188.0


def test_refresh_index_summary_gaps_keeps_index_mode_status_compatible():
    plans = [{
        "pallet_type": "A",
        "sales_order_no": "ORDER-1",
        "mpm_status": "FAILED",
        "mpm_gap": 8.0,
    }]
    stats = {"A__ORDER-1": {
        "pallet_type": "A",
        "sales_order_no": "ORDER-1",
        "avg_mpm_gap": 8.0,
        "max_mpm_gap": 8.0,
    }}

    PackingWorkflow._refresh_index_summary_gaps(plans, stats)

    assert stats["A__ORDER-1"]["avg_mpm_gap"] == 8.0
    assert stats["A__ORDER-1"]["max_mpm_gap"] == 8.0
