from src.main.success_target import SuccessTarget
from src.main.target_policy import make_target_policy
from src.packing.beam_search_packer import BeamSearchPacker


PALLET_DIMS = {"length": 1200.0, "width": 1200.0, "height": 1000.0}


def _box(box_id, mpm):
    return {
        "id": box_id,
        "length": 1000.0,
        "width": 1000.0,
        "height": 720.0,
        "weight": 1.0,
        "min_pack_multiple": mpm,
        "pallet_dims": PALLET_DIMS,
    }


def test_beam_fill_mode_stops_at_fill_threshold_and_returns_remainder():
    dims = PALLET_DIMS
    policy = make_target_policy(
        SuccessTarget(mode="fill_rate", threshold=0.50), 192.0, dims
    )
    boxes = [_box("A", 1.0), _box("B", 999.0)]
    packer = BeamSearchPacker(pallet_dims=dims)

    packed, remaining = packer.pack(
        boxes,
        num_restarts=1,
        beam_width=2,
        candidate_limit=4,
        random_seed=1,
        target_mpm=192.0,
        target_policy=policy,
    )

    assert len(packed) == 1
    assert len(remaining) == 1
    assert {box["id"] for box in packed + remaining} == {"A", "B"}
    assert policy.is_reached(packed)


def test_beam_fill_mode_is_invariant_to_mpm_values():
    dims = PALLET_DIMS
    policy = make_target_policy(
        SuccessTarget(mode="fill_rate", threshold=0.50), 192.0, dims
    )

    def run(values):
        packer = BeamSearchPacker(pallet_dims=dims)
        packed, remaining = packer.pack(
            [_box("A", values[0]), _box("B", values[1])],
            num_restarts=1,
            beam_width=2,
            candidate_limit=4,
            random_seed=1,
            target_mpm=192.0,
            target_policy=policy,
        )
        return [box["id"] for box in packed], [box["id"] for box in remaining]

    assert run((1.0, 999.0)) == run((999.0, 1.0))
