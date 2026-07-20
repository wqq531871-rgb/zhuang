"""Directed donor-receiver exchange tests."""

from copy import deepcopy

from src.config import ConstraintConfig
from src.packing.beam_search_packer import BeamSearchPacker


PALLET_DIMS = {"length": 300.0, "width": 200.0, "height": 300.0}


def _box(box_id, x, mpm, case_group=7):
    return {
        "id": box_id,
        "type": "T",
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
        "case_group": case_group,
        "position": {"x": float(x), "y": 0.0, "z": 0.0},
        "pallet_dims": deepcopy(PALLET_DIMS),
    }


def _plan(pallet_id, items, target=192.0):
    total = sum(item["min_pack_multiple"] for item in items)
    return {
        "pallet_id": pallet_id,
        "pallet_type": "TEST",
        "sales_order_no": "O1",
        "case_group": items[0]["case_group"],
        "packed_items": items,
        "mpm_total": total,
        "mpm_target": target,
        "mpm_gap": target - total,
        "mpm_status": "SUCCESS" if total >= target else "FAILED",
        "stability_checks": {"status": "SUCCESS"},
    }


def _config():
    return ConstraintConfig(
        suction_reachability_enabled=False,
        center_of_mass_tolerance=1.0,
    )


def test_pack_additions_preserves_existing_layout():
    packer = BeamSearchPacker(
        PALLET_DIMS,
        size_tolerance=0.0,
        constraint_config=_config(),
    )
    existing = [_box("receiver", 0, 180)]
    addition = _box("moved", 100, 20)
    addition.pop("position")
    before = deepcopy(existing)

    combined, unfitted = packer.pack_additions(
        existing,
        [addition],
        target_mpm=192.0,
        num_restarts=2,
        beam_width=3,
        candidate_limit=10,
        random_seed=7,
    )

    assert not unfitted
    assert {item["id"] for item in combined} == {"receiver", "moved"}
    kept = next(item for item in combined if item["id"] == "receiver")
    assert kept == before[0]


def test_directed_exchange_reaches_target_without_repacking_receiver():
    from src.rescue.directed_exchange import directed_donor_receiver_exchange

    receiver = _plan("R", [_box("receiver", 0, 180)])
    donor = _plan(
        "D",
        [_box("keep", 0, 1), _box("move", 100, 20)],
    )
    plans = [receiver, donor]
    receiver_before = deepcopy(receiver["packed_items"])

    diag = directed_donor_receiver_exchange(
        plans,
        PALLET_DIMS,
        192.0,
        constraint_config=_config(),
    )

    assert diag["directed_exchange_accepted"] == 1
    assert sum(p["mpm_status"] == "SUCCESS" for p in plans) == 1
    rescued = next(p for p in plans if p["pallet_id"] == "R")
    kept = next(item for item in rescued["packed_items"] if item["id"] == "receiver")
    assert kept == receiver_before[0]
    assert {item["id"] for item in rescued["packed_items"]} == {
        "receiver",
        "move",
    }
    remaining_donor = next(p for p in plans if p["pallet_id"] == "D")
    assert [item["id"] for item in remaining_donor["packed_items"]] == ["keep"]


def test_directed_exchange_never_crosses_case_group():
    from src.rescue.directed_exchange import directed_donor_receiver_exchange

    receiver = _plan("R", [_box("receiver", 0, 180, case_group=7)])
    donor = _plan("D", [_box("move", 0, 20, case_group=8)])
    plans = [receiver, donor]
    before = deepcopy(plans)

    diag = directed_donor_receiver_exchange(
        plans,
        PALLET_DIMS,
        192.0,
        constraint_config=_config(),
    )

    assert diag["directed_exchange_accepted"] == 0
    assert plans == before


def test_workflow_forwards_directed_exchange_config(monkeypatch):
    import src.main.workflow as workflow_module
    from src.main.workflow import PackingWorkflow

    calls = []

    def fake_exchange(
        plans,
        pallet_dims,
        target_mpm,
        constraint_config,
        max_items,
        max_attempts,
    ):
        calls.append((
            plans,
            pallet_dims,
            target_mpm,
            constraint_config,
            max_items,
            max_attempts,
        ))
        return {"rescued": 1, "directed_exchange_accepted": 1}

    monkeypatch.setattr(
        workflow_module,
        "directed_donor_receiver_exchange",
        fake_exchange,
        raising=False,
    )
    config = ConstraintConfig(
        directed_exchange_enabled=True,
        directed_exchange_max_items=3,
        directed_exchange_max_attempts=12,
    )
    workflow = PackingWorkflow.__new__(PackingWorkflow)
    workflow._constraint_config = config
    plans = [_plan("R", [_box("receiver", 0, 180)])]

    diag = workflow._call_directed_exchange(
        plans,
        PALLET_DIMS,
        192.0,
    )

    assert diag["rescued"] == 1
    assert calls == [(
        plans,
        PALLET_DIMS,
        192.0,
        config,
        3,
        12,
    )]


def test_workflow_skips_directed_exchange_when_disabled(monkeypatch):
    import src.main.workflow as workflow_module
    from src.main.workflow import PackingWorkflow

    def fail_if_called(*args, **kwargs):
        raise AssertionError("disabled directed exchange must not run")

    monkeypatch.setattr(
        workflow_module,
        "directed_donor_receiver_exchange",
        fail_if_called,
        raising=False,
    )
    workflow = PackingWorkflow.__new__(PackingWorkflow)
    workflow._constraint_config = ConstraintConfig(
        directed_exchange_enabled=False,
    )

    diag = workflow._call_directed_exchange([], PALLET_DIMS, 192.0)

    assert diag == {
        "rescued": 0,
        "directed_exchange_tried": 0,
        "directed_exchange_accepted": 0,
        "skipped": True,
    }
