import math
from dataclasses import replace

import pytest

from packing_ui.animation import PHASES, trajectory_pose
from packing_ui.data import RobotAction
from packing_ui.integration import CameraBoxData
from packing_ui.playback import PlaybackController
from packing_ui.scene import oriented_cuboid_points


@pytest.fixture
def action():
    return RobotAction(
        item_id="box-1",
        box_type="A01",
        sequence=1,
        sequence_source="seq",
        pick_z=500.0,
        box_corner="x_max_y_min",
        cup_corner="x_max_y_min",
        box_place=(100.0, 200.0, 240.0),
        suction_place=(500.0, 500.0, 720.0),
        conveyor_orientation_deg=0,
        target_orientation_deg=90,
        rotation_deg=90,
        box_size=(700.0, 530.0, 480.0),
        cup_size=(800.0, 600.0),
        rotation_state=2,
        pickup_point="B",
        pickup_point_code=2,
    )


def test_animation_has_complete_pick_transfer_place_sequence():
    assert PHASES == (
        "READY",
        "PICK_DESCEND",
        "PICK_ATTACH",
        "LIFT",
        "TRANSFER",
        "PLACE_DESCEND",
        "RELEASE",
        "RETRACT",
    )


def test_ready_generates_box_on_conveyor_below_x_axis_in_negative_y(action):
    pose = trajectory_pose(
        action, "READY", 0.0, pallet_length=1440, pallet_width=2240
    )

    assert 0 <= pose.box_x <= 1440
    assert pose.box_y + max(action.box_size[0], action.box_size[1]) < 0
    assert pose.box_z == pytest.approx(action.pick_z - action.box_size[2])
    assert pose.cup_z > action.pick_z
    assert pose.box_attached is False


def test_ready_uses_camera_xyz_instead_of_nominal_conveyor_origin(action):
    camera_action = replace(
        action,
        pick_z=485.0,
        camera_data=CameraBoxData(
            box_id="box-1",
            x=420.0,
            y=-1100.0,
            z=5.0,
            orientation_deg=0,
        ),
        plc_ready=True,
    )

    pose = trajectory_pose(
        camera_action, "READY", 0.0, pallet_length=1440, pallet_width=2240
    )

    assert pose.box_xyz == pytest.approx((420.0, -1100.0, 5.0))


def test_pick_descend_reaches_box_top_without_attaching(action):
    pose = trajectory_pose(
        action, "PICK_DESCEND", 1.0, pallet_length=1440, pallet_width=2240
    )

    assert pose.cup_z == pytest.approx(action.pick_z)
    assert pose.box_attached is False


@pytest.mark.parametrize(
    "pick_action",
    [
        pytest.param(None, id="B-x_max_y_min"),
        pytest.param("A", id="A-x_min_y_min"),
    ],
)
def test_selected_box_and_cup_ab_bounds_are_exactly_aligned(action, pick_action):
    if pick_action == "A":
        action = replace(
            action,
            conveyor_orientation_deg=0,
            target_orientation_deg=0,
            rotation_deg=0,
            rotation_state=1,
            pickup_point="A",
            pickup_point_code=1,
            box_corner="x_min_y_min",
            cup_corner="x_min_y_min",
            suction_place=(400.0, 600.0, 720.0),
        )
    pose = trajectory_pose(
        action, "PICK_DESCEND", 1.0, pallet_length=1440, pallet_width=2240
    )
    box_points = oriented_cuboid_points(
        pose.box_x,
        pose.box_y,
        pose.box_z,
        *action.box_size,
        pose.yaw_deg - action.target_orientation_deg,
    )
    cup_points = oriented_cuboid_points(
        pose.cup_x - 300.0,
        pose.cup_y - 400.0,
        pose.cup_z,
        600.0,
        800.0,
        50.0,
        pose.yaw_deg,
    )

    def selected_corner(points):
        xs = [point[0] for point in points]
        ys = [point[1] for point in points]
        return (
            max(xs) if action.pickup_point == "B" else min(xs),
            min(ys),
        )

    assert selected_corner(box_points) == pytest.approx(
        selected_corner(cup_points)
    )


def test_transfer_reaches_target_xy_and_target_yaw_above_pallet(action):
    pose = trajectory_pose(
        action, "TRANSFER", 1.0, pallet_length=1440, pallet_width=2240
    )

    assert pose.box_x == pytest.approx(action.box_place[0])
    assert pose.box_y == pytest.approx(action.box_place[1])
    assert pose.box_z > action.box_place[2]
    assert pose.yaw_deg == pytest.approx(-90)
    assert pose.yaw_deg % 180 == action.target_orientation_deg
    assert pose.box_attached is True


def test_transfer_keeps_the_same_physical_box_and_cup_corner_attached(action):
    start = trajectory_pose(
        action, "TRANSFER", 0.0, pallet_length=1440, pallet_width=2240
    )
    middle = trajectory_pose(
        action, "TRANSFER", 0.5, pallet_length=1440, pallet_width=2240
    )
    start_offset = (
        start.box_x + action.box_size[0] / 2.0 - start.cup_x,
        start.box_y + action.box_size[1] / 2.0 - start.cup_y,
    )
    middle_offset = (
        middle.box_x + action.box_size[0] / 2.0 - middle.cup_x,
        middle.box_y + action.box_size[1] / 2.0 - middle.cup_y,
    )
    angle = math.radians(middle.yaw_deg - start.yaw_deg)
    expected = (
        start_offset[0] * math.cos(angle) - start_offset[1] * math.sin(angle),
        start_offset[0] * math.sin(angle) + start_offset[1] * math.cos(angle),
    )

    assert middle_offset == pytest.approx(expected)


def test_place_descend_finishes_at_json_target(action):
    pose = trajectory_pose(
        action, "PLACE_DESCEND", 1.0, pallet_length=1440, pallet_width=2240
    )

    assert pose.box_xyz == pytest.approx(action.box_place)
    assert pose.cup_xyz == pytest.approx(action.suction_place)
    assert pose.box_attached is True


def test_reverse_rotation_with_b_point_finishes_at_json_target(action):
    reverse = replace(
        action,
        conveyor_orientation_deg=90,
        target_orientation_deg=0,
        rotation_deg=90,
        rotation_state=2,
        pickup_point="B",
        pickup_point_code=2,
        box_corner="x_max_y_min",
        cup_corner="x_max_y_min",
        suction_place=(400.0, 600.0, 720.0),
    )

    pose = trajectory_pose(
        reverse, "PLACE_DESCEND", 1.0, pallet_length=1440, pallet_width=2240
    )

    assert pose.box_xyz == pytest.approx(reverse.box_place)
    assert pose.cup_xyz == pytest.approx(reverse.suction_place)


def test_release_leaves_box_and_retract_lifts_only_suction(action):
    released = trajectory_pose(
        action, "RELEASE", 1.0, pallet_length=1440, pallet_width=2240
    )
    retracted = trajectory_pose(
        action, "RETRACT", 1.0, pallet_length=1440, pallet_width=2240
    )

    assert released.box_attached is False
    assert retracted.box_xyz == pytest.approx(action.box_place)
    assert retracted.cup_z > action.suction_place[2]
    assert retracted.completed is True


def test_playback_controller_seeks_resets_and_advances_phases(action):
    controller = PlaybackController()
    controller.set_actions([action, action])

    assert controller.step_count == 2
    assert controller.phase == "READY"
    controller.advance(1.0)
    assert controller.phase == "PICK_DESCEND"
    controller.next_step()
    assert controller.current_step_index == 1
    controller.seek_step(99)
    assert controller.current_step_index == 1
    controller.reset()
    assert (controller.current_step_index, controller.phase, controller.fraction) == (
        0,
        "READY",
        0.0,
    )
