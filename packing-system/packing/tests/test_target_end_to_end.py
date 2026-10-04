from run_packing import build_workflow
from src.config import ConstraintConfig
from src.main.report_persister import NullReportPersister
from src.main.success_target import SuccessTarget


PALLET = {"length": 1440.0, "width": 2240.0, "height": 720.0}


def _regular_boxes(count, mpm=1.0):
    return [
        {
            "id": f"B{i:03d}",
            "type": "REG",
            "length": 350.0,
            "width": 265.0,
            "height": 240.0,
            "volume": 350.0 * 265.0 * 240.0,
            "weight": 1.0,
            "min_pack_multiple": mpm,
            "pallet_type": "MH423C",
            "sales_order_no": "FILL-ONLY",
            "pallet_dims": PALLET,
        }
        for i in range(count)
    ]


def test_end_to_end_fill_mode_accepts_index_failure_and_conserves_boxes():
    boxes = _regular_boxes(84, mpm=1.0)
    workflow = build_workflow(
        constraint_config=ConstraintConfig(main_packer="gcp"),
        success_target=SuccessTarget(mode="fill_rate", threshold=0.80),
    )
    workflow._report_persister = NullReportPersister()

    report = workflow.run_with_boxes(boxes)

    output_ids = [
        item["id"]
        for pallet in report["pallets"]
        for item in pallet["packed_items"]
    ]
    assert sorted(output_ids) == sorted(box["id"] for box in boxes)
    assert len(output_ids) == len(set(output_ids))
    assert report["success_target"] == {"mode": "fill_rate", "threshold": 0.80}
    assert any(
        pallet["index_status"] == "FAILED"
        and pallet["final_status"] == "SUCCESS"
        for pallet in report["pallets"]
    )
    assert all(
        "_index_min_pack_multiple" not in item
        for pallet in report["pallets"]
        for item in pallet["packed_items"]
    )
