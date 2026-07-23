import pytest

from packing_ui.integration import (
    CameraBoxData,
    parse_camera_payload,
    plc_control,
)


def test_parse_camera_payload_accepts_single_box_object():
    boxes = parse_camera_payload(
        {
            "box_id": "BOX-001",
            "x": 420,
            "y": -1100,
            "z": 10,
            "orientation_deg": 90,
            "timestamp": "2026-07-23T10:30:00+08:00",
            "confidence": 0.98,
        }
    )

    assert boxes == [
        CameraBoxData(
            box_id="BOX-001",
            x=420.0,
            y=-1100.0,
            z=10.0,
            orientation_deg=90,
            timestamp="2026-07-23T10:30:00+08:00",
            confidence=0.98,
        )
    ]


def test_parse_camera_payload_accepts_boxes_array():
    boxes = parse_camera_payload(
        {
            "boxes": [
                {"box_id": "BOX-001", "orientation_deg": 0},
                {"box_id": "BOX-002", "orientation_deg": 90},
            ]
        }
    )

    assert [box.box_id for box in boxes] == ["BOX-001", "BOX-002"]


def test_parse_camera_payload_rejects_invalid_orientation():
    with pytest.raises(ValueError, match="0 或 90"):
        parse_camera_payload({"box_id": "BOX-001", "orientation_deg": 45})


@pytest.mark.parametrize(
    ("camera_deg", "target_deg", "state", "point", "code"),
    [
        (0, 0, 1, "A", 1),
        (90, 90, 1, "A", 1),
        (0, 90, 2, "B", 2),
        (90, 0, 2, "B", 2),
    ],
)
def test_plc_control_maps_orientation_to_state_and_ab_point(
    camera_deg, target_deg, state, point, code
):
    control = plc_control(camera_deg, target_deg)

    assert control.rotation_state == state
    assert control.pickup_point == point
    assert control.pickup_point_code == code
    assert control.pickup_corner == (
        "x_min_y_min" if point == "A" else "x_max_y_min"
    )
