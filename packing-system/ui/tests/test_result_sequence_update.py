import json
from pathlib import Path

from result_sequence_update import (
    apply_seq_values,
    find_pallet_in_plan,
    result_triplet_paths,
    rewrite_result_triplet_for_pallet,
)


def test_result_triplet_paths_from_packing_plan():
    plan, wcs, wcs_map = result_triplet_paths(Path("output/packing_plan_20260721_155026.json"))
    assert plan.name == "packing_plan_20260721_155026.json"
    assert wcs.name == "wcs_plan_20260721_155026.json"
    assert wcs_map.name == "wcs_plan_map_20260721_155026.json"


def test_result_triplet_paths_from_execution_report():
    plan, wcs, wcs_map = result_triplet_paths(
        Path("output/packing_plan_20260721_155026_execution.json")
    )
    assert plan.name == "packing_plan_20260721_155026_execution.json"
    assert wcs.name == "packing_plan_20260721_155026_execution_wcs.json"
    assert wcs_map.name == "packing_plan_20260721_155026_execution_wcs_map.json"


def test_apply_seq_values_only_changes_seq_not_array_order():
    pallet = {
        "packed_items": [
            {"id": "A", "seq": 1},
            {"id": "B", "seq": 2},
            {"id": "C", "seq": 3},
        ]
    }
    applied = apply_seq_values(pallet, ["C", "A", "B"])
    assert [item["id"] for item in pallet["packed_items"]] == ["A", "B", "C"]
    assert [item["seq"] for item in pallet["packed_items"]] == [2, 3, 1]
    assert applied == {"C": 1, "A": 2, "B": 3}


def _sample_item(box_id: str, seq: int, z: float = 0.0) -> dict:
    return {
        "id": box_id,
        "seq": seq,
        "product_code": seq,
        "position": {"x": 0, "y": 0, "z": z},
        "original_length": 10,
        "original_width": 10,
        "original_height": 10,
    }


def test_rewrite_only_patches_seq_for_one_pallet(tmp_path):
    plan_path = tmp_path / "packing_plan_20260721_120000.json"
    wcs_path = tmp_path / "wcs_plan_20260721_120000.json"
    map_path = tmp_path / "wcs_plan_map_20260721_120000.json"

    pallet_a = {
        "pallet_id": "P1",
        "sales_order_no": "SO1",
        "pallet_type": "MH",
        "mpm_status": "SUCCESS",
        "packed_items": [_sample_item("A", 1), _sample_item("B", 2, z=10)],
    }
    pallet_b = {
        "pallet_id": "P2",
        "sales_order_no": "SO2",
        "pallet_type": "MH",
        "mpm_status": "SUCCESS",
        "packed_items": [_sample_item("X", 1), _sample_item("Y", 2, z=10)],
    }
    # plan_data holds a *different dict* with same key — must still update by match
    plan_pallet_a = {
        "pallet_id": "P1",
        "sales_order_no": "SO1",
        "pallet_type": "MH",
        "mpm_status": "SUCCESS",
        "packed_items": [_sample_item("A", 1), _sample_item("B", 2, z=10)],
    }
    plan_data = {"pallets": [plan_pallet_a, pallet_b]}
    wcs_path.write_text(
        json.dumps(
            [
                {
                    "box_index": 1,
                    "box_unique_id": "uid-a",
                    "layers": [{"cartons": [{"seq": 1}, {"seq": 2}]}],
                    "marker": "old-a",
                },
                {
                    "box_index": 2,
                    "box_unique_id": "uid-b",
                    "layers": [{"cartons": [{"seq": 1}, {"seq": 2}]}],
                    "marker": "keep-me",
                },
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    map_path.write_text(
        json.dumps(
            {
                "uid-a": {
                    "pallet_id": "P1",
                    "sales_order_no": "SO1",
                    "pallet_type": "MH",
                    "packed_items": [_sample_item("A", 1), _sample_item("B", 2, z=10)],
                },
                "uid-b": pallet_b,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    def fake_build_layers(items):
        ordered = sorted(items, key=lambda it: int(it.get("seq") or 0))
        return (
            [
                {
                    "cartons": [
                        {"seq": int(it["seq"]), "product_code": it["product_code"]}
                        for it in ordered
                    ]
                }
            ],
            20.0,
        )

    written_plan, written_wcs, written_map, applied = rewrite_result_triplet_for_pallet(
        plan_path,
        plan_data,
        pallet_a,  # different object from plan_data["pallets"][0]
        ["B", "A"],
        build_layers=fake_build_layers,
    )

    assert applied == {"B": 1, "A": 2}
    assert find_pallet_in_plan(plan_data, pallet_a) is plan_pallet_a

    saved_plan = json.loads(written_plan.read_text(encoding="utf-8"))
    items_a = saved_plan["pallets"][0]["packed_items"]
    assert [it["id"] for it in items_a] == ["A", "B"]  # array order unchanged
    assert [it["seq"] for it in items_a] == [2, 1]
    assert [it["seq"] for it in saved_plan["pallets"][1]["packed_items"]] == [1, 2]

    saved_wcs = json.loads(written_wcs.read_text(encoding="utf-8"))
    assert saved_wcs[0]["box_unique_id"] == "uid-a"
    assert [c["seq"] for c in saved_wcs[0]["layers"][0]["cartons"]] == [1, 2]
    assert saved_wcs[1]["marker"] == "keep-me"

    saved_map = json.loads(written_map.read_text(encoding="utf-8"))
    assert [it["seq"] for it in saved_map["uid-a"]["packed_items"]] == [2, 1]
    assert [it["id"] for it in saved_map["uid-b"]["packed_items"]] == ["X", "Y"]
