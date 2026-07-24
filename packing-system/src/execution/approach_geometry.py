"""Pure geometry helpers for a diagonal robot placement approach."""

from dataclasses import dataclass
import math
from typing import Iterable, Tuple


Point = Tuple[float, float]
Rect = Tuple[float, float, float, float]


def _finite_float(value: float, name: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be a finite number")
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{name} must be a finite number") from exc
    if not math.isfinite(result):
        raise ValueError(f"{name} must be a finite number")
    return result


def _finite_tuple(
    values: Iterable[float], expected_length: int, name: str
) -> Tuple[float, ...]:
    try:
        items = tuple(values)
    except TypeError as exc:
        raise ValueError(f"{name} must contain {expected_length} finite numbers") from exc
    if len(items) != expected_length:
        raise ValueError(f"{name} must contain {expected_length} finite numbers")
    return tuple(
        _finite_float(value, f"{name}[{index}]")
        for index, value in enumerate(items)
    )


def _validated_point(point: Iterable[float], name: str) -> Point:
    x, y = _finite_tuple(point, 2, name)
    return x, y


def _validated_rect(rect: Iterable[float], name: str) -> Rect:
    x_min, x_max, y_min, y_max = _finite_tuple(rect, 4, name)
    if x_max <= x_min or y_max <= y_min:
        raise ValueError(f"{name} must have positive width and height")
    return x_min, x_max, y_min, y_max


def _nonnegative_float(value: float, name: str) -> float:
    result = _finite_float(value, name)
    if result < 0:
        raise ValueError(f"{name} must be non-negative")
    return result


def _checked_add(first: float, second: float, name: str) -> float:
    return _finite_float(first + second, name)


def _checked_subtract(first: float, second: float, name: str) -> float:
    return _finite_float(first - second, name)


def _checked_divide(numerator: float, denominator: float, name: str) -> float:
    return _finite_float(numerator / denominator, name)


def _rect_dimensions(rect: Rect, name: str) -> Point:
    return (
        _checked_subtract(rect[1], rect[0], f"{name} width"),
        _checked_subtract(rect[3], rect[2], f"{name} height"),
    )


def _translated_rect(rect: Rect, offset_x: float, offset_y: float) -> Rect:
    return (
        _checked_add(rect[0], offset_x, "translated start x_min"),
        _checked_add(rect[1], offset_x, "translated start x_max"),
        _checked_add(rect[2], offset_y, "translated start y_min"),
        _checked_add(rect[3], offset_y, "translated start y_max"),
    )


@dataclass(frozen=True)
class MovingRectPath:
    """A fixed-size rectangle translated from +X/+Y to its final position."""

    final_rect: Rect
    offset_x: float
    offset_y: float
    z_min: float
    z_max: float

    def __post_init__(self) -> None:
        final_rect = _validated_rect(self.final_rect, "final_rect")
        offset_x = _nonnegative_float(self.offset_x, "offset_x")
        offset_y = _nonnegative_float(self.offset_y, "offset_y")
        z_min = _finite_float(self.z_min, "z_min")
        z_max = _finite_float(self.z_max, "z_max")
        if z_max <= z_min:
            raise ValueError("z_max must be greater than z_min")
        _rect_dimensions(final_rect, "final_rect")
        _translated_rect(final_rect, offset_x, offset_y)

        object.__setattr__(self, "final_rect", final_rect)
        object.__setattr__(self, "offset_x", offset_x)
        object.__setattr__(self, "offset_y", offset_y)
        object.__setattr__(self, "z_min", z_min)
        object.__setattr__(self, "z_max", z_max)


def _segment_intersects_closed_rect(start: Point, end: Point, rect: Rect) -> bool:
    t_enter = 0.0
    t_exit = 1.0
    axes = (
        (start[0], end[0], rect[0], rect[1]),
        (start[1], end[1], rect[2], rect[3]),
    )
    for start_value, end_value, lower, upper in axes:
        delta = _checked_subtract(end_value, start_value, "segment axis delta")
        if delta == 0.0:
            if start_value < lower or start_value > upper:
                return False
            continue

        axis_enter = _checked_divide(
            _checked_subtract(lower, start_value, "segment entry numerator"),
            delta,
            "segment entry parameter",
        )
        axis_exit = _checked_divide(
            _checked_subtract(upper, start_value, "segment exit numerator"),
            delta,
            "segment exit parameter",
        )
        if axis_enter > axis_exit:
            axis_enter, axis_exit = axis_exit, axis_enter
        t_enter = max(t_enter, axis_enter)
        t_exit = min(t_exit, axis_exit)
        if t_enter > t_exit:
            return False
    return True


def _segment_intersects_rect_interior(start: Point, end: Point, rect: Rect) -> bool:
    if rect[0] >= rect[1] or rect[2] >= rect[3]:
        return False

    t_enter = 0.0
    t_exit = 1.0
    axes = (
        (start[0], end[0], rect[0], rect[1]),
        (start[1], end[1], rect[2], rect[3]),
    )
    for start_value, end_value, lower, upper in axes:
        delta = _checked_subtract(end_value, start_value, "segment axis delta")
        if delta == 0.0:
            if not lower < start_value < upper:
                return False
            continue

        axis_enter = _checked_divide(
            _checked_subtract(lower, start_value, "segment entry numerator"),
            delta,
            "segment entry parameter",
        )
        axis_exit = _checked_divide(
            _checked_subtract(upper, start_value, "segment exit numerator"),
            delta,
            "segment exit parameter",
        )
        if axis_enter > axis_exit:
            axis_enter, axis_exit = axis_exit, axis_enter
        t_enter = max(t_enter, axis_enter)
        t_exit = min(t_exit, axis_exit)
        if t_enter >= t_exit:
            return False
    return True


def segment_intersects_rect(
    start: Iterable[float],
    end: Iterable[float],
    rect: Iterable[float],
    tolerance: float = 1e-6,
) -> bool:
    """Return whether a closed segment intersects an axis-aligned rectangle."""

    validated_start = _validated_point(start, "start")
    validated_end = _validated_point(end, "end")
    x_min, x_max, y_min, y_max = _validated_rect(rect, "rect")
    tolerance = _nonnegative_float(tolerance, "tolerance")
    expanded_rect = (
        _checked_subtract(x_min, tolerance, "expanded rect x_min"),
        _checked_add(x_max, tolerance, "expanded rect x_max"),
        _checked_subtract(y_min, tolerance, "expanded rect y_min"),
        _checked_add(y_max, tolerance, "expanded rect y_max"),
    )
    return _segment_intersects_closed_rect(
        validated_start, validated_end, expanded_rect
    )


def _strict_axis_overlap(
    first_min: float,
    first_max: float,
    second_min: float,
    second_max: float,
    clearance: float,
    tolerance: float,
) -> bool:
    clearance_lower = _checked_add(
        _checked_subtract(second_min, clearance, "clearance lower bound"),
        tolerance,
        "tolerant clearance lower bound",
    )
    clearance_upper = _checked_subtract(
        _checked_add(second_max, clearance, "clearance upper bound"),
        tolerance,
        "tolerant clearance upper bound",
    )
    return (
        first_max > clearance_lower
        and first_min < clearance_upper
    )


def _inclusive_axis_overlap(
    first_min: float,
    first_max: float,
    second_min: float,
    second_max: float,
    clearance: float,
    tolerance: float,
) -> bool:
    clearance_lower = _checked_subtract(
        _checked_subtract(second_min, clearance, "clearance lower bound"),
        tolerance,
        "tolerant clearance lower bound",
    )
    clearance_upper = _checked_add(
        _checked_add(second_max, clearance, "clearance upper bound"),
        tolerance,
        "tolerant clearance upper bound",
    )
    return first_max >= clearance_lower and first_min <= clearance_upper


def preposition_descent_blocked(
    path: MovingRectPath,
    blocker_rect: Iterable[float],
    blocker_z_max: float,
    xy_clearance: float,
    tolerance: float = 1e-6,
) -> bool:
    """Return whether a blocker obstructs descent at the translated start."""

    if not isinstance(path, MovingRectPath):
        raise ValueError("path must be a MovingRectPath")
    blocker_rect = _validated_rect(blocker_rect, "blocker_rect")
    blocker_z_max = _finite_float(blocker_z_max, "blocker_z_max")
    xy_clearance = _nonnegative_float(xy_clearance, "xy_clearance")
    tolerance = _nonnegative_float(tolerance, "tolerance")

    if blocker_z_max <= _checked_add(
        path.z_min, tolerance, "tolerant path z_min"
    ):
        return False

    start_rect = _translated_rect(path.final_rect, path.offset_x, path.offset_y)
    return _strict_axis_overlap(
        start_rect[0],
        start_rect[1],
        blocker_rect[0],
        blocker_rect[1],
        xy_clearance,
        tolerance,
    ) and _strict_axis_overlap(
        start_rect[2],
        start_rect[3],
        blocker_rect[2],
        blocker_rect[3],
        xy_clearance,
        tolerance,
    )


def moving_path_blocked(
    path: MovingRectPath,
    blocker_rect: Iterable[float],
    blocker_z_min: float,
    blocker_z_max: float,
    xy_clearance: float,
    tolerance: float = 1e-6,
) -> bool:
    """Return whether a blocker intersects the diagonal translation sweep."""

    if not isinstance(path, MovingRectPath):
        raise ValueError("path must be a MovingRectPath")
    blocker_rect = _validated_rect(blocker_rect, "blocker_rect")
    blocker_z_min = _finite_float(blocker_z_min, "blocker_z_min")
    blocker_z_max = _finite_float(blocker_z_max, "blocker_z_max")
    if blocker_z_max <= blocker_z_min:
        raise ValueError("blocker_z_max must be greater than blocker_z_min")
    xy_clearance = _nonnegative_float(xy_clearance, "xy_clearance")
    tolerance = _nonnegative_float(tolerance, "tolerance")

    tolerant_z_min = _checked_add(path.z_min, tolerance, "tolerant path z_min")
    tolerant_z_max = _checked_subtract(
        path.z_max, tolerance, "tolerant path z_max"
    )
    if blocker_z_max <= tolerant_z_min or blocker_z_min >= tolerant_z_max:
        return False

    final_x_min, final_x_max, final_y_min, final_y_max = path.final_rect
    width, height = _rect_dimensions(path.final_rect, "final_rect")
    start = (
        _checked_add(final_x_min, path.offset_x, "translated start x_min"),
        _checked_add(final_y_min, path.offset_y, "translated start y_min"),
    )
    end = (final_x_min, final_y_min)

    collision_rect = (
        _checked_add(
            _checked_subtract(
                _checked_subtract(blocker_rect[0], width, "Minkowski x_min"),
                xy_clearance,
                "clearance-expanded Minkowski x_min",
            ),
            tolerance,
            "tolerant Minkowski x_min",
        ),
        _checked_subtract(
            _checked_add(
                blocker_rect[1],
                xy_clearance,
                "clearance-expanded Minkowski x_max",
            ),
            tolerance,
            "tolerant Minkowski x_max",
        ),
        _checked_add(
            _checked_subtract(
                _checked_subtract(blocker_rect[2], height, "Minkowski y_min"),
                xy_clearance,
                "clearance-expanded Minkowski y_min",
            ),
            tolerance,
            "tolerant Minkowski y_min",
        ),
        _checked_subtract(
            _checked_add(
                blocker_rect[3],
                xy_clearance,
                "clearance-expanded Minkowski y_max",
            ),
            tolerance,
            "tolerant Minkowski y_max",
        ),
    )
    return _segment_intersects_rect_interior(start, end, collision_rect)


def local_egress_blocked(
    corridor_rect: Iterable[float],
    lower_top: float,
    upper_rect: Iterable[float],
    upper_z_min: float,
    upper_z_max: float,
    offset_x: float,
    offset_y: float,
    xy_clearance: float,
    height_tolerance: float,
    tolerance: float = 1e-6,
) -> bool:
    """Return whether a taller upper box blocks local lift or exit."""

    corridor_rect = _validated_rect(corridor_rect, "corridor_rect")
    lower_top = _finite_float(lower_top, "lower_top")
    upper_rect = _validated_rect(upper_rect, "upper_rect")
    upper_z_min = _finite_float(upper_z_min, "upper_z_min")
    upper_z_max = _finite_float(upper_z_max, "upper_z_max")
    if upper_z_max <= upper_z_min:
        raise ValueError("upper_z_max must be greater than upper_z_min")
    offset_x = _nonnegative_float(offset_x, "offset_x")
    offset_y = _nonnegative_float(offset_y, "offset_y")
    xy_clearance = _nonnegative_float(xy_clearance, "xy_clearance")
    height_tolerance = _nonnegative_float(
        height_tolerance, "height_tolerance"
    )
    tolerance = _nonnegative_float(tolerance, "tolerance")

    height_limit = _checked_add(
        _checked_add(lower_top, height_tolerance, "egress height limit"),
        tolerance,
        "tolerant egress height limit",
    )
    if upper_z_max <= height_limit:
        return False

    local_hit = _inclusive_axis_overlap(
        corridor_rect[0],
        corridor_rect[1],
        upper_rect[0],
        upper_rect[1],
        xy_clearance,
        tolerance,
    ) and _inclusive_axis_overlap(
        corridor_rect[2],
        corridor_rect[3],
        upper_rect[2],
        upper_rect[3],
        xy_clearance,
        tolerance,
    )
    if local_hit:
        return True

    path = MovingRectPath(
        final_rect=corridor_rect,
        offset_x=offset_x,
        offset_y=offset_y,
        z_min=lower_top,
        z_max=upper_z_max,
    )
    return moving_path_blocked(
        path,
        upper_rect,
        upper_z_min,
        upper_z_max,
        xy_clearance,
        tolerance,
    )


__all__ = [
    "MovingRectPath",
    "local_egress_blocked",
    "moving_path_blocked",
    "preposition_descent_blocked",
    "segment_intersects_rect",
]
