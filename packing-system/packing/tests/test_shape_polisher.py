from copy import deepcopy

from src.main.shape_polisher import ShapePolisher, measure_shape_quality


PALLET = {"length": 20.0, "width": 20.0, "height": 20.0}


def _box(box_id, x, y, z=0.0, height=5.0):
    return {
        "id": box_id,
        "length": 10.0,
        "width": 10.0,
        "height": height,
        "raw_length": 10.0,
        "raw_width": 10.0,
        "raw_height": height,
        "position": {"x": x, "y": y, "z": z},
        "min_pack_multiple": 0.2,
        "pallet_dims": PALLET,
    }


def test_shape_quality_prefers_flat_compact_layout():
    compact = [
        _box("A", 0, 0),
        _box("B", 10, 0),
        _box("C", 0, 10),
        _box("D", 10, 10),
    ]
    ragged = [
        _box("A", 0, 0),
        _box("B", 10, 0),
        _box("C", 0, 0, z=5),
        _box("D", 0, 10, height=2),
    ]

    compact_quality = measure_shape_quality(compact)
    ragged_quality = measure_shape_quality(ragged)

    assert compact_quality["top_level_count"] == 1
    assert ragged_quality["top_level_count"] > 1
    assert compact_quality["rank"] > ragged_quality["rank"]


def test_polisher_accepts_only_an_improved_layout_with_same_boxes():
    original = [
        _box("A", 0, 0),
        _box("B", 10, 0),
        _box("C", 0, 0, z=5),
        _box("D", 0, 10, height=2),
    ]
    improved = [
        _box("A", 0, 0),
        _box("B", 10, 0),
        _box("C", 0, 10),
        _box("D", 10, 10),
    ]
    plan = {"packed_items": deepcopy(original), "mpm_status": "SUCCESS"}

    polisher = ShapePolisher(
        enabled=True,
        seconds_per_pallet=1.0,
        repack_fn=lambda items, dims, deadline: deepcopy(improved),
        validate_fn=lambda candidate, dims: True,
    )
    diagnostics = polisher.polish_plans([plan])

    assert [item["id"] for item in plan["packed_items"]] == ["A", "B", "C", "D"]
    assert plan["packed_items"][2]["position"] == {"x": 0, "y": 10, "z": 0.0}
    assert plan["mpm_status"] == "SUCCESS"
    assert plan["shape_quality"]["polish_applied"] is True
    assert diagnostics["improved"] == 1


def test_polisher_never_changes_success_for_worse_or_nonconserving_candidate():
    original = [_box("A", 0, 0), _box("B", 10, 0)]
    original_positions = [deepcopy(item["position"]) for item in original]
    plan = {"packed_items": deepcopy(original), "mpm_status": "SUCCESS"}

    polisher = ShapePolisher(
        enabled=True,
        seconds_per_pallet=1.0,
        repack_fn=lambda items, dims, deadline: [_box("A", 0, 0)],
        validate_fn=lambda candidate, dims: True,
    )
    polisher.polish_plans([plan])

    assert [item["position"] for item in plan["packed_items"]] == original_positions
    assert plan["mpm_status"] == "SUCCESS"
    assert plan["shape_quality"]["polish_applied"] is False


def test_polisher_skips_failed_pallets():
    items = [_box("A", 0, 0)]
    called = []
    plan = {"packed_items": deepcopy(items), "mpm_status": "FAILED"}
    polisher = ShapePolisher(
        repack_fn=lambda *args: called.append(True),
        validate_fn=lambda *args: True,
    )

    diagnostics = polisher.polish_plans([plan])

    assert called == []
    assert diagnostics["attempted"] == 0


def test_polisher_failure_keeps_original_successful_plan():
    items = [_box("A", 0, 0), _box("B", 10, 0, height=2)]
    plan = {"packed_items": deepcopy(items), "mpm_status": "SUCCESS"}

    def broken_repack(*args):
        raise RuntimeError("search failed")

    polisher = ShapePolisher(repack_fn=broken_repack)
    diagnostics = polisher.polish_plans([plan])

    assert plan["packed_items"] == items
    assert plan["mpm_status"] == "SUCCESS"
    assert plan["shape_quality"]["polish_applied"] is False
    assert plan["shape_quality"]["polish_reason"] == "search_error"
    assert diagnostics["improved"] == 0
