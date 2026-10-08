"""Bounded, success-preserving pallet shape polishing.

This pass is deliberately a soft objective.  It may replace the positions of
the boxes already on a successful pallet, but it never moves boxes between
pallets and never changes the pallet's success status.
"""

from __future__ import annotations

import time
from collections import Counter
from copy import deepcopy
from dataclasses import replace
from typing import Callable, Dict, Iterable, List, Optional

from ..geometry.constraint_validator import validate_pallet_constraints
from ..packing.beam_search_packer import BeamSearchPacker
from ..utils.helpers import has_box_above, repack_ready_item


def _rectangle_union_area(rectangles: Iterable[tuple[float, float, float, float]]) -> float:
    rects = [rect for rect in rectangles if rect[1] > rect[0] and rect[3] > rect[2]]
    xs = sorted({value for rect in rects for value in rect[:2]})
    area = 0.0
    for left, right in zip(xs, xs[1:]):
        intervals = sorted(
            (bottom, top)
            for x0, x1, bottom, top in rects
            if x0 < right and x1 > left
        )
        covered = 0.0
        if intervals:
            start, end = intervals[0]
            for next_start, next_end in intervals[1:]:
                if next_start > end:
                    covered += end - start
                    start, end = next_start, next_end
                else:
                    end = max(end, next_end)
            covered += end - start
        area += (right - left) * covered
    return area


def measure_shape_quality(items: List[Dict]) -> Dict:
    """Return explainable metrics plus a lexicographic higher-is-better rank."""
    positioned = [item for item in items if item.get("position")]
    if not positioned:
        return {
            "top_level_count": 0,
            "top_height_spread_mm": 0.0,
            "footprint_compactness": 0.0,
            "rank": (0, 0.0, 0.0, 0.0),
        }

    exposed = [item for item in positioned if not has_box_above(item, positioned)]
    top_heights = [
        float(item["position"]["z"]) + float(item.get("height", 0) or 0)
        for item in exposed
    ]
    rounded_levels = {round(height, 6) for height in top_heights}
    top_level_count = len(rounded_levels)
    top_spread = max(top_heights) - min(top_heights) if top_heights else 0.0

    floor_items = [
        item for item in positioned
        if abs(float(item["position"].get("z", 0) or 0)) <= 1e-9
    ]
    rects = [
        (
            float(item["position"]["x"]),
            float(item["position"]["x"]) + float(item.get("length", 0) or 0),
            float(item["position"]["y"]),
            float(item["position"]["y"]) + float(item.get("width", 0) or 0),
        )
        for item in floor_items
    ]
    if rects:
        bbox_area = (
            (max(rect[1] for rect in rects) - min(rect[0] for rect in rects))
            * (max(rect[3] for rect in rects) - min(rect[2] for rect in rects))
        )
        compactness = _rectangle_union_area(rects) / bbox_area if bbox_area > 0 else 0.0
    else:
        bbox_area = 0.0
        compactness = 0.0

    # Flatness dominates; compactness only chooses between similarly flat layouts.
    rank = (-top_level_count, -top_spread, compactness, -bbox_area)
    return {
        "top_level_count": top_level_count,
        "top_height_spread_mm": round(top_spread, 6),
        "footprint_compactness": round(compactness, 6),
        "rank": rank,
    }


class ShapePolisher:
    """Try a small local repack and accept it only through a strict ratchet."""

    def __init__(
        self,
        constraint_config=None,
        enabled: bool = True,
        seconds_per_pallet: float = 1.0,
        repack_fn: Optional[Callable] = None,
        validate_fn: Optional[Callable] = None,
    ):
        self.constraint_config = constraint_config
        self.enabled = bool(enabled)
        self.seconds_per_pallet = max(0.0, float(seconds_per_pallet))
        self._repack_fn = repack_fn or self._repack
        self._validate_fn = validate_fn or self._validate

    def polish_plans(self, plans: List[Dict]) -> Dict[str, int]:
        diagnostics = {"attempted": 0, "improved": 0}
        if not self.enabled or self.seconds_per_pallet <= 0:
            return diagnostics

        for plan in plans:
            items = plan.get("packed_items") or []
            if str(plan.get("mpm_status") or "").upper() != "SUCCESS" or not items:
                continue
            pallet_dims = items[0].get("pallet_dims") or plan.get("pallet_dims") or {}
            before = measure_shape_quality(items)
            started = time.monotonic()
            deadline = started + self.seconds_per_pallet
            diagnostics["attempted"] += 1
            reason = "not_improved"
            try:
                candidate = self._repack_fn(deepcopy(items), pallet_dims, deadline)
            except Exception:
                # This optional pass must never turn a completed packing run
                # into an error.  The original successful plan is the fallback.
                candidate = None
                reason = "search_error"
            applied = False
            after = before
            if (
                candidate
                and Counter(str(item.get("id")) for item in candidate)
                == Counter(str(item.get("id")) for item in items)
                and self._validate_fn(candidate, pallet_dims)
            ):
                candidate_quality = measure_shape_quality(candidate)
                if candidate_quality["rank"] > before["rank"]:
                    plan["packed_items"] = candidate
                    after = candidate_quality
                    applied = True
                    reason = "improved"
                    diagnostics["improved"] += 1

            plan["shape_quality"] = {
                key: value for key, value in after.items() if key != "rank"
            }
            plan["shape_quality"].update({
                "polish_attempted": True,
                "polish_applied": applied,
                "polish_reason": reason,
                "polish_seconds": round(time.monotonic() - started, 4),
            })
        return diagnostics

    def _repack(self, items: List[Dict], pallet_dims: Dict, deadline: float):
        ready = [repack_ready_item(item) for item in items]
        packer = BeamSearchPacker(
            pallet_dims,
            constraint_config=self.constraint_config,
            max_candidate_points=120,
            max_points_per_layer=24,
        )
        packed, unfitted = packer.pack(
            ready,
            num_restarts=5,
            beam_width=2,
            candidate_limit=10,
            random_seed=20261008,
            stop_when_target_met=False,
            allow_skip_items=False,
            deadline=deadline,
            state_tiebreaker=lambda state: measure_shape_quality(
                state.get("placed_boxes") or []
            )["rank"],
        )
        return packed if not unfitted and len(packed) == len(items) else None

    def _validate(self, items: List[Dict], pallet_dims: Dict) -> bool:
        config = self.constraint_config
        if config is not None:
            # Flatness is the preference being improved here, not a success gate.
            config = replace(config, flat_top_full_perimeter_enabled=False)
        result = validate_pallet_constraints(
            {"packed_items": items},
            pallet_dims,
            constraint_config=config,
            target_mpm=0.0,
        )
        return bool(result.get("is_valid"))
