"""Plan a robot-safe, centered execution layout from a packing report."""

from __future__ import annotations

import heapq
import logging
import math
import time
from collections import deque
from copy import deepcopy
from dataclasses import dataclass
from typing import Dict, List, Optional, Set, Tuple

from .approach_geometry import (
    MovingRectPath,
    moving_path_blocked,
    preposition_descent_blocked,
)


_ORIGINS = {
    "x_min_y_min",
    "x_min_y_max",
    "x_max_y_min",
    "x_max_y_max",
}
_ROBOT_REFERENCES = _ORIGINS | {"x_min", "x_max", "y_min", "y_max"}
STACK_HEIGHT_BEFORE_FIELD = "stack_height_before"
_LOGGER = logging.getLogger(__name__)


class ExecutionSequenceError(ValueError):
    """Raised when a pallet cannot be converted to a valid execution order."""


class _ExecutionSequenceDeadlineExceeded(RuntimeError):
    pass


def _check_deadline(deadline: Optional[float]) -> None:
    if deadline is not None and time.monotonic() >= deadline:
        raise _ExecutionSequenceDeadlineExceeded


@dataclass(frozen=True)
class ExecutionSequenceConfig:
    """Execution-order preferences and geometric tolerances."""

    origin: str = "x_min_y_min"
    coordinate_tolerance_mm: float = 1e-6
    box_xy_clearance_mm: float = 0.0
    suction_xy_clearance_mm: float = 0.0
    suction_z_clearance_mm: float = 0.0
    approach_offset_x_mm: float = 35.0
    approach_offset_y_mm: float = 35.0
    approach_z_clearance_mm: float = 0.0
    approach_box_xy_clearance_mm: float = 0.0
    approach_suction_xy_clearance_mm: float = 2.0
    require_suction_pose: bool = True
    max_occupied_directions: int = 2
    side_neighbor_clearance_mm: float = 5.0
    side_height_tolerance_mm: float = 2.0
    preserve_open_direction: bool = True
    max_sequence_search_seconds_per_pallet: float = 1.0
    scan_column_tolerance_mm: float = 5.0

    def __post_init__(self) -> None:
        if self.origin not in _ORIGINS:
            raise ValueError(
                "origin must be one of: %s" % ", ".join(sorted(_ORIGINS))
            )
        numeric_clearances = {
            "coordinate_tolerance_mm": self.coordinate_tolerance_mm,
            "box_xy_clearance_mm": self.box_xy_clearance_mm,
            "suction_xy_clearance_mm": self.suction_xy_clearance_mm,
            "suction_z_clearance_mm": self.suction_z_clearance_mm,
            "approach_offset_x_mm": self.approach_offset_x_mm,
            "approach_offset_y_mm": self.approach_offset_y_mm,
            "approach_z_clearance_mm": self.approach_z_clearance_mm,
            "approach_box_xy_clearance_mm": (
                self.approach_box_xy_clearance_mm
            ),
            "approach_suction_xy_clearance_mm": (
                self.approach_suction_xy_clearance_mm
            ),
            "side_neighbor_clearance_mm": self.side_neighbor_clearance_mm,
            "side_height_tolerance_mm": self.side_height_tolerance_mm,
            "max_sequence_search_seconds_per_pallet": (
                self.max_sequence_search_seconds_per_pallet
            ),
            "scan_column_tolerance_mm": self.scan_column_tolerance_mm,
        }
        for name, value in numeric_clearances.items():
            if isinstance(value, bool):
                raise ValueError("%s must be a finite number" % name)
            try:
                numeric = float(value)
            except (TypeError, ValueError, OverflowError) as exc:
                raise ValueError("%s must be a finite number" % name) from exc
            if not math.isfinite(numeric):
                raise ValueError("%s must be finite" % name)
            if numeric < 0:
                raise ValueError("%s must be non-negative" % name)
            object.__setattr__(self, name, numeric)
        if not isinstance(self.preserve_open_direction, bool):
            raise ValueError("preserve_open_direction must be a boolean")
        if not isinstance(self.require_suction_pose, bool):
            raise ValueError("require_suction_pose must be a boolean")
        if (
            isinstance(self.max_occupied_directions, bool)
            or not isinstance(self.max_occupied_directions, int)
            or not 0 <= self.max_occupied_directions <= 4
        ):
            raise ValueError("max_occupied_directions must be an integer from 0 to 4")
        if self.max_sequence_search_seconds_per_pallet <= 0:
            raise ValueError(
                "max_sequence_search_seconds_per_pallet must be positive"
            )


def _number(item: Dict, key: str) -> float:
    try:
        value = float(item[key])
    except (KeyError, TypeError, ValueError) as exc:
        raise ExecutionSequenceError("invalid or missing %s" % key) from exc
    if not math.isfinite(value):
        raise ExecutionSequenceError("%s must be finite" % key)
    return value


def _geometry(item: Dict) -> Tuple[float, float, float, float, float, float]:
    pos = item.get("position")
    if not isinstance(pos, dict):
        raise ExecutionSequenceError(
            "box %r is missing position" % item.get("id")
        )
    x = _number(pos, "x")
    y = _number(pos, "y")
    z = _number(pos, "z")
    length = _number(item, "length")
    width = _number(item, "width")
    height = _number(item, "height")
    if min(length, width, height) <= 0:
        raise ExecutionSequenceError(
            "box %r has non-positive dimensions" % item.get("id")
        )
    return x, y, z, length, width, height


def _physical_dimension(item: Dict, axis: str) -> float:
    value = item.get(
        "original_%s" % axis,
        item.get("raw_%s" % axis, item.get(axis)),
    )
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ExecutionSequenceError(
            "box %r has invalid physical %s" % (item.get("id"), axis)
        ) from exc
    if not math.isfinite(result):
        raise ExecutionSequenceError(
            "box %r physical %s must be finite" % (item.get("id"), axis)
        )
    if result <= 0:
        raise ExecutionSequenceError(
            "box %r has non-positive physical %s" % (item.get("id"), axis)
        )
    return result


def _physical_geometry(
    item: Dict,
) -> Tuple[float, float, float, float, float, float]:
    x, y, z, _length, _width, _height = _geometry(item)
    return (
        x,
        y,
        z,
        _physical_dimension(item, "length"),
        _physical_dimension(item, "width"),
        _physical_dimension(item, "height"),
    )


def _axis_overlap(a_min: float, a_max: float, b_min: float, b_max: float) -> float:
    return max(0.0, min(a_max, b_max) - max(a_min, b_min))


def _rect(item: Dict, clearance: float = 0.0) -> Tuple[float, float, float, float]:
    x, y, _z, length, width, _height = _physical_geometry(item)
    return (
        x - clearance,
        x + length + clearance,
        y - clearance,
        y + width + clearance,
    )


def _suction_rect(
    item: Dict,
    clearance: float,
    require: bool,
) -> Optional[Tuple[float, float, float, float]]:
    names = (
        "suction_rect_x_min",
        "suction_rect_x_max",
        "suction_rect_y_min",
        "suction_rect_y_max",
    )
    if any(item.get(name) is None for name in names):
        if require:
            raise ExecutionSequenceError(
                "box %r is missing suction rectangle" % item.get("id")
            )
        return None
    try:
        x_min, x_max, y_min, y_max = (float(item[name]) for name in names)
    except (TypeError, ValueError) as exc:
        raise ExecutionSequenceError(
            "box %r has invalid suction rectangle" % item.get("id")
        ) from exc
    if not all(math.isfinite(value) for value in (x_min, x_max, y_min, y_max)):
        raise ExecutionSequenceError(
            "box %r suction rectangle values must be finite" % item.get("id")
        )
    if x_max <= x_min or y_max <= y_min:
        raise ExecutionSequenceError(
            "box %r has invalid suction rectangle" % item.get("id")
        )
    return (
        x_min - clearance,
        x_max + clearance,
        y_min - clearance,
        y_max + clearance,
    )


def _rects_overlap(
    first: Tuple[float, float, float, float],
    second: Tuple[float, float, float, float],
    tolerance: float,
) -> bool:
    return (
        _axis_overlap(first[0], first[1], second[0], second[1]) > tolerance
        and _axis_overlap(first[2], first[3], second[2], second[3]) > tolerance
    )


def _add_edge(
    edges: List[Set[int]], indegree: List[int], source: int, target: int
) -> None:
    if source == target or target in edges[source]:
        return
    edges[source].add(target)
    indegree[target] += 1


def _support_edges(
    items: List[Dict], tolerance: float
) -> Tuple[List[Set[int]], List[int], List[Set[int]]]:
    edges: List[Set[int]] = [set() for _ in items]
    indegree = [0 for _ in items]
    supports: List[Set[int]] = [set() for _ in items]
    geometry = [_physical_geometry(item) for item in items]

    for target_idx, target in enumerate(geometry):
        tx, ty, tz, tl, tw, _th = target
        if tz <= tolerance:
            continue
        for support_idx, support in enumerate(geometry):
            if support_idx == target_idx:
                continue
            sx, sy, sz, sl, sw, sh = support
            if abs((sz + sh) - tz) > tolerance:
                continue
            if _axis_overlap(tx, tx + tl, sx, sx + sl) <= tolerance:
                continue
            if _axis_overlap(ty, ty + tw, sy, sy + sw) <= tolerance:
                continue
            supports[target_idx].add(support_idx)
            _add_edge(edges, indegree, support_idx, target_idx)
        if not supports[target_idx]:
            raise ExecutionSequenceError(
                "box %r has no direct support" % items[target_idx].get("id")
            )
    return edges, indegree, supports


def _add_clearance_edges(
    items: List[Dict],
    config: ExecutionSequenceConfig,
    edges: List[Set[int]],
    indegree: List[int],
) -> None:
    tolerance = config.coordinate_tolerance_mm
    geometry = [_physical_geometry(item) for item in items]
    blocker_rects = [_rect(item) for item in items]
    box_sweeps = [
        _rect(item, config.box_xy_clearance_mm) for item in items
    ]
    suction_sweeps = [
        _suction_rect(
            item,
            config.suction_xy_clearance_mm,
            config.require_suction_pose,
        )
        for item in items
    ]

    for target_idx, target in enumerate(geometry):
        _tx, _ty, target_bottom, _tl, _tw, target_height = target
        target_top = target_bottom + target_height
        for blocker_idx, blocker in enumerate(geometry):
            if blocker_idx == target_idx:
                continue
            _bx, _by, blocker_bottom, _bl, _bw, blocker_height = blocker
            blocker_top = blocker_bottom + blocker_height
            box_blocked = (
                _rects_overlap(
                    box_sweeps[target_idx], blocker_rects[blocker_idx], tolerance
                )
                and blocker_top > target_bottom + tolerance
            )
            suction_sweep = suction_sweeps[target_idx]
            suction_blocked = (
                suction_sweep is not None
                and _rects_overlap(
                    suction_sweep, blocker_rects[blocker_idx], tolerance
                )
                and blocker_top
                > target_top - config.suction_z_clearance_mm + tolerance
            )
            if box_blocked or suction_blocked:
                _add_edge(edges, indegree, target_idx, blocker_idx)


@dataclass(frozen=True)
class _ApproachPaths:
    box: MovingRectPath
    box_final_descent: MovingRectPath
    suction: Optional[MovingRectPath]


@dataclass(frozen=True)
class _ApproachBlocker:
    rect: Tuple[float, float, float, float]
    z_min: float
    z_max: float


def _approach_pallet_height(
    items: List[Dict], pallet_dims: Optional[Dict[str, float]]
) -> float:
    dims = _pallet_dims(items) if pallet_dims is None else pallet_dims
    try:
        height = float(dims["height"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ExecutionSequenceError(
            "approach geometry requires a finite positive pallet height"
        ) from exc
    if not math.isfinite(height) or height <= 0:
        raise ExecutionSequenceError(
            "approach geometry requires a finite positive pallet height"
        )
    return height


def _approach_paths(
    items: List[Dict],
    config: ExecutionSequenceConfig,
    pallet_dims: Optional[Dict[str, float]],
    deadline: Optional[float] = None,
) -> List[_ApproachPaths]:
    pallet_height = _approach_pallet_height(items, pallet_dims)
    result = []
    for item in items:
        _check_deadline(deadline)
        target_id = item.get("id")
        try:
            _x, _y, target_bottom, _length, _width, target_height = (
                _physical_geometry(item)
            )
            box_z_min = target_bottom + config.approach_z_clearance_mm
            box_z_max = box_z_min + target_height
            if not all(math.isfinite(value) for value in (box_z_min, box_z_max)):
                raise ValueError("box approach Z interval must be finite")
            box_path = MovingRectPath(
                final_rect=_rect(item),
                offset_x=config.approach_offset_x_mm,
                offset_y=config.approach_offset_y_mm,
                z_min=box_z_min,
                z_max=box_z_max,
            )
            box_final_descent_path = MovingRectPath(
                final_rect=_rect(item),
                offset_x=0.0,
                offset_y=0.0,
                z_min=target_bottom,
                z_max=box_z_max,
            )

            suction_path = None
            suction_rect = _suction_rect(
                item, 0.0, config.require_suction_pose
            )
            if suction_rect is not None:
                suction_z_min = (
                    target_bottom
                    + target_height
                    + config.approach_z_clearance_mm
                    - config.suction_z_clearance_mm
                )
                if not math.isfinite(suction_z_min):
                    raise ValueError("suction approach Z interval must be finite")
                if (
                    suction_z_min
                    < pallet_height - config.coordinate_tolerance_mm
                ):
                    suction_path = MovingRectPath(
                        final_rect=suction_rect,
                        offset_x=config.approach_offset_x_mm,
                        offset_y=config.approach_offset_y_mm,
                        z_min=suction_z_min,
                        z_max=pallet_height,
                    )
        except ValueError as exc:
            raise ExecutionSequenceError(
                "box %r has invalid derived approach geometry: %s"
                % (target_id, exc)
            ) from exc
        result.append(
            _ApproachPaths(
                box=box_path,
                box_final_descent=box_final_descent_path,
                suction=suction_path,
            )
        )
    return result


def _approach_blockers(
    items: List[Dict], deadline: Optional[float] = None
) -> List[_ApproachBlocker]:
    result = []
    for item in items:
        _check_deadline(deadline)
        _x, _y, z_min, _length, _width, height = _physical_geometry(item)
        z_max = z_min + height
        if not math.isfinite(z_max):
            raise ExecutionSequenceError(
                "box %r has invalid derived approach blocker geometry"
                % item.get("id")
            )
        result.append(
            _ApproachBlocker(rect=_rect(item), z_min=z_min, z_max=z_max)
        )
    return result


def _approach_blocking_phase(
    target_id,
    target_paths: _ApproachPaths,
    blocker_id,
    blocker: _ApproachBlocker,
    config: ExecutionSequenceConfig,
) -> Optional[str]:
    paths = (
        ("box", target_paths.box, config.approach_box_xy_clearance_mm),
        (
            "suction",
            target_paths.suction,
            config.approach_suction_xy_clearance_mm,
        ),
    )
    try:
        for label, path, clearance in paths:
            if path is None:
                continue
            if preposition_descent_blocked(
                path,
                blocker.rect,
                blocker.z_max,
                clearance,
                config.coordinate_tolerance_mm,
            ):
                return "%s pre-position descent" % label
            if moving_path_blocked(
                path,
                blocker.rect,
                blocker.z_min,
                blocker.z_max,
                clearance,
                config.coordinate_tolerance_mm,
            ):
                return "%s diagonal approach" % label
            if label == "box" and moving_path_blocked(
                target_paths.box_final_descent,
                blocker.rect,
                blocker.z_min,
                blocker.z_max,
                config.approach_box_xy_clearance_mm,
                config.coordinate_tolerance_mm,
            ):
                return "box final descent"
    except ValueError as exc:
        raise ExecutionSequenceError(
            "invalid approach geometry for target %r against blocker %r: %s"
            % (target_id, blocker_id, exc)
        ) from exc
    return None


def _add_approach_edges(
    items: List[Dict],
    config: ExecutionSequenceConfig,
    edges: List[Set[int]],
    indegree: List[int],
    pallet_dims: Optional[Dict[str, float]] = None,
    deadline: Optional[float] = None,
) -> None:
    target_paths = _approach_paths(items, config, pallet_dims, deadline)
    blockers = _approach_blockers(items, deadline)
    for target_idx, paths in enumerate(target_paths):
        _check_deadline(deadline)
        for blocker_idx, blocker in enumerate(blockers):
            _check_deadline(deadline)
            if blocker_idx == target_idx:
                continue
            phase = _approach_blocking_phase(
                items[target_idx].get("id"),
                paths,
                items[blocker_idx].get("id"),
                blocker,
                config,
            )
            if phase is not None:
                _add_edge(edges, indegree, target_idx, blocker_idx)


def _assert_approach_replay_safe(
    items: List[Dict],
    ordered_indices: List[int],
    config: ExecutionSequenceConfig,
    pallet_dims: Optional[Dict[str, float]] = None,
    deadline: Optional[float] = None,
) -> None:
    target_paths = _approach_paths(items, config, pallet_dims, deadline)
    blockers = _approach_blockers(items, deadline)
    placed: Set[int] = set()
    for target_idx in ordered_indices:
        _check_deadline(deadline)
        for blocker_idx in placed:
            _check_deadline(deadline)
            phase = _approach_blocking_phase(
                items[target_idx].get("id"),
                target_paths[target_idx],
                items[blocker_idx].get("id"),
                blockers[blocker_idx],
                config,
            )
            if phase is not None:
                raise ExecutionSequenceError(
                    "box %r approach is blocked by box %r during %s"
                    % (
                        items[target_idx].get("id"),
                        items[blocker_idx].get("id"),
                        phase,
                    )
                )
        placed.add(target_idx)


def _assert_replay_safe(
    items: List[Dict],
    ordered_indices: List[int],
    supports: List[Set[int]],
    config: ExecutionSequenceConfig,
) -> None:
    placed: Set[int] = set()
    tolerance = config.coordinate_tolerance_mm
    for target_idx in ordered_indices:
        if not supports[target_idx].issubset(placed):
            raise ExecutionSequenceError(
                "box %r is scheduled before its direct support"
                % items[target_idx].get("id")
            )
        target = items[target_idx]
        _x, _y, target_bottom, _l, _w, target_height = _physical_geometry(target)
        target_top = target_bottom + target_height
        box_sweep = _rect(target, config.box_xy_clearance_mm)
        suction_sweep = _suction_rect(
            target,
            config.suction_xy_clearance_mm,
            config.require_suction_pose,
        )
        for blocker_idx in placed:
            blocker = items[blocker_idx]
            _bx, _by, blocker_bottom, _bl, _bw, blocker_height = (
                _physical_geometry(blocker)
            )
            blocker_top = blocker_bottom + blocker_height
            blocker_rect = _rect(blocker)
            if (
                _rects_overlap(box_sweep, blocker_rect, tolerance)
                and blocker_top > target_bottom + tolerance
            ):
                raise ExecutionSequenceError(
                    "box %r has a blocked vertical box path" % target.get("id")
                )
            if (
                suction_sweep is not None
                and _rects_overlap(suction_sweep, blocker_rect, tolerance)
                and blocker_top
                > target_top - config.suction_z_clearance_mm + tolerance
            ):
                raise ExecutionSequenceError(
                    "box %r has a blocked suction path" % target.get("id")
                )
        placed.add(target_idx)


def _pallet_dims(items: List[Dict]) -> Dict[str, float]:
    for item in items:
        dims = item.get("pallet_dims")
        if isinstance(dims, dict):
            try:
                result = {
                    "length": float(dims["length"]),
                    "width": float(dims["width"]),
                    "height": float(dims["height"]),
                }
            except (KeyError, TypeError, ValueError):
                break
            if not all(math.isfinite(value) and value > 0 for value in result.values()):
                break
            return result
    raise ExecutionSequenceError("boxes require finite positive pallet_dims")


def _validate_bounds(
    items: List[Dict],
    pallet_dims: Dict[str, float],
    tolerance: float,
) -> None:
    for item in items:
        x, y, z, length, width, height = _physical_geometry(item)
        inside = (
            x >= -tolerance
            and y >= -tolerance
            and z >= -tolerance
            and x + length <= pallet_dims["length"] + tolerance
            and y + width <= pallet_dims["width"] + tolerance
            and z + height <= pallet_dims["height"] + tolerance
        )
        if not inside:
            raise ExecutionSequenceError(
                "box %r is outside pallet bounds" % item.get("id")
            )


def _axis_center_shift(
    minimum: float,
    maximum: float,
    pallet_size: float,
    tolerance: float,
) -> float:
    remaining = pallet_size - (maximum - minimum)
    if remaining <= tolerance:
        return 0.0
    near_margin = minimum
    far_margin = pallet_size - maximum
    shift = (far_margin - near_margin) / 2.0
    return 0.0 if abs(shift) <= tolerance else shift


def _center_layout_in_place(
    items: List[Dict],
    pallet_dims: Dict[str, float],
    tolerance: float,
) -> None:
    if not items:
        return
    geometry = [_physical_geometry(item) for item in items]
    min_x = min(entry[0] for entry in geometry)
    max_x = max(entry[0] + entry[3] for entry in geometry)
    min_y = min(entry[1] for entry in geometry)
    max_y = max(entry[1] + entry[4] for entry in geometry)
    shift_x = _axis_center_shift(
        min_x, max_x, pallet_dims["length"], tolerance
    )
    shift_y = _axis_center_shift(
        min_y, max_y, pallet_dims["width"], tolerance
    )
    if shift_x == 0.0 and shift_y == 0.0:
        return
    for item in items:
        position = item["position"]
        position["x"] = float(position["x"]) + shift_x
        position["y"] = float(position["y"]) + shift_y
        suction_names = (
            "suction_rect_x_min",
            "suction_rect_x_max",
            "suction_rect_y_min",
            "suction_rect_y_max",
        )
        if all(item.get(name) is not None for name in suction_names):
            item["suction_rect_x_min"] = (
                float(item["suction_rect_x_min"]) + shift_x
            )
            item["suction_rect_x_max"] = (
                float(item["suction_rect_x_max"]) + shift_x
            )
            item["suction_rect_y_min"] = (
                float(item["suction_rect_y_min"]) + shift_y
            )
            item["suction_rect_y_max"] = (
                float(item["suction_rect_y_max"]) + shift_y
            )


def _robot_depth(
    item: Dict,
    pallet_dims: Dict[str, float],
    reference: str,
) -> float:
    x, y, _z, length, width, _height = _physical_geometry(item)
    center_x = x + length / 2.0
    center_y = y + width / 2.0
    x_from_min = min(1.0, max(0.0, center_x / pallet_dims["length"]))
    x_from_max = min(
        1.0,
        max(0.0, (pallet_dims["length"] - center_x) / pallet_dims["length"]),
    )
    y_from_min = min(1.0, max(0.0, center_y / pallet_dims["width"]))
    y_from_max = min(
        1.0,
        max(0.0, (pallet_dims["width"] - center_y) / pallet_dims["width"]),
    )
    if reference == "x_min":
        return x_from_min
    if reference == "x_max":
        return x_from_max
    if reference == "y_min":
        return y_from_min
    if reference == "y_max":
        return y_from_max
    x_depth = x_from_min if reference.startswith("x_min") else x_from_max
    y_depth = y_from_min if reference.endswith("y_min") else y_from_max
    return min(1.0, math.hypot(x_depth, y_depth) / math.sqrt(2.0))


def _refresh_robot_depth_fields(
    items: List[Dict],
    pallet: Dict,
    pallet_dims: Dict[str, float],
    default_reference: str,
) -> None:
    if not any(
        "robot_depth" in item or "robot_depth_band" in item
        for item in items
    ):
        return
    try:
        band_count = max(1, int(pallet.get("depth_band_count", 4)))
    except (TypeError, ValueError) as exc:
        raise ExecutionSequenceError("invalid depth_band_count") from exc
    pallet_reference = str(
        pallet.get("robot_reference") or default_reference
    )
    for item in items:
        reference = str(item.get("robot_reference") or pallet_reference)
        if reference not in _ROBOT_REFERENCES:
            raise ExecutionSequenceError(
                "unsupported robot_reference=%r" % reference
            )
        depth = _robot_depth(item, pallet_dims, reference)
        if "robot_depth" in item:
            item["robot_depth"] = round(depth, 9)
        if "robot_depth_band" in item:
            item["robot_depth_band"] = min(
                band_count - 1, int(depth * band_count)
            )


def _assert_final_execution_layout(
    items: List[Dict],
    config: ExecutionSequenceConfig,
    deadline: Optional[float] = None,
) -> None:
    pallet_dims = _pallet_dims(items)
    _validate_bounds(items, pallet_dims, config.coordinate_tolerance_mm)
    edges, indegree, supports = _support_edges(
        items, config.coordinate_tolerance_mm
    )
    _add_clearance_edges(items, config, edges, indegree)
    _add_approach_edges(
        items, config, edges, indegree, pallet_dims, deadline=deadline
    )
    for source_idx, targets in enumerate(edges):
        if any(source_idx >= target_idx for target_idx in targets):
            raise ExecutionSequenceError(
                "centered execution layout violates dependency order"
            )
    ordered_indices = list(range(len(items)))
    _assert_replay_safe(items, ordered_indices, supports, config)
    _assert_approach_replay_safe(
        items,
        ordered_indices,
        config,
        pallet_dims,
        deadline=deadline,
    )
    if config.preserve_open_direction:
        geometry = [_physical_geometry(item) for item in items]
        blockers = _direction_blocker_map(geometry, config)
        _assert_open_direction_replay(
            items, ordered_indices, config, blockers
        )


def _annotate_stack_height_before(items: List[Dict]) -> None:
    stack_height = 0.0
    for item in items:
        item[STACK_HEIGHT_BEFORE_FIELD] = stack_height
        _x, _y, z, _length, _width, height = _physical_geometry(item)
        stack_height = max(stack_height, z + height)


def _origin_progress(
    entry: Tuple[float, float, float, float, float, float],
    origin: str,
    pallet_dims: Dict[str, float],
) -> Tuple[float, float]:
    x, y, _z, length, width, _height = entry
    x_progress = (
        x
        if origin.startswith("x_min")
        else pallet_dims["length"] - (x + length)
    )
    y_progress = (
        y
        if origin.endswith("y_min")
        else pallet_dims["width"] - (y + width)
    )
    return x_progress, y_progress


def _coordinate_ranks(
    geometry: List[Tuple[float, float, float, float, float, float]],
    config: ExecutionSequenceConfig,
    pallet_dims: Dict[str, float],
    deadline: Optional[float] = None,
) -> List[Tuple[int, int]]:
    progress = []
    for entry in geometry:
        _check_deadline(deadline)
        progress.append(_origin_progress(entry, config.origin, pallet_dims))

    ranks_by_axis: List[List[int]] = []
    for axis in (0, 1):
        other_axis = 1 - axis
        ranks = [0] * len(geometry)
        rank = -1
        cluster_anchor: Optional[float] = None
        for idx in sorted(
            range(len(geometry)),
            key=lambda value: (
                progress[value][axis],
                progress[value][other_axis],
                value,
            ),
        ):
            _check_deadline(deadline)
            coordinate = progress[idx][axis]
            if (
                cluster_anchor is None
                or coordinate - cluster_anchor
                > config.scan_column_tolerance_mm
            ):
                rank += 1
                cluster_anchor = coordinate
            ranks[idx] = rank
        ranks_by_axis.append(ranks)

    return [
        (ranks_by_axis[0][idx], ranks_by_axis[1][idx])
        for idx in range(len(geometry))
    ]


def _side_directions_between(
    target: Tuple[float, float, float, float, float, float],
    blocker: Tuple[float, float, float, float, float, float],
    config: ExecutionSequenceConfig,
    include_lower: bool = False,
) -> Set[str]:
    tx, ty, target_bottom, tl, tw, target_height = target
    target_top = target_bottom + target_height
    target_x_max = tx + tl
    target_y_max = ty + tw
    tolerance = config.coordinate_tolerance_mm
    clearance = config.side_neighbor_clearance_mm
    bx, by, blocker_bottom, bl, bw, bh = blocker
    blocker_top = blocker_bottom + bh
    if include_lower:
        if blocker_top <= target_bottom + tolerance:
            return set()
    elif (
        blocker_top
        < target_top - config.side_height_tolerance_mm - tolerance
    ):
        return set()
    blocker_x_max = bx + bl
    blocker_y_max = by + bw
    y_overlap = _axis_overlap(ty, target_y_max, by, blocker_y_max)
    x_overlap = _axis_overlap(tx, target_x_max, bx, blocker_x_max)
    x_minus_gap = tx - blocker_x_max
    x_plus_gap = bx - target_x_max
    y_minus_gap = ty - blocker_y_max
    y_plus_gap = by - target_y_max
    directions: Set[str] = set()
    if y_overlap > tolerance:
        if -tolerance <= x_minus_gap <= clearance + tolerance:
            directions.add("x-")
        if -tolerance <= x_plus_gap <= clearance + tolerance:
            directions.add("x+")
    if x_overlap > tolerance:
        if -tolerance <= y_minus_gap <= clearance + tolerance:
            directions.add("y-")
        if -tolerance <= y_plus_gap <= clearance + tolerance:
            directions.add("y+")
    return directions


def _direction_blocker_map(
    geometry: List[Tuple[float, float, float, float, float, float]],
    config: ExecutionSequenceConfig,
    include_lower: bool = False,
    deadline: Optional[float] = None,
) -> List[Dict[str, Set[int]]]:
    result: List[Dict[str, Set[int]]] = [
        {"x-": set(), "x+": set(), "y-": set(), "y+": set()}
        for _ in geometry
    ]
    for target_idx, target in enumerate(geometry):
        _check_deadline(deadline)
        for blocker_idx, blocker in enumerate(geometry):
            _check_deadline(deadline)
            if target_idx == blocker_idx:
                continue
            for direction in _side_directions_between(
                target,
                blocker,
                config,
                include_lower=include_lower,
            ):
                result[target_idx][direction].add(blocker_idx)
    return result


def _occupied_from_blocker_map(
    target_idx: int,
    present: Set[int],
    blockers: List[Dict[str, Set[int]]],
) -> Set[str]:
    return {
        direction
        for direction, indices in blockers[target_idx].items()
        if not indices.isdisjoint(present)
    }


def _assert_open_direction_replay(
    items: List[Dict],
    ordered_indices: List[int],
    config: ExecutionSequenceConfig,
    blockers: List[Dict[str, Set[int]]],
) -> None:
    placed: Set[int] = set()
    for target_idx in ordered_indices:
        occupied = _occupied_from_blocker_map(
            target_idx, placed, blockers
        )
        if len(occupied) > config.max_occupied_directions:
            raise ExecutionSequenceError(
                "box %r is enclosed from %d directions: %s"
                % (
                    items[target_idx].get("id"),
                    len(occupied),
                    ",".join(sorted(occupied)),
                )
            )
        placed.add(target_idx)


def _predecessor_map(
    edges: List[Set[int]], deadline: Optional[float]
) -> List[Set[int]]:
    predecessors: List[Set[int]] = [set() for _targets in edges]
    for source_idx, targets in enumerate(edges):
        _check_deadline(deadline)
        for target_idx in targets:
            _check_deadline(deadline)
            predecessors[target_idx].add(source_idx)
    return predecessors


def _blocker_dependents(
    blockers: List[Dict[str, Set[int]]],
    deadline: Optional[float],
) -> List[List[Tuple[int, str]]]:
    dependents: List[List[Tuple[int, str]]] = [
        [] for _target in blockers
    ]
    for target_idx, direction_map in enumerate(blockers):
        _check_deadline(deadline)
        for direction, blocker_indices in direction_map.items():
            _check_deadline(deadline)
            for blocker_idx in blocker_indices:
                _check_deadline(deadline)
                dependents[blocker_idx].append((target_idx, direction))
    return dependents


def _residual_can_complete(
    prefix: Set[int],
    residual: Set[int],
    edges: List[Set[int]],
    predecessors: List[Set[int]],
    config: ExecutionSequenceConfig,
    blockers: List[Dict[str, Set[int]]],
    blocker_dependents: List[List[Tuple[int, str]]],
    preference_rank: List[int],
    deadline: Optional[float],
) -> bool:
    """Return whether residual boxes can be peeled back to the fixed prefix."""

    _check_deadline(deadline)
    if not residual:
        return True
    remaining = set(residual)
    present = prefix.union(remaining)
    successor_count: Dict[int, int] = {}
    direction_counts: Dict[int, Dict[str, int]] = {}
    occupied_count: Dict[int, int] = {}
    for idx in remaining:
        _check_deadline(deadline)
        successor_count[idx] = len(edges[idx].intersection(remaining))
        counts: Dict[str, int] = {}
        for direction, blocker_indices in blockers[idx].items():
            _check_deadline(deadline)
            counts[direction] = len(blocker_indices.intersection(present))
        direction_counts[idx] = counts
        occupied_count[idx] = sum(count > 0 for count in counts.values())

    eligible: List[Tuple[int, int]] = []
    queued: Set[int] = set()

    def enqueue_if_eligible(idx: int) -> None:
        if (
            idx in remaining
            and idx not in queued
            and successor_count[idx] == 0
            and occupied_count[idx] <= config.max_occupied_directions
        ):
            heapq.heappush(eligible, (-preference_rank[idx], idx))
            queued.add(idx)

    for idx in remaining:
        _check_deadline(deadline)
        enqueue_if_eligible(idx)

    while remaining:
        _check_deadline(deadline)
        if not eligible:
            return False
        _rank, removed_idx = heapq.heappop(eligible)
        remaining.remove(removed_idx)

        for predecessor_idx in predecessors[removed_idx]:
            _check_deadline(deadline)
            if predecessor_idx not in remaining:
                continue
            successor_count[predecessor_idx] -= 1
            enqueue_if_eligible(predecessor_idx)

        for target_idx, direction in blocker_dependents[removed_idx]:
            _check_deadline(deadline)
            if target_idx not in remaining:
                continue
            previous = direction_counts[target_idx][direction]
            direction_counts[target_idx][direction] = previous - 1
            if previous == 1:
                occupied_count[target_idx] -= 1
            enqueue_if_eligible(target_idx)
    return True


def _stable_forward_order(
    items: List[Dict],
    edges: List[Set[int]],
    config: ExecutionSequenceConfig,
    forward_keys: List[Tuple],
    blockers: Optional[List[Dict[str, Set[int]]]],
    deadline: Optional[float],
    pallet_id=None,
) -> Optional[List[int]]:
    """Choose the lexicographically earliest completable forward schedule."""

    if len(forward_keys) != len(items):
        raise ValueError("forward_keys must match items length")
    _check_deadline(deadline)
    predecessors = _predecessor_map(edges, deadline)
    preference_order = sorted(
        range(len(items)), key=lambda idx: forward_keys[idx]
    )
    preference_rank = [0] * len(items)
    for rank, idx in enumerate(preference_order):
        _check_deadline(deadline)
        preference_rank[idx] = rank

    blocker_dependencies: Optional[List[List[Tuple[int, str]]]] = None
    if config.preserve_open_direction:
        if blockers is None:
            raise ValueError("blockers are required when preserving open direction")
        blocker_dependencies = _blocker_dependents(blockers, deadline)

    placed: Set[int] = set()
    remaining = set(range(len(items)))
    ordered: List[int] = []
    deviations: List[Tuple[int, int, str, bool]] = []
    deviation_keys: Set[Tuple[int, str, bool]] = set()
    while remaining:
        _check_deadline(deadline)
        selected_idx: Optional[int] = None
        first_rejected: Optional[Tuple[int, str, bool]] = None
        for candidate_idx in preference_order:
            _check_deadline(deadline)
            if candidate_idx not in remaining:
                continue
            if not predecessors[candidate_idx].issubset(placed):
                if first_rejected is None:
                    first_rejected = (
                        candidate_idx,
                        "hard_dependency",
                        False,
                    )
                continue
            if config.preserve_open_direction:
                occupied = _occupied_from_blocker_map(
                    candidate_idx, placed, blockers
                )
                if len(occupied) > config.max_occupied_directions:
                    if first_rejected is None:
                        first_rejected = (
                            candidate_idx,
                            "open_direction",
                            False,
                        )
                    continue
                next_prefix = placed.union({candidate_idx})
                next_residual = remaining.difference({candidate_idx})
                if not _residual_can_complete(
                    next_prefix,
                    next_residual,
                    edges,
                    predecessors,
                    config,
                    blockers,
                    blocker_dependencies,
                    preference_rank,
                    deadline,
                ):
                    if first_rejected is None:
                        first_rejected = (
                            candidate_idx,
                            "open_direction",
                            True,
                        )
                    continue
            selected_idx = candidate_idx
            break

        if selected_idx is None:
            return None
        if first_rejected is not None:
            expected_idx, reason, lookahead = first_rejected
            deviation_key = (expected_idx, reason, lookahead)
            if deviation_key not in deviation_keys:
                deviation_keys.add(deviation_key)
                deviations.append(
                    (expected_idx, selected_idx, reason, lookahead)
                )
        remaining.remove(selected_idx)
        placed.add(selected_idx)
        ordered.append(selected_idx)
    if deviations:
        preview_entries = []
        for expected_idx, selected_idx, reason, lookahead in deviations[:8]:
            expected_id = items[expected_idx].get("id")
            selected_id = items[selected_idx].get("id")
            preview_entries.append(
                "expected=%r selected=%r box=%r after=%r reason=%s%s"
                % (
                    expected_id,
                    selected_id,
                    expected_id,
                    selected_id,
                    reason,
                    " lookahead=true" if lookahead else "",
                )
            )
        _LOGGER.warning(
            "execution scan deviations pallet=%r count=%d: %s%s",
            pallet_id,
            len(deviations),
            "; ".join(preview_entries),
            "; ..." if len(deviations) > 8 else "",
        )
    return ordered


def _support_tiers(
    supports: List[Set[int]], deadline: Optional[float] = None
) -> List[int]:
    item_count = len(supports)
    dependents: List[List[int]] = [[] for _support in supports]
    unresolved_support_counts = [0] * item_count

    for target_idx, direct_supports in enumerate(supports):
        _check_deadline(deadline)
        validated_supports = []
        for support_idx in direct_supports:
            _check_deadline(deadline)
            if (
                isinstance(support_idx, bool)
                or not isinstance(support_idx, int)
                or not 0 <= support_idx < item_count
            ):
                raise ExecutionSequenceError(
                    "support dependency index %r for box %d is out of range"
                    % (support_idx, target_idx)
                )
            validated_supports.append(support_idx)
        unresolved_support_counts[target_idx] = len(validated_supports)
        for support_idx in sorted(validated_supports):
            _check_deadline(deadline)
            dependents[support_idx].append(target_idx)

    ready = deque()
    for idx, unresolved_count in enumerate(unresolved_support_counts):
        _check_deadline(deadline)
        if unresolved_count == 0:
            ready.append(idx)

    tiers = [0] * item_count
    resolved_count = 0
    while ready:
        _check_deadline(deadline)
        support_idx = ready.popleft()
        resolved_count += 1
        for target_idx in dependents[support_idx]:
            _check_deadline(deadline)
            tiers[target_idx] = max(
                tiers[target_idx], tiers[support_idx] + 1
            )
            unresolved_support_counts[target_idx] -= 1
            if unresolved_support_counts[target_idx] == 0:
                ready.append(target_idx)

    _check_deadline(deadline)
    if resolved_count != item_count:
        raise ExecutionSequenceError(
            "support dependency graph contains a cycle"
        )
    return tiers


def _directed_wave_keys(
    geometry: List[Tuple[float, float, float, float, float, float]],
    supports: List[Set[int]],
    config: ExecutionSequenceConfig,
    pallet_dims: Dict[str, float],
    deadline: Optional[float] = None,
) -> List[Tuple[int, int, int, int, int, int]]:
    coordinate_ranks = _coordinate_ranks(
        geometry,
        config,
        pallet_dims,
        deadline=deadline,
    )
    support_tiers = _support_tiers(supports, deadline=deadline)
    keys = []
    for stable_index, (x_rank, y_rank) in enumerate(coordinate_ranks):
        _check_deadline(deadline)
        spatial_ring = max(x_rank, y_rank)
        support_tier = support_tiers[stable_index]
        wave = spatial_ring + support_tier
        keys.append(
            (
                wave,
                spatial_ring,
                x_rank,
                y_rank,
                support_tier,
                stable_index,
            )
        )
    return keys


def _stable_directed_wave_order(
    items: List[Dict],
    edges: List[Set[int]],
    supports: List[Set[int]],
    config: ExecutionSequenceConfig,
    pallet_dims: Dict[str, float],
    geometry: List[Tuple[float, float, float, float, float, float]],
    blockers: Optional[List[Dict[str, Set[int]]]],
    deadline: float,
    pallet_id=None,
) -> Optional[List[int]]:
    forward_keys = _directed_wave_keys(
        geometry,
        supports,
        config,
        pallet_dims,
        deadline=deadline,
    )
    return _stable_forward_order(
        items,
        edges,
        config,
        forward_keys,
        blockers,
        deadline,
        pallet_id,
    )


def _raise_no_execution_order(
    pallet: Dict, config: ExecutionSequenceConfig
) -> None:
    if config.preserve_open_direction:
        raise ExecutionSequenceError(
            "pallet %r has no execution order preserving at least %d open "
            "directions within %.3fs"
            % (
                pallet.get("pallet_id"),
                4 - config.max_occupied_directions,
                config.max_sequence_search_seconds_per_pallet,
            )
        )
    raise ExecutionSequenceError(
        "pallet %r has no execution order within %.3fs"
        % (
            pallet.get("pallet_id"),
            config.max_sequence_search_seconds_per_pallet,
        )
    )


def sequence_pallet_items(
    pallet: Dict,
    config: Optional[ExecutionSequenceConfig] = None,
) -> List[Dict]:
    """Return deep-copied items in a support-safe low-height execution order."""

    cfg = config or ExecutionSequenceConfig()
    source_items = list(pallet.get("packed_items") or [])
    if not source_items:
        return []

    ids = [item.get("id") for item in source_items]
    if any(box_id is None for box_id in ids) or len(set(ids)) != len(ids):
        raise ExecutionSequenceError("box ids must be present and unique")

    dims = _pallet_dims(source_items)
    _validate_bounds(source_items, dims, cfg.coordinate_tolerance_mm)
    edges, indegree, supports = _support_edges(
        source_items, cfg.coordinate_tolerance_mm
    )
    _add_clearance_edges(source_items, cfg, edges, indegree)
    deadline = time.monotonic() + cfg.max_sequence_search_seconds_per_pallet
    try:
        _add_approach_edges(
            source_items,
            cfg,
            edges,
            indegree,
            dims,
            deadline=deadline,
        )
    except _ExecutionSequenceDeadlineExceeded:
        _raise_no_execution_order(pallet, cfg)
    ready = deque(idx for idx, degree in enumerate(indegree) if degree == 0)
    processed_count = 0
    while ready:
        idx = ready.popleft()
        processed_count += 1
        for target_idx in sorted(edges[idx]):
            indegree[target_idx] -= 1
            if indegree[target_idx] == 0:
                ready.append(target_idx)

    if processed_count != len(source_items):
        blocked_ids = [
            source_items[idx].get("id")
            for idx, degree in enumerate(indegree)
            if degree > 0
        ]
        preview = blocked_ids[:12]
        suffix = "..." if len(blocked_ids) > len(preview) else ""
        raise ExecutionSequenceError(
            "pallet %r has cyclic execution dependencies; blocked boxes=%r%s"
            % (pallet.get("pallet_id"), preview, suffix)
        )
    geometry = [_physical_geometry(item) for item in source_items]
    blockers: Optional[List[Dict[str, Set[int]]]] = None
    try:
        if cfg.preserve_open_direction:
            blockers = _direction_blocker_map(
                geometry,
                cfg,
                deadline=deadline,
            )
        ordered_indices = _stable_directed_wave_order(
            source_items,
            edges,
            supports,
            cfg,
            dims,
            geometry,
            blockers,
            deadline,
            pallet.get("pallet_id"),
        )
    except _ExecutionSequenceDeadlineExceeded:
        ordered_indices = None
    if ordered_indices is None:
        _raise_no_execution_order(pallet, cfg)
    _assert_replay_safe(source_items, ordered_indices, supports, cfg)
    try:
        _assert_approach_replay_safe(
            source_items,
            ordered_indices,
            cfg,
            dims,
            deadline=deadline,
        )
    except _ExecutionSequenceDeadlineExceeded:
        _raise_no_execution_order(pallet, cfg)
    if cfg.preserve_open_direction:
        _assert_open_direction_replay(
            source_items, ordered_indices, cfg, blockers
        )
    ordered_items = []
    for sequence, idx in enumerate(ordered_indices, 1):
        item = deepcopy(source_items[idx])
        item.pop("original_packing_sequence", None)
        item.pop("robot_packing_sequence", None)
        item["seq"] = sequence
        ordered_items.append(item)
    _center_layout_in_place(
        ordered_items, dims, cfg.coordinate_tolerance_mm
    )
    _refresh_robot_depth_fields(
        ordered_items, pallet, dims, cfg.origin
    )
    try:
        _assert_final_execution_layout(
            ordered_items, cfg, deadline=deadline
        )
    except _ExecutionSequenceDeadlineExceeded:
        _raise_no_execution_order(pallet, cfg)
    _annotate_stack_height_before(ordered_items)
    return ordered_items


def plan_execution_report(
    report: Optional[Dict],
    config: Optional[ExecutionSequenceConfig] = None,
) -> Dict:
    """Return a centered robot execution report in dependency-safe order."""

    if report is None:
        raise ExecutionSequenceError("report is required")
    if not isinstance(report, dict):
        raise ExecutionSequenceError("report must be a dictionary")
    result = deepcopy(report)
    pallets = result.get("pallets")
    if pallets is None:
        return result
    if not isinstance(pallets, list):
        raise ExecutionSequenceError("report pallets must be a list")
    source_pallets = report.get("pallets") or []
    for idx, pallet in enumerate(pallets):
        if not isinstance(pallet, dict):
            raise ExecutionSequenceError("pallet %d must be a dictionary" % idx)
        pallet["packed_items"] = sequence_pallet_items(
            source_pallets[idx], config=config
        )
    return result
