"""Pure frontend helpers shared by the dashboard variants."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import math
from typing import Iterable, MutableMapping


DEFAULT_DOWNLOAD_INTERVAL = 200
MIN_DOWNLOAD_INTERVAL = 1
MAX_DOWNLOAD_INTERVAL = 86400

RUN_MODE_OPTIONS = (
    ("接口持续运行", "continuous"),
    ("接口单次运行", "once"),
    ("Excel 单次运行", "excel"),
    ("接口运行至成功", "until-success"),
)


@dataclass(frozen=True)
class RunModePolicy:
    uses_api: bool
    uses_interval: bool
    uses_excel: bool


_RUN_MODE_POLICIES = {
    "continuous": RunModePolicy(True, True, False),
    "once": RunModePolicy(True, False, False),
    "excel": RunModePolicy(False, False, True),
    "until-success": RunModePolicy(True, True, False),
}


def run_mode_policy(mode: str) -> RunModePolicy:
    """Return which controls and data source are used by a run mode."""
    try:
        return _RUN_MODE_POLICIES[mode]
    except KeyError as exc:
        raise ValueError(f"未知运行方式：{mode}") from exc


def successful_pallet_count(pallets: Iterable[dict]) -> int:
    """Return the global successful-pallet count for a loaded result."""
    return sum(
        1
        for pallet in (pallets or [])
        if str((pallet or {}).get("mpm_status") or "").strip().upper()
        == "SUCCESS"
    )


_BOX_DIMENSION_FIELDS = (
    ("original_length", "original_width", "original_height"),
    ("raw_length", "raw_width", "raw_height"),
    ("length", "width", "height"),
)
_INTEGER_MULTIPLE_TOLERANCE = 1e-6


def _box_dimensions(item: dict) -> tuple[float, float, float] | None:
    """Return the first complete, positive dimension triplet by field priority."""
    for fields in _BOX_DIMENSION_FIELDS:
        try:
            dimensions = tuple(float((item or {}).get(field)) for field in fields)
        except (TypeError, ValueError):
            continue
        if all(math.isfinite(value) and value > 0 for value in dimensions):
            return dimensions
    return None


def _specs_have_integer_multiple_relationship(
    left: tuple[float, float, float],
    right: tuple[float, float, float],
) -> bool:
    """Return whether all corresponding axes form integer ratios."""
    for left_value, right_value in zip(left, right):
        ratio = max(left_value, right_value) / min(left_value, right_value)
        nearest_integer = round(ratio)
        if nearest_integer < 1:
            return False
        if abs(ratio - nearest_integer) > _INTEGER_MULTIPLE_TOLERANCE:
            return False
    return True


def regular_irregular_box_counts(
    pallets: Iterable[dict],
) -> tuple[int, int]:
    """Count boxes whose specifications do or do not have an integer-multiple peer."""
    specification_counts: Counter[tuple[float, float, float]] = Counter()
    invalid_count = 0
    for pallet in pallets or []:
        for item in (pallet or {}).get("packed_items") or []:
            dimensions = _box_dimensions(item)
            if dimensions is None:
                invalid_count += 1
            else:
                specification_counts[dimensions] += 1

    specifications = list(specification_counts)
    regular_specifications: set[tuple[float, float, float]] = set()
    for index, left in enumerate(specifications):
        for right in specifications[index + 1 :]:
            if _specs_have_integer_multiple_relationship(left, right):
                regular_specifications.add(left)
                regular_specifications.add(right)

    regular_count = sum(
        count
        for specification, count in specification_counts.items()
        if specification in regular_specifications
    )
    valid_count = sum(specification_counts.values())
    irregular_count = invalid_count + valid_count - regular_count
    return regular_count, irregular_count


def list_success_pallets(pallets: Iterable[dict]) -> list:
    """Return SUCCESS pallets that have a non-empty pallet_id, stable order."""
    result = []
    for pallet in pallets or []:
        if str((pallet or {}).get("mpm_status") or "").strip().upper() != "SUCCESS":
            continue
        pid = str((pallet or {}).get("pallet_id") or "").strip()
        if not pid:
            continue
        result.append(pallet)
    return result


def normalize_download_interval(
    value,
    default: int = DEFAULT_DOWNLOAD_INTERVAL,
) -> int:
    """Return a valid WCS polling interval, falling back to the default."""
    try:
        interval = int(value)
    except (TypeError, ValueError):
        interval = int(default)
    if not MIN_DOWNLOAD_INTERVAL <= interval <= MAX_DOWNLOAD_INTERVAL:
        interval = int(default)
    return interval


def apply_download_interval(config: MutableMapping, value) -> int:
    """Write a normalized polling interval without discarding WCS settings."""
    interval = normalize_download_interval(value)
    data_source = config.setdefault("data_source", {})
    data_source["download_interval"] = interval
    return interval
