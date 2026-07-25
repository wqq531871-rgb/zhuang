from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
from typing import Any, Iterable, Mapping

from .integration import CameraBoxData, plc_control
from .layout_state import STATE_PATH_CAMERA, normalize_state_path


def _number(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


@dataclass(frozen=True)
class PackedItem:
    id: str
    box_type: str
    length: float
    width: float
    height: float
    raw_length: float
    raw_width: float
    raw_height: float
    x: float
    y: float
    z: float
    box_corner: str
    cup_corner: str
    suction_orientation: str
    cup_x_size: float
    cup_y_size: float
    suction_x_min: float
    suction_x_max: float
    suction_y_min: float
    suction_y_max: float
    sequence: int
    sequence_source: str
    original: Mapping[str, Any] = field(repr=False, compare=False)


@dataclass(frozen=True)
class PalletPlan:
    source_key: str
    pallet_id: str
    pallet_type: str
    sales_order_no: str
    mpm_status: str
    sequence_status: str
    robot_verified: bool
    pallet_length: float
    pallet_width: float
    pallet_height: float
    items: tuple[PackedItem, ...]
    original: Mapping[str, Any] = field(repr=False, compare=False)


@dataclass(frozen=True)
class RobotAction:
    item_id: str
    box_type: str
    sequence: int
    sequence_source: str
    pick_z: float
    box_corner: str
    cup_corner: str
    box_place: tuple[float, float, float]
    suction_place: tuple[float, float, float]
    conveyor_orientation_deg: int
    target_orientation_deg: int
    rotation_deg: int
    box_size: tuple[float, float, float]
    cup_size: tuple[float, float]
    place_box_corner: str = "x_min_y_min"
    place_cup_corner: str = "x_min_y_min"
    camera_data: CameraBoxData | None = None
    rotation_state: int = 1
    pickup_point: str = "A"
    pickup_point_code: int = 1
    plc_ready: bool = False
    show_on_conveyor: bool = False
    db_state: int | None = None


def _sequence_key(raw: Mapping[str, Any], index: int) -> tuple[int, int]:
    seq = raw.get("seq")
    if seq is not None:
        return 0, int(seq)
    return 1, index


def _derive_suction_rect(
    raw: Mapping[str, Any], x: float, y: float, box_length: float, box_width: float
) -> tuple[float, float, float, float]:
    cup_x = _number(raw.get("suction_cup_x_size"), 600.0)
    cup_y = _number(raw.get("suction_cup_y_size"), 800.0)
    box_corner = str(raw.get("suction_box_corner") or "x_min_y_min")
    cup_corner = str(raw.get("suction_cup_corner") or box_corner)

    anchor_x = x + (box_length if "x_max" in box_corner else 0.0)
    anchor_y = y + (box_width if "y_max" in box_corner else 0.0)
    x_min = anchor_x - (cup_x if "x_max" in cup_corner else 0.0)
    y_min = anchor_y - (cup_y if "y_max" in cup_corner else 0.0)
    return x_min, x_min + cup_x, y_min, y_min + cup_y


def _parse_item(raw: Mapping[str, Any], index: int) -> PackedItem:
    position = raw.get("position") or {}
    x = _number(position.get("x"))
    y = _number(position.get("y"))
    z = _number(position.get("z"))
    length = _number(raw.get("length"), _number(raw.get("raw_length")))
    width = _number(raw.get("width"), _number(raw.get("raw_width")))
    height = _number(raw.get("height"), _number(raw.get("raw_height")))
    raw_length = _number(raw.get("raw_length"), length)
    raw_width = _number(raw.get("raw_width"), width)
    raw_height = _number(raw.get("raw_height"), height)
    derived = _derive_suction_rect(raw, x, y, length, width)
    key_bucket, sequence = _sequence_key(raw, index)
    source = ("seq", "array")[key_bucket]
    return PackedItem(
        id=str(raw.get("id") or f"box-{index + 1}"),
        box_type=str(raw.get("type") or raw.get("包装规格代码") or "UNKNOWN"),
        length=length,
        width=width,
        height=height,
        raw_length=raw_length,
        raw_width=raw_width,
        raw_height=raw_height,
        x=x,
        y=y,
        z=z,
        box_corner=str(raw.get("suction_box_corner") or "x_min_y_min"),
        cup_corner=str(raw.get("suction_cup_corner") or "x_min_y_min"),
        suction_orientation=str(raw.get("suction_orientation") or "cup_600x_800y"),
        cup_x_size=_number(raw.get("suction_cup_x_size"), 600.0),
        cup_y_size=_number(raw.get("suction_cup_y_size"), 800.0),
        suction_x_min=_number(raw.get("suction_rect_x_min"), derived[0]),
        suction_x_max=_number(raw.get("suction_rect_x_max"), derived[1]),
        suction_y_min=_number(raw.get("suction_rect_y_min"), derived[2]),
        suction_y_max=_number(raw.get("suction_rect_y_max"), derived[3]),
        sequence=sequence,
        sequence_source=source,
        original=raw,
    )


def _parse_plan(source_key: str, raw: Mapping[str, Any]) -> PalletPlan:
    raw_items = raw.get("packed_items")
    if not isinstance(raw_items, list):
        raise ValueError(f"托盘 {source_key} 缺少 packed_items 数组")
    indexed = list(enumerate(raw_items))
    indexed.sort(key=lambda pair: _sequence_key(pair[1], pair[0]))
    items = tuple(_parse_item(item, original_index) for original_index, item in indexed)
    dims = next(
        (item.get("pallet_dims") for item in raw_items if item.get("pallet_dims")),
        raw.get("pallet_dims") or {},
    )
    return PalletPlan(
        source_key=source_key,
        pallet_id=str(raw.get("pallet_id") or source_key),
        pallet_type=str(raw.get("pallet_type") or "UNKNOWN"),
        sales_order_no=str(raw.get("sales_order_no") or ""),
        mpm_status=str(raw.get("mpm_status") or "UNKNOWN").upper(),
        sequence_status=str(raw.get("sequence_status") or "UNKNOWN"),
        robot_verified=bool(raw.get("robot_verified", False)),
        pallet_length=_number(dims.get("length"), 1440.0),
        pallet_width=_number(dims.get("width"), 2240.0),
        pallet_height=_number(dims.get("height"), 720.0),
        items=items,
        original=raw,
    )


def normalize_document(data: Any) -> list[PalletPlan]:
    if not isinstance(data, Mapping):
        raise ValueError("JSON 根节点必须是对象")
    if isinstance(data.get("pallets"), list):
        candidates: Iterable[tuple[str, Mapping[str, Any]]] = (
            (str(index), value) for index, value in enumerate(data["pallets"])
        )
    else:
        candidates = (
            (str(key), value)
            for key, value in data.items()
            if isinstance(value, Mapping) and isinstance(value.get("packed_items"), list)
        )
    plans = [_parse_plan(key, value) for key, value in candidates]
    if not plans:
        raise ValueError("JSON 中没有找到有效的托盘方案")
    return plans


def load_plan_file(path: str | Path) -> list[PalletPlan]:
    path = Path(path)
    try:
        with path.open("r", encoding="utf-8-sig") as handle:
            data = json.load(handle)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ValueError(f"JSON 文件格式错误：{exc}") from exc
    except OSError as exc:
        raise ValueError(f"无法读取文件：{exc}") from exc
    return normalize_document(data)


def filter_plans(plans: Iterable[PalletPlan], status: str) -> list[PalletPlan]:
    wanted = status.upper()
    if wanted == "ALL":
        return list(plans)
    return [plan for plan in plans if plan.mpm_status == wanted]


def target_orientation(item: PackedItem) -> int:
    orientation = item.suction_orientation.lower()
    if "800x_600" in orientation:
        return 90
    if "600x_800" in orientation:
        return 0
    return 90 if item.cup_x_size > item.cup_y_size else 0


def pickup_corner(source_orientation: int, target_orientation_deg: int) -> str:
    """Map the semantic PLC A/B point to its agreed geometric corner."""
    return plc_control(source_orientation, target_orientation_deg).pickup_corner


def _positive_dim(value: Any) -> bool:
    try:
        return float(value) > 0
    except (TypeError, ValueError):
        return False


def item_camera_dims_complete(item: PackedItem) -> bool:
    original = item.original or {}
    return (
        _positive_dim(original.get("camera_length"))
        and _positive_dim(original.get("camera_width"))
        and _positive_dim(original.get("camera_height"))
    )


def item_state_ready(item: PackedItem) -> bool:
    state = (item.original or {}).get("state")
    try:
        return int(state) in (0, 1, 2)
    except (TypeError, ValueError):
        return False


def build_action(
    item: PackedItem,
    conveyor_orientation_deg: int,
    conveyor_z: float,
    camera_data: CameraBoxData | None = None,
    state_source: str = STATE_PATH_CAMERA,
) -> RobotAction:
    source = normalize_state_path(state_source)
    target = target_orientation(item)
    original = item.original or {}
    db_state_raw = original.get("state")
    try:
        db_state = int(db_state_raw) if db_state_raw is not None and db_state_raw != "" else None
    except (TypeError, ValueError):
        db_state = None

    # 优先用库中 state（相机 LWH 判定结果）；否则退回相机角 / 手动姿态
    if db_state in (1, 2):
        rotation_state = db_state
        conveyor_orientation = target if db_state == 1 else (90 if int(target) == 0 else 0)
        if camera_data is not None:
            camera_data = CameraBoxData(
                box_id=camera_data.box_id,
                orientation_deg=conveyor_orientation,
                x=camera_data.x,
                y=camera_data.y,
                z=camera_data.z,
                timestamp=camera_data.timestamp,
                confidence=camera_data.confidence,
            )
        else:
            camera_data = CameraBoxData(
                box_id=item.id, orientation_deg=conveyor_orientation
            )
        control = plc_control(conveyor_orientation, target)
    elif db_state == 0:
        rotation_state = 0
        conveyor_orientation = (
            camera_data.orientation_deg
            if camera_data is not None
            else int(conveyor_orientation_deg) % 180
        )
        if camera_data is None:
            camera_data = CameraBoxData(
                box_id=item.id, orientation_deg=int(conveyor_orientation)
            )
        control = plc_control(
            conveyor_orientation if conveyor_orientation in (0, 90) else 0,
            target,
        )
        # 异型：仍显示，但不按成功旋转语义覆盖
        rotation_state = 0
    else:
        conveyor_orientation = (
            camera_data.orientation_deg
            if camera_data is not None
            else int(conveyor_orientation_deg) % 180
        )
        control = plc_control(conveyor_orientation, target)
        rotation_state = control.rotation_state

    rotation = 90 if int(rotation_state) == 2 else 0
    corner = control.pickup_corner if int(rotation_state) in (1, 2) else "x_min_y_min"
    pickup_point = control.pickup_point if int(rotation_state) in (1, 2) else "A"
    pickup_code = control.pickup_point_code if int(rotation_state) in (1, 2) else 1
    target_cup_x_size, target_cup_y_size = (
        (600.0, 800.0) if target == 0 else (800.0, 600.0)
    )
    suction_x = item.x + target_cup_x_size / 2.0
    suction_y = item.y + target_cup_y_size / 2.0
    top_z = item.z + item.raw_height
    dims_ok = item_camera_dims_complete(item)
    state_ok = item_state_ready(item)
    dimensions_required = source == STATE_PATH_CAMERA
    show_on_conveyor = state_ok and (dims_ok or not dimensions_required)
    return RobotAction(
        item_id=item.id,
        box_type=item.box_type,
        sequence=item.sequence,
        sequence_source=item.sequence_source,
        pick_z=(
            float(camera_data.z) + item.raw_height
            if camera_data is not None and camera_data.z is not None
            else float(conveyor_z) + item.raw_height
        ),
        box_corner=corner,
        cup_corner=corner,
        box_place=(item.x, item.y, item.z),
        suction_place=(suction_x, suction_y, top_z),
        conveyor_orientation_deg=int(conveyor_orientation),
        target_orientation_deg=target,
        rotation_deg=rotation,
        box_size=(item.raw_length, item.raw_width, item.raw_height),
        cup_size=(600.0, 800.0),
        place_box_corner="x_min_y_min",
        place_cup_corner="x_min_y_min",
        camera_data=camera_data,
        rotation_state=int(rotation_state) if int(rotation_state) in (0, 1, 2) else 1,
        pickup_point=pickup_point,
        pickup_point_code=pickup_code,
        plc_ready=show_on_conveyor and int(rotation_state) in (1, 2),
        show_on_conveyor=show_on_conveyor,
        db_state=db_state,
    )


def action_to_dict(action: RobotAction) -> dict[str, Any]:
    box_x, box_y, box_z = action.box_place
    tcp_x, tcp_y, tcp_z = action.suction_place
    camera = action.camera_data
    return {
        "item_id": action.item_id,
        "box_type": action.box_type,
        "sequence": action.sequence,
        "sequence_source": action.sequence_source,
        "pickup": {
            "z": action.pick_z,
            "conveyor_orientation_deg": action.conveyor_orientation_deg,
            "box_corner": action.box_corner,
            "cup_corner": action.cup_corner,
        },
        "placement": {
            "box_origin": {"x": box_x, "y": box_y, "z": box_z},
            "suction_tcp_contact": {"x": tcp_x, "y": tcp_y, "z": tcp_z},
            "box_corner": action.place_box_corner,
            "cup_corner": action.place_cup_corner,
            "target_orientation_deg": action.target_orientation_deg,
            "rotation_deg": action.rotation_deg,
        },
        "camera": {
            "received": camera is not None,
            "box_id": camera.box_id if camera else None,
            "x": camera.x if camera else None,
            "y": camera.y if camera else None,
            "z": camera.z if camera else None,
            "orientation_deg": camera.orientation_deg if camera else None,
            "timestamp": camera.timestamp if camera else "",
            "confidence": camera.confidence if camera else None,
        },
        "plc": {
            "ready": action.plc_ready,
            "rotation_state": action.rotation_state,
            "pickup_point": action.pickup_point,
            "pickup_point_code": action.pickup_point_code,
        },
    }
