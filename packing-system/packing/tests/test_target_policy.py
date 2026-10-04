import math

import pytest

from src.main.success_target import SuccessTarget
from src.main.target_policy import make_target_policy


PALLET_DIMS = {"length": 10.0, "width": 10.0, "height": 10.0}


def test_index_policy_matches_historical_mpm_math():
    policy = make_target_policy(SuccessTarget(), 192.0, PALLET_DIMS)
    items = [
        {"min_pack_multiple": 100.0, "volume": 400.0},
        {"min_pack_multiple": 92.0, "volume": 300.0},
    ]

    assert policy.items_value(items) == 192.0
    assert policy.is_reached(items)
    assert policy.gap(items) == 0.0


def test_fill_policy_uses_volume_and_ignores_mpm():
    target = SuccessTarget(mode="fill_rate", threshold=0.75)
    policy = make_target_policy(target, 192.0, PALLET_DIMS)
    low_index = [{"min_pack_multiple": 1.0, "volume": 750.0}]
    high_index = [{"min_pack_multiple": 999.0, "volume": 750.0}]

    assert policy.items_value(low_index) == pytest.approx(0.75)
    assert policy.items_value(high_index) == pytest.approx(0.75)
    assert policy.is_reached(low_index)
    assert policy.is_reached(high_index)


@pytest.mark.parametrize("threshold", [0.70, 0.75, 0.80, 0.85, 0.90])
def test_fill_policy_inclusive_boundary_for_all_steps(threshold):
    policy = make_target_policy(
        SuccessTarget(mode="fill_rate", threshold=threshold),
        192.0,
        PALLET_DIMS,
    )

    assert policy.is_reached([{"volume": threshold * 1000.0}])
    assert not policy.is_reached([{"volume": threshold * 1000.0 - 0.001}])


@pytest.mark.parametrize(
    "dims",
    [
        {},
        {"length": 0, "width": 10, "height": 10},
        {"length": -1, "width": 10, "height": 10},
        {"length": math.nan, "width": 10, "height": 10},
        {"length": math.inf, "width": 10, "height": 10},
    ],
)
def test_fill_policy_rejects_invalid_pallet_volume(dims):
    with pytest.raises(ValueError, match="托盘尺寸"):
        make_target_policy(
            SuccessTarget(mode="fill_rate", threshold=0.80),
            192.0,
            dims,
        )


def test_fill_policy_uses_original_box_volume_after_rotation():
    policy = make_target_policy(
        SuccessTarget(mode="fill_rate", threshold=0.80),
        192.0,
        PALLET_DIMS,
    )
    rotated = {
        "length": 10.0,
        "width": 5.0,
        "height": 4.0,
        "original_length": 5.0,
        "original_width": 10.0,
        "original_height": 4.0,
    }

    assert policy.box_value(rotated) == pytest.approx(0.2)


def test_policy_annotation_keeps_index_status_separate_from_fill_status():
    policy = make_target_policy(
        SuccessTarget(mode="fill_rate", threshold=0.75),
        192.0,
        PALLET_DIMS,
    )
    plan = {
        "mpm_total": 100.0,
        "mpm_target": 192.0,
        "packed_items": [{"volume": 800.0}],
    }

    policy.annotate_plan(plan)

    assert plan["index_status"] == "FAILED"
    assert plan["goal_value"] == pytest.approx(0.8)
    assert plan["final_status"] == "SUCCESS"
    assert plan["mpm_status"] == "SUCCESS"
