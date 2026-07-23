from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True)
class CameraBoxData:
    box_id: str
    orientation_deg: int
    x: float | None = None
    y: float | None = None
    z: float | None = None
    timestamp: str = ""
    confidence: float | None = None


@dataclass(frozen=True)
class PlcControl:
    rotation_state: int
    pickup_point: str
    pickup_point_code: int
    pickup_corner: str


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"相机坐标或置信度不是有效数值：{value!r}") from exc


def _parse_camera_box(raw: Mapping[str, Any]) -> CameraBoxData:
    box_id = str(raw.get("box_id") or raw.get("id") or "").strip()
    if not box_id:
        raise ValueError("相机数据缺少 box_id")
    try:
        orientation = int(raw.get("orientation_deg"))
    except (TypeError, ValueError) as exc:
        raise ValueError("相机姿态必须为 0 或 90") from exc
    if orientation not in (0, 90):
        raise ValueError("相机姿态必须为 0 或 90")
    return CameraBoxData(
        box_id=box_id,
        orientation_deg=orientation,
        x=_optional_float(raw.get("x")),
        y=_optional_float(raw.get("y")),
        z=_optional_float(raw.get("z")),
        timestamp=str(raw.get("timestamp") or ""),
        confidence=_optional_float(raw.get("confidence")),
    )


def parse_camera_payload(data: Any) -> list[CameraBoxData]:
    if isinstance(data, Mapping):
        raw_boxes = data.get("boxes")
        if raw_boxes is None:
            raw_boxes = [data]
    elif isinstance(data, list):
        raw_boxes = data
    else:
        raise ValueError("相机 JSON 根节点必须是对象或数组")
    if not isinstance(raw_boxes, list) or not raw_boxes:
        raise ValueError("相机 JSON 中没有箱子数据")
    if not all(isinstance(raw, Mapping) for raw in raw_boxes):
        raise ValueError("相机 boxes 中的每一项必须是对象")
    return [_parse_camera_box(raw) for raw in raw_boxes]


def plc_control(camera_orientation_deg: int, target_orientation_deg: int) -> PlcControl:
    camera = int(camera_orientation_deg)
    target = int(target_orientation_deg)
    if camera not in (0, 90) or target not in (0, 90):
        raise ValueError("相机姿态和目标姿态必须为 0 或 90")
    needs_rotation = camera != target
    return PlcControl(
        rotation_state=2 if needs_rotation else 1,
        pickup_point="B" if needs_rotation else "A",
        pickup_point_code=2 if needs_rotation else 1,
        pickup_corner="x_max_y_min" if needs_rotation else "x_min_y_min",
    )
