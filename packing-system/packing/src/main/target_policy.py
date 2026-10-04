"""Packing objective policies shared by packing, rescue, and reporting."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Dict, Sequence

from .success_target import SuccessTarget


def _finite_positive(value) -> float:
    number = float(value or 0.0)
    return number if math.isfinite(number) and number > 0.0 else 0.0


def _box_volume(box: Dict) -> float:
    explicit = _finite_positive(box.get("volume"))
    if explicit:
        return explicit
    original = (
        _finite_positive(box.get("original_length")),
        _finite_positive(box.get("original_width")),
        _finite_positive(box.get("original_height")),
    )
    if all(original):
        return original[0] * original[1] * original[2]
    current = (
        _finite_positive(box.get("length")),
        _finite_positive(box.get("width")),
        _finite_positive(box.get("height")),
    )
    return current[0] * current[1] * current[2]


@dataclass(frozen=True)
class PackingTargetPolicy:
    mode: str
    threshold: float
    index_target: float

    def box_value(self, box: Dict) -> float:
        raise NotImplementedError

    def items_value(self, items: Sequence[Dict]) -> float:
        return sum(self.box_value(item) for item in items)

    def is_reached(self, items: Sequence[Dict]) -> bool:
        return self.items_value(items) + 1e-12 >= self.threshold

    def gap(self, items: Sequence[Dict]) -> float:
        return max(0.0, self.threshold - self.items_value(items))

    def annotate_plan(self, plan: Dict) -> Dict:
        items = plan.get("packed_items") or []
        mpm_total = float(
            plan.get("mpm_total")
            if plan.get("mpm_total") is not None
            else sum(float(item.get("min_pack_multiple") or 0.0) for item in items)
        )
        index_target = float(plan.get("mpm_target") or self.index_target)
        index_status = "SUCCESS" if mpm_total + 1e-12 >= index_target else "FAILED"
        goal_value = self.items_value(items)
        final_status = "SUCCESS" if goal_value + 1e-12 >= self.threshold else "FAILED"
        plan.update(
            {
                "mpm_total": mpm_total,
                "mpm_target": index_target,
                "mpm_gap": index_target - mpm_total,
                "index_status": index_status,
                "goal_mode": self.mode,
                "goal_threshold": self.threshold,
                "goal_value": goal_value,
                "goal_status": final_status,
                "final_status": final_status,
                "mpm_status": final_status,
            }
        )
        return plan


@dataclass(frozen=True)
class IndexTargetPolicy(PackingTargetPolicy):
    def box_value(self, box: Dict) -> float:
        return float(box.get("min_pack_multiple") or 0.0)


@dataclass(frozen=True)
class FillRateTargetPolicy(PackingTargetPolicy):
    pallet_volume: float

    def box_value(self, box: Dict) -> float:
        return _box_volume(box) / self.pallet_volume


def make_target_policy(
    success_target: SuccessTarget,
    index_target: float,
    pallet_dims: Dict,
) -> PackingTargetPolicy:
    """Create the operational target policy for one pallet group."""
    if success_target.mode == "index":
        return IndexTargetPolicy(
            mode="index",
            threshold=float(index_target),
            index_target=float(index_target),
        )

    dimensions = tuple(
        _finite_positive((pallet_dims or {}).get(name))
        for name in ("length", "width", "height")
    )
    if not all(dimensions):
        raise ValueError("装载率模式需要有限且大于 0 的托盘尺寸")
    pallet_volume = dimensions[0] * dimensions[1] * dimensions[2]
    return FillRateTargetPolicy(
        mode="fill_rate",
        threshold=float(success_target.threshold),
        index_target=float(index_target),
        pallet_volume=pallet_volume,
    )
