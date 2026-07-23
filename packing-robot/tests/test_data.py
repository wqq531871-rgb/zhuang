import json

import pytest

from packing_ui.data import (
    action_to_dict,
    build_action,
    filter_plans,
    load_plan_file,
    normalize_document,
)
from packing_ui.integration import CameraBoxData


def item(item_id="box-1", **overrides):
    data = {
        "id": item_id,
        "type": "A01",
        "length": 702.0,
        "width": 532.0,
        "height": 480.0,
        "raw_length": 700.0,
        "raw_width": 530.0,
        "raw_height": 480.0,
        "position": {"x": 100.0, "y": 200.0, "z": 240.0},
        "suction_box_corner": "x_min_y_min",
        "suction_cup_corner": "x_max_y_max",
        "suction_orientation": "cup_800x_600y",
        "suction_cup_x_size": 800.0,
        "suction_cup_y_size": 600.0,
        "suction_rect_x_min": 80.0,
        "suction_rect_x_max": 880.0,
        "suction_rect_y_min": 180.0,
        "suction_rect_y_max": 780.0,
        "seq": 2,
        "robot_packing_sequence": 2,
    }
    data.update(overrides)
    return data


def plan(pallet_id="P-1", status="SUCCESS", items=None):
    return {
        "pallet_id": pallet_id,
        "pallet_type": "MH423C",
        "sales_order_no": "SO-1",
        "mpm_status": status,
        "sequence_status": "GEOMETRICALLY_FEASIBLE",
        "robot_verified": False,
        "packed_items": items or [item()],
    }


def test_normalizes_map_root_and_orders_only_by_seq():
    later = item(
        "later", seq=9, robot_packing_sequence=1, original_packing_sequence=1
    )
    earlier = item(
        "earlier", seq=1, robot_packing_sequence=99, original_packing_sequence=99
    )

    plans = normalize_document({"opaque-key": plan(items=[later, earlier])})

    assert [box.id for box in plans[0].items] == ["earlier", "later"]
    assert plans[0].source_key == "opaque-key"


def test_normalizes_documented_pallets_array():
    plans = normalize_document({"packing_plan_id": None, "pallets": [plan()]})

    assert len(plans) == 1
    assert plans[0].pallet_id == "P-1"


def test_missing_seq_keeps_array_order_and_ignores_legacy_sequence_fields():
    boxes = [
        item("first", seq=None, robot_packing_sequence=99, original_packing_sequence=99),
        item("second", seq=None, robot_packing_sequence=1, original_packing_sequence=1),
    ]

    parsed = normalize_document({"k": plan(items=boxes)})[0]

    assert [box.id for box in parsed.items] == ["first", "second"]
    assert [box.sequence_source for box in parsed.items] == ["array", "array"]


def test_filters_status_case_insensitively_and_all_keeps_everything():
    plans = normalize_document(
        {"a": plan("P-1", "SUCCESS"), "b": plan("P-2", "FAILED")}
    )

    assert [p.pallet_id for p in filter_plans(plans, "success")] == ["P-1"]
    assert len(filter_plans(plans, "ALL")) == 2


def test_build_action_computes_pick_place_center_corners_and_rotation():
    parsed_item = normalize_document({"k": plan()})[0].items[0]

    action = build_action(parsed_item, conveyor_orientation_deg=0, conveyor_z=125.0)

    assert action.pick_z == pytest.approx(605.0)
    assert action.box_place == pytest.approx((100.0, 200.0, 240.0))
    assert action.suction_place == pytest.approx((500.0, 500.0, 720.0))
    assert action.box_corner == "x_max_y_min"
    assert action.cup_corner == "x_max_y_min"
    assert action.place_box_corner == "x_min_y_min"
    assert action.place_cup_corner == "x_min_y_min"
    assert action.target_orientation_deg == 90
    assert action.rotation_deg == 90


def test_rotation_is_zero_when_conveyor_matches_target():
    parsed_item = normalize_document({"k": plan()})[0].items[0]

    action = build_action(parsed_item, conveyor_orientation_deg=90, conveyor_z=0)

    assert action.rotation_deg == 0
    assert action.box_corner == "x_min_y_min"
    assert action.cup_corner == "x_min_y_min"


def test_reverse_quarter_turn_uses_b_pick_point_and_left_top_for_place():
    parsed_item = normalize_document(
        {"k": plan(items=[item(suction_orientation="cup_600x_800y")])}
    )[0].items[0]

    action = build_action(parsed_item, conveyor_orientation_deg=90, conveyor_z=0)

    assert action.rotation_deg == 90
    assert action.pickup_point == "B"
    assert action.box_corner == "x_max_y_min"
    assert action.cup_corner == "x_max_y_min"
    assert action.place_box_corner == "x_min_y_min"
    assert action.place_cup_corner == "x_min_y_min"
    assert action.suction_place == pytest.approx((400.0, 600.0, 720.0))


def test_action_to_dict_exposes_robot_output_contract():
    parsed_item = normalize_document({"k": plan()})[0].items[0]
    action = build_action(parsed_item, conveyor_orientation_deg=0, conveyor_z=125)

    output = action_to_dict(action)

    assert output["pickup"] == {
        "z": 605.0,
        "conveyor_orientation_deg": 0,
        "box_corner": "x_max_y_min",
        "cup_corner": "x_max_y_min",
    }
    assert output["placement"]["box_origin"] == {"x": 100.0, "y": 200.0, "z": 240.0}
    assert output["placement"]["box_corner"] == "x_min_y_min"
    assert output["placement"]["cup_corner"] == "x_min_y_min"
    assert output["placement"]["rotation_deg"] == 90
    assert output["plc"] == {
        "ready": False,
        "rotation_state": 2,
        "pickup_point": "B",
        "pickup_point_code": 2,
    }


def test_camera_data_overrides_manual_orientation_and_is_exported_for_plc():
    parsed_item = normalize_document({"k": plan()})[0].items[0]
    camera = CameraBoxData(
        box_id="box-1",
        x=420.0,
        y=-1100.0,
        z=5.0,
        orientation_deg=90,
        timestamp="2026-07-23T10:30:00+08:00",
        confidence=0.98,
    )

    action = build_action(
        parsed_item,
        conveyor_orientation_deg=0,
        conveyor_z=125,
        camera_data=camera,
    )
    output = action_to_dict(action)

    assert action.conveyor_orientation_deg == 90
    assert action.pick_z == pytest.approx(485.0)
    assert action.rotation_state == 1
    assert action.pickup_point == "A"
    assert action.pickup_point_code == 1
    assert action.plc_ready is True
    assert output["camera"] == {
        "received": True,
        "box_id": "box-1",
        "x": 420.0,
        "y": -1100.0,
        "z": 5.0,
        "orientation_deg": 90,
        "timestamp": "2026-07-23T10:30:00+08:00",
        "confidence": 0.98,
    }
    assert output["plc"] == {
        "ready": True,
        "rotation_state": 1,
        "pickup_point": "A",
        "pickup_point_code": 1,
    }


def test_load_plan_file_reports_invalid_json(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("{not-json", encoding="utf-8")

    with pytest.raises(ValueError, match="JSON"):
        load_plan_file(bad)


def test_load_plan_file_reads_utf8(tmp_path):
    path = tmp_path / "plan.json"
    path.write_text(json.dumps({"键": plan()}, ensure_ascii=False), encoding="utf-8")

    assert load_plan_file(path)[0].pallet_id == "P-1"
