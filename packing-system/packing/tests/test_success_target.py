import pytest

from src.main.success_target import SuccessTarget, apply_success_target
from src.main.result_formatter import ResultFormatter
from src.main.output_formatter import build_json_output_plan


def _report():
    return {
        "summary": {
            "overall": {
                "total_pallets": 2,
                "success_pallets": 1,
                "failed_pallets": 1,
                "unknown_pallets": 0,
            },
            "by_pallet_type": {
                "MH423C__ORDER-1": {
                    "pallet_type": "MH423C",
                    "sales_order_no": "ORDER-1",
                    "total_pallets": 2,
                    "success_pallets": 1,
                    "failed_pallets": 1,
                    "unknown_pallets": 0,
                }
            },
        },
        "pallets": [
            {
                "pallet_id": "MH423C-ORDER-1-1",
                "pallet_type": "MH423C",
                "sales_order_no": "ORDER-1",
                "mpm_status": "FAILED",
                "mpm_total": 180,
                "fill_rate": 0.75,
            },
            {
                "pallet_id": "MH423C-ORDER-1-2",
                "pallet_type": "MH423C",
                "sales_order_no": "ORDER-1",
                "mpm_status": "SUCCESS",
                "mpm_total": 200,
                "fill_rate": 0.749999,
            },
        ],
    }


def test_fill_rate_target_uses_inclusive_threshold_and_preserves_index_status():
    report = _report()

    apply_success_target(report, SuccessTarget(mode="fill_rate", threshold=0.75))

    first, second = report["pallets"]
    assert first["index_status"] == "FAILED"
    assert first["mpm_status"] == "SUCCESS"
    assert first["final_status"] == "SUCCESS"
    assert first["goal_value"] == 0.75
    assert second["index_status"] == "SUCCESS"
    assert second["mpm_status"] == "FAILED"
    assert second["final_status"] == "FAILED"
    assert report["success_target"] == {
        "mode": "fill_rate",
        "threshold": 0.75,
    }


def test_fill_rate_just_below_threshold_is_not_rounded_up_to_success():
    pallet_dims = {"length": 1000.0, "width": 1.0, "height": 1.0}
    plan = [{
        "pallet_id": "P1",
        "mpm_status": "FAILED",
        "mpm_total": 0.0,
        "packed_items": [{
            "id": 1,
            "length": 749.9996,
            "width": 1.0,
            "height": 1.0,
            "position": {"x": 0.0, "y": 0.0, "z": 0.0},
            "pallet_dims": pallet_dims,
        }],
    }]
    pallets = build_json_output_plan(plan, raw_boxes=[])
    report = {"summary": {"overall": {}}, "pallets": pallets}

    apply_success_target(
        report,
        SuccessTarget(mode="fill_rate", threshold=0.75),
    )

    assert pallets[0]["fill_rate"] == pytest.approx(0.7499996)
    assert pallets[0]["final_status"] == "FAILED"


def test_fill_rate_target_recomputes_overall_and_group_success_counts():
    report = _report()
    report["pallets"][1]["fill_rate"] = 0.80

    apply_success_target(report, SuccessTarget(mode="fill_rate", threshold=0.75))

    overall = report["summary"]["overall"]
    grouped = report["summary"]["by_pallet_type"]["MH423C__ORDER-1"]
    assert (overall["success_pallets"], overall["failed_pallets"]) == (2, 0)
    assert (grouped["success_pallets"], grouped["failed_pallets"]) == (2, 0)


def test_group_counts_keep_split_subgroups_separate():
    report = _report()
    report["summary"]["by_pallet_type"] = {
        "MH423C__ORDER-1": {
            "pallet_type": "MH423C",
            "sales_order_no": "ORDER-1",
        },
        "MH423C__ORDER-1__SPLITREST__": {
            "pallet_type": "MH423C",
            "sales_order_no": "ORDER-1",
        },
    }
    report["pallets"][0]["_summary_group_key"] = "MH423C__ORDER-1"
    report["pallets"][1]["_summary_group_key"] = (
        "MH423C__ORDER-1__SPLITREST__"
    )

    apply_success_target(report, SuccessTarget())

    grouped = report["summary"]["by_pallet_type"]
    assert grouped["MH423C__ORDER-1"]["total_pallets"] == 1
    assert grouped["MH423C__ORDER-1__SPLITREST__"]["total_pallets"] == 1
    assert all("_summary_group_key" not in pallet for pallet in report["pallets"])


def test_default_case_group_does_not_absorb_nonzero_case_group():
    report = _report()
    report["summary"]["by_pallet_type"] = {
        "zero": {
            "pallet_type": "MH423C",
            "sales_order_no": "ORDER-1",
            "case_group": 0,
        },
        "one": {
            "pallet_type": "MH423C",
            "sales_order_no": "ORDER-1",
            "case_group": "1",
        },
    }
    report["pallets"][0]["case_group"] = 0
    report["pallets"][1]["case_group"] = 1

    apply_success_target(report, SuccessTarget())

    grouped = report["summary"]["by_pallet_type"]
    assert grouped["zero"]["total_pallets"] == 1
    assert grouped["one"]["total_pallets"] == 1


def test_index_target_keeps_existing_success_decision():
    report = _report()

    apply_success_target(report, SuccessTarget(mode="index", threshold=192.0))

    assert [p["mpm_status"] for p in report["pallets"]] == ["FAILED", "SUCCESS"]
    assert [p["final_status"] for p in report["pallets"]] == ["FAILED", "SUCCESS"]
    assert [p["goal_value"] for p in report["pallets"]] == [180.0, 200.0]


def test_final_target_is_applied_before_robot_sequence_generation(monkeypatch):
    pallet = {
        "pallet_id": "MH423C-ORDER-1-1",
        "pallet_type": "MH423C",
        "sales_order_no": "ORDER-1",
        "mpm_status": "FAILED",
        "mpm_total": 180,
        "fill_rate": 0.75,
        "packed_items": [
            {
                "id": "BOX-1",
                "length": 100.0,
                "width": 100.0,
                "height": 100.0,
                "position": {"x": 0.0, "y": 0.0, "z": 0.0},
            }
        ],
    }
    monkeypatch.setattr(
        ResultFormatter, "validate_output_quality", staticmethod(lambda *_args: None)
    )
    monkeypatch.setattr(
        ResultFormatter, "validate_final_constraints", staticmethod(lambda *_args, **_kwargs: None)
    )

    report = ResultFormatter.build_full_report(
        [pallet],
        {"overall": {}, "by_pallet_type": {}},
        0.1,
        [],
        lambda _plans, _raw: [dict(pallet)],
        success_target=SuccessTarget(mode="fill_rate", threshold=0.75),
    )

    assert report["pallets"][0]["final_status"] == "SUCCESS"
    assert report["pallets"][0]["sequence_status"] != "SKIPPED_FAILED_PALLET"


def test_reapplying_fill_target_preserves_existing_true_index_status():
    report = _report()
    pallet = report["pallets"][0]
    pallet["index_status"] = "FAILED"
    pallet["mpm_status"] = "SUCCESS"
    pallet["fill_rate"] = 0.80

    apply_success_target(report, SuccessTarget(mode="fill_rate", threshold=0.75))

    assert pallet["index_status"] == "FAILED"
    assert pallet["final_status"] == "SUCCESS"


@pytest.mark.parametrize("threshold", [0.70, 0.75, 0.80, 0.85, 0.90])
def test_config_accepts_only_approved_fill_rate_steps(threshold):
    target = SuccessTarget.from_mapping(
        {"mode": "fill_rate", "threshold": threshold}
    )
    assert target == SuccessTarget(mode="fill_rate", threshold=threshold)


@pytest.mark.parametrize("threshold", [0.0, 0.74, 0.95, 70])
def test_config_rejects_unapproved_fill_rate_steps(threshold):
    with pytest.raises(ValueError, match="装载率目标"):
        SuccessTarget.from_mapping(
            {"mode": "fill_rate", "threshold": threshold}
        )

