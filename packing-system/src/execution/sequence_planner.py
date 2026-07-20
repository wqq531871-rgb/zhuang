"""Plan a robot-safe execution order without changing the final pallet layout."""

from __future__ import annotations

import heapq
import math
from copy import deepcopy
from dataclasses import dataclass
from typing import Dict, List, Optional, Set, Tuple


_ORIGINS = {
    "x_min_y_min",
    "x_min_y_max",
    "x_max_y_min",
    "x_max_y_max",
}


class ExecutionSequenceError(ValueError):
    """Raised when a pallet cannot be converted to a valid execution order."""


@dataclass(frozen=True)
class ExecutionSequenceConfig:
    """Execution-order preferences and geometric tolerances."""

    origin: str = "x_min_y_min"
    coordinate_tolerance_mm: float = 1e-6
    box_xy_clearance_mm: float = 0.0
    suction_xy_clearance_mm: float = 0.0
    suction_z_clearance_mm: float = 0.0
    require_suction_pose: bool = True

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
        }
        for name, value in numeric_clearances.items():
            try:
                numeric = float(value)
            except (TypeError, ValueError) as exc:
                raise ValueError("%s must be a finite number" % name) from exc
            if not math.isfinite(numeric):
                raise ValueError("%s must be finite" % name)
            if numeric < 0:
                raise ValueError("%s must be non-negative" % name)
            object.__setattr__(self, name, numeric)


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


def _origin_key(
    item: Dict,
    origin: str,
    pallet_dims: Dict[str, float],
) -> Tuple[float, float, float]:
    x, y, _z, length, width, _height = _geometry(item)
    center_x = x + length / 2.0
    center_y = y + width / 2.0
    dx = center_x if origin.startswith("x_min") else pallet_dims["length"] - center_x
    dy = center_y if origin.endswith("y_min") else pallet_dims["width"] - center_y
    return dx * dx + dy * dy, dy, dx


def _schedule_key(
    item: Dict,
    original_index: int,
    config: ExecutionSequenceConfig,
    pallet_dims: Dict[str, float],
) -> Tuple[float, float, float, float, float, int]:
    _x, _y, z, _length, _width, height = _geometry(item)
    distance, y_progress, x_progress = _origin_key(
        item, config.origin, pallet_dims
    )
    return (
        z + height,
        z,
        distance,
        y_progress,
        x_progress,
        original_index,
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
    ready = []
    for idx, degree in enumerate(indegree):
        if degree == 0:
            heapq.heappush(
                ready,
                (_schedule_key(source_items[idx], idx, cfg, dims), idx),
            )

    ordered_indices = []
    while ready:
        _key, idx = heapq.heappop(ready)
        ordered_indices.append(idx)
        for target_idx in sorted(edges[idx]):
            indegree[target_idx] -= 1
            if indegree[target_idx] == 0:
                heapq.heappush(
                    ready,
                    (
                        _schedule_key(
                            source_items[target_idx], target_idx, cfg, dims
                        ),
                        target_idx,
                    ),
                )

    if len(ordered_indices) != len(source_items):
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
    _assert_replay_safe(source_items, ordered_indices, supports, cfg)
    return [deepcopy(source_items[idx]) for idx in ordered_indices]


def plan_execution_report(
    report: Optional[Dict],
    config: Optional[ExecutionSequenceConfig] = None,
) -> Dict:
    """Return a same-schema report with only ``packed_items`` order changed."""

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
