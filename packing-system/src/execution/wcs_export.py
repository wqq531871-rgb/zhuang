"""WCS export that preserves the independent execution order as global seq."""

from __future__ import annotations

from copy import deepcopy
from typing import Dict, List, Optional, Tuple

from src.adapter.wcs_adapter import WcsPlanResult, report_to_plan_result

from .sequence_planner import (
    EXECUTION_SEQUENCE_DIAGNOSTICS_FIELD,
    STACK_HEIGHT_BEFORE_FIELD,
    ExecutionSequenceConfig,
    plan_execution_report,
)


def _item_z(item: Dict) -> float:
    return round(float((item.get("position") or {}).get("z", 0) or 0), 3)


def _true_dim(item: Dict, axis: str) -> float:
    return float(
        item.get(
            "original_%s" % axis,
            item.get("raw_%s" % axis, item.get(axis, 0)),
        )
        or 0
    )


def _layers_in_execution_order(
    items: List[Dict],
) -> Tuple[List[Dict], float]:
    z_levels = sorted({_item_z(item) for item in items})
    layer_of = {z: idx + 1 for idx, z in enumerate(z_levels)}
    by_layer: Dict[int, List[Dict]] = {}
    total_height = 0.0
    for seq, item in enumerate(items, 1):
        z = _item_z(item)
        height = _true_dim(item, "height")
        layer_id = layer_of[z]
        total_height = max(total_height, z + height)
        by_layer.setdefault(layer_id, []).append(
            {
                "length": _true_dim(item, "length"),
                "width": _true_dim(item, "width"),
                "height": height,
                "layer_id": layer_id,
                "seq": seq,
                "product_code": int(item.get("product_code") or 0),
            }
        )
    return (
        [{"cartons": by_layer[layer_id]} for layer_id in sorted(by_layer)],
        total_height,
    )


def report_to_execution_plan_result(
    report: Optional[Dict],
    config: Optional[ExecutionSequenceConfig] = None,
    include_failed: bool = True,
) -> WcsPlanResult:
    """Plan execution order and export WCS cartons with seq from that order."""

    execution_report = plan_execution_report(report, config=config)
    return execution_report_to_plan_result(
        execution_report,
        include_failed=include_failed,
    )


def execution_report_to_plan_result(
    execution_report: Optional[Dict],
    include_failed: bool = True,
) -> WcsPlanResult:
    """Export an already-planned execution report without replanning it."""

    base_result = report_to_plan_result(
        deepcopy(execution_report), include_failed=include_failed
    )
    cases = deepcopy(base_result.cases)
    for case in cases:
        pallet = base_result.plan_by_unique_id[case["box_unique_id"]]
        layers, total_height = _layers_in_execution_order(
            list(pallet.get("packed_items") or [])
        )
        case["layers"] = layers
        case["total_height"] = total_height
    plan_by_unique_id = deepcopy(base_result.plan_by_unique_id)
    for pallet in plan_by_unique_id.values():
        pallet.pop(EXECUTION_SEQUENCE_DIAGNOSTICS_FIELD, None)
        for item in pallet.get("packed_items") or []:
            item.pop(STACK_HEIGHT_BEFORE_FIELD, None)
    return WcsPlanResult(
        cases=cases,
        plan_by_unique_id=plan_by_unique_id,
    )
