from __future__ import annotations

from dataclasses import dataclass
import math

from .data import RobotAction


PHASES = (
    "READY",
    "PICK_DESCEND",
    "PICK_ATTACH",
    "LIFT",
    "TRANSFER",
    "PLACE_DESCEND",
    "RELEASE",
    "RETRACT",
)


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _smooth(value: float) -> float:
    value = _clamp(value)
    return value * value * (3.0 - 2.0 * value)


def _mix(start: float, end: float, fraction: float) -> float:
    return start + (end - start) * _smooth(fraction)


@dataclass(frozen=True)
class MotionPose:
    phase: str
    cup_x: float
    cup_y: float
    cup_z: float
    box_x: float
    box_y: float
    box_z: float
    yaw_deg: float
    box_attached: bool
    completed: bool = False

    @property
    def cup_xyz(self) -> tuple[float, float, float]:
        return self.cup_x, self.cup_y, self.cup_z

    @property
    def box_xyz(self) -> tuple[float, float, float]:
        return self.box_x, self.box_y, self.box_z


def conveyor_box_origin(
    action: RobotAction, pallet_length: float, pallet_width: float
) -> tuple[float, float, float]:
    camera = action.camera_data
    if (
        camera is not None
        and camera.x is not None
        and camera.y is not None
        and camera.z is not None
    ):
        return camera.x, camera.y, camera.z
    conveyor_y_center = (-1800.0 + -350.0) / 2.0
    return (
        max(0.0, (float(pallet_length) - action.box_size[0]) / 2.0),
        conveyor_y_center - action.box_size[1] / 2.0,
        action.pick_z - action.box_size[2],
    )


def _rotated_xy_bounds(
    x: float, y: float, length: float, width: float, yaw_deg: float
) -> tuple[float, float, float, float]:
    angle = math.radians(yaw_deg)
    cosine, sine = math.cos(angle), math.sin(angle)
    cx, cy = x + length / 2.0, y + width / 2.0
    points = [
        (
            cx + local_x * cosine - local_y * sine,
            cy + local_x * sine + local_y * cosine,
        )
        for local_x, local_y in (
            (-length / 2.0, -width / 2.0),
            (length / 2.0, -width / 2.0),
            (length / 2.0, width / 2.0),
            (-length / 2.0, width / 2.0),
        )
    ]
    xs, ys = zip(*points)
    return min(xs), max(xs), min(ys), max(ys)


def _pick_cup_center(
    action: RobotAction, box_origin: tuple[float, float, float]
) -> tuple[float, float]:
    """Align the selected current-bounds corner of the cup and box."""
    box_x, box_y, _ = box_origin
    length, width, _ = action.box_size
    box_yaw = action.conveyor_orientation_deg - action.target_orientation_deg
    box_x_min, box_x_max, box_y_min, _ = _rotated_xy_bounds(
        box_x, box_y, length, width, box_yaw
    )
    cup_x_min, cup_x_max, cup_y_min, _ = _rotated_xy_bounds(
        -300.0,
        -400.0,
        600.0,
        800.0,
        action.conveyor_orientation_deg,
    )
    box_anchor_x = box_x_max if action.pickup_point == "B" else box_x_min
    cup_anchor_x = cup_x_max if action.pickup_point == "B" else cup_x_min
    return (
        box_anchor_x - cup_anchor_x,
        box_y_min - cup_y_min,
    )


def _attached_box_xy(
    action: RobotAction,
    box_start: tuple[float, float, float],
    pick_cup_xy: tuple[float, float],
    cup_xy: tuple[float, float],
    yaw_deg: float,
) -> tuple[float, float]:
    """Rotate the original center offset so the same physical corners stay joined."""
    length, width, _ = action.box_size
    offset_x = box_start[0] + length / 2.0 - pick_cup_xy[0]
    offset_y = box_start[1] + width / 2.0 - pick_cup_xy[1]
    angle = math.radians(yaw_deg - action.conveyor_orientation_deg)
    rotated_x = offset_x * math.cos(angle) - offset_y * math.sin(angle)
    rotated_y = offset_x * math.sin(angle) + offset_y * math.cos(angle)
    return (
        cup_xy[0] + rotated_x - length / 2.0,
        cup_xy[1] + rotated_y - width / 2.0,
    )


def trajectory_pose(
    action: RobotAction,
    phase: str,
    fraction: float,
    pallet_length: float,
    pallet_width: float,
) -> MotionPose:
    """Return one deterministic frame of the conveyor-to-pallet motion."""
    if phase not in PHASES:
        raise ValueError(f"未知动画阶段：{phase}")
    t = _clamp(fraction)
    box_start = conveyor_box_origin(action, pallet_length, pallet_width)
    pick_cup_x, pick_cup_y = _pick_cup_center(action, box_start)
    target_box_x, target_box_y, target_box_z = action.box_place
    target_cup_x, target_cup_y, target_cup_z = action.suction_place
    box_height = action.box_size[2]
    safe_z = max(1250.0, action.pick_z + 550.0, target_cup_z + 550.0)
    motion_target_yaw = (
        float(action.conveyor_orientation_deg)
        if int(action.rotation_state) != 2
        else float(action.conveyor_orientation_deg - 90)
    )

    cup_x, cup_y, cup_z = pick_cup_x, pick_cup_y, safe_z
    box_x, box_y, box_z = box_start
    yaw = float(action.conveyor_orientation_deg)
    attached = False
    completed = False

    if phase == "PICK_DESCEND":
        cup_z = _mix(safe_z, action.pick_z, t)
    elif phase == "PICK_ATTACH":
        cup_z = action.pick_z
        attached = True
    elif phase == "LIFT":
        cup_z = _mix(action.pick_z, safe_z, t)
        box_x, box_y = _attached_box_xy(
            action,
            box_start,
            (pick_cup_x, pick_cup_y),
            (cup_x, cup_y),
            yaw,
        )
        box_z = _mix(box_start[2], safe_z - box_height, t)
        attached = True
    elif phase == "TRANSFER":
        cup_x = _mix(pick_cup_x, target_cup_x, t)
        cup_y = _mix(pick_cup_y, target_cup_y, t)
        box_z = safe_z - box_height
        yaw = _mix(action.conveyor_orientation_deg, motion_target_yaw, t)
        box_x, box_y = _attached_box_xy(
            action,
            box_start,
            (pick_cup_x, pick_cup_y),
            (cup_x, cup_y),
            yaw,
        )
        attached = True
    elif phase == "PLACE_DESCEND":
        cup_x, cup_y = target_cup_x, target_cup_y
        cup_z = _mix(safe_z, target_cup_z, t)
        box_x, box_y = _attached_box_xy(
            action,
            box_start,
            (pick_cup_x, pick_cup_y),
            (cup_x, cup_y),
            motion_target_yaw,
        )
        box_z = _mix(safe_z - box_height, target_box_z, t)
        yaw = motion_target_yaw
        attached = True
    elif phase == "RELEASE":
        cup_x, cup_y, cup_z = action.suction_place
        box_x, box_y, box_z = action.box_place
        yaw = motion_target_yaw
    elif phase == "RETRACT":
        cup_x, cup_y = target_cup_x, target_cup_y
        cup_z = _mix(target_cup_z, safe_z, t)
        box_x, box_y, box_z = action.box_place
        yaw = motion_target_yaw
        completed = t >= 1.0

    return MotionPose(
        phase=phase,
        cup_x=cup_x,
        cup_y=cup_y,
        cup_z=cup_z,
        box_x=box_x,
        box_y=box_y,
        box_z=box_z,
        yaw_deg=yaw,
        box_attached=attached,
        completed=completed,
    )
