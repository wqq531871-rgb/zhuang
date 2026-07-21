"""Targeted donor-receiver exchanges that preserve the receiver layout."""

from __future__ import annotations

import itertools
from copy import deepcopy
from typing import Dict, List, Optional, Tuple

from src.geometry.constraint_validator import validate_pallet_constraints
from src.packing.beam_search_packer import BeamSearchPacker
from src.rescue.pallet_evaluator import PalletEvaluator
from src.utils.case_group import normalize_case_group
from src.utils.helpers import has_box_above, item_volume, repack_ready_item


def _refresh(plan: Dict, target_mpm: float) -> None:
    plan["mpm_target"] = target_mpm
    PalletEvaluator.calc_pallet_status(plan)


def _case_group(plan: Dict):
    groups = {
        normalize_case_group(item.get("case_group"))
        for item in plan.get("packed_items", [])
    }
    if len(groups) != 1:
        return None
    return next(iter(groups))


def _top_level_positive_items(plan: Dict) -> List[Dict]:
    items = list(plan.get("packed_items") or [])
    return [
        item
        for item in items
        if float(item.get("min_pack_multiple", 0) or 0) > 0
        and not has_box_above(item, items)
    ]


def _ranked_subsets(
    items: List[Dict], gap: float, max_items: int
) -> List[Tuple[Dict, ...]]:
    limited = sorted(
        items,
        key=lambda item: (
            abs(gap - float(item.get("min_pack_multiple", 0) or 0)),
            item_volume(item),
            str(item.get("id")),
        ),
    )[:18]
    subsets = []
    for count in range(1, min(max_items, len(limited)) + 1):
        for combo in itertools.combinations(limited, count):
            total = sum(
                float(item.get("min_pack_multiple", 0) or 0)
                for item in combo
            )
            if total + 1e-9 < gap:
                continue
            subsets.append(combo)
    subsets.sort(
        key=lambda combo: (
            sum(
                float(item.get("min_pack_multiple", 0) or 0)
                for item in combo
            ) - gap,
            len(combo),
            sum(item_volume(item) for item in combo),
            tuple(str(item.get("id")) for item in combo),
        )
    )
    return subsets


def _candidate_passes_gates(
    raw_boxes: List[Dict],
    plans: List[Dict],
    constraint_config,
) -> bool:
    input_ids = [str(item.get("id")) for item in raw_boxes]
    output_ids = [
        str(item.get("id"))
        for plan in plans
        for item in plan.get("packed_items", [])
    ]
    if len(output_ids) != len(input_ids) or sorted(output_ids) != sorted(input_ids):
        return False
    for plan in plans:
        items = list(plan.get("packed_items") or [])
        if not items or _case_group(plan) is None:
            return False
        gate = validate_pallet_constraints(
            plan,
            items[0].get("pallet_dims") or {},
            constraint_config=constraint_config,
            target_mpm=plan.get("mpm_target"),
        )
        if not gate.get("is_valid"):
            return False
    return True


def directed_donor_receiver_exchange(
    type_plans: List[Dict],
    pallet_dims: Dict[str, float],
    target_mpm: Optional[float],
    constraint_config=None,
    max_items: int = 4,
    max_attempts: int = 40,
) -> Dict:
    """Move only selected top donor boxes into fixed receiver free space."""

    if constraint_config is None:
        from src.config import ConstraintConfig
        constraint_config = ConstraintConfig()
    diag = {
        "rescued": 0,
        "directed_exchange_tried": 0,
        "directed_exchange_accepted": 0,
        "directed_exchange_cross_group_skipped": 0,
        "directed_exchange_geofail": 0,
        "directed_exchange_gate_rejected": 0,
        "directed_exchange_max_items": max_items,
    }
    if target_mpm is None or target_mpm <= 0 or len(type_plans) < 2:
        return diag

    target = float(target_mpm)
    for plan in type_plans:
        _refresh(plan, target)
    raw_boxes = [
        deepcopy(item)
        for plan in type_plans
        for item in plan.get("packed_items", [])
    ]

    while diag["directed_exchange_tried"] < max_attempts:
        accepted_this_round = False
        receivers = sorted(
            [
                (index, plan)
                for index, plan in enumerate(type_plans)
                if plan.get("mpm_status") == "FAILED"
                and plan.get("packed_items")
                and 0 < float(plan.get("mpm_gap", 0) or 0) <= target
            ],
            key=lambda entry: (
                float(entry[1].get("mpm_gap", target) or target),
                -float(entry[1].get("mpm_total", 0) or 0),
            ),
        )
        for receiver_idx, receiver in receivers:
            receiver_group = _case_group(receiver)
            if receiver_group is None:
                continue
            gap = float(receiver.get("mpm_gap", 0) or 0)
            for donor_idx, donor in enumerate(type_plans):
                if donor_idx == receiver_idx or not donor.get("packed_items"):
                    continue
                if _case_group(donor) != receiver_group:
                    diag["directed_exchange_cross_group_skipped"] += 1
                    continue
                donor_items = _top_level_positive_items(donor)
                for selected in _ranked_subsets(donor_items, gap, max_items):
                    if diag["directed_exchange_tried"] >= max_attempts:
                        break
                    diag["directed_exchange_tried"] += 1
                    selected_ids = {item.get("id") for item in selected}
                    candidate = deepcopy(type_plans)
                    candidate_receiver = candidate[receiver_idx]
                    candidate_donor = candidate[donor_idx]
                    additions = [repack_ready_item(item) for item in selected]
                    packer = BeamSearchPacker(
                        pallet_dims,
                        size_tolerance=0.0,
                        z_tolerance=0.0,
                        max_candidate_points=160,
                        max_points_per_layer=35,
                        constraint_config=constraint_config,
                    )
                    combined, unfitted = packer.pack_additions(
                        candidate_receiver["packed_items"],
                        additions,
                        num_restarts=3,
                        beam_width=4,
                        candidate_limit=18,
                        random_seed=61000 + diag["directed_exchange_tried"],
                        target_mpm=target,
                    )
                    if unfitted or not selected_ids.issubset(
                        {item.get("id") for item in combined}
                    ):
                        diag["directed_exchange_geofail"] += 1
                        continue
                    candidate_receiver["packed_items"] = combined
                    candidate_donor["packed_items"] = [
                        item
                        for item in candidate_donor["packed_items"]
                        if item.get("id") not in selected_ids
                    ]
                    _refresh(candidate_receiver, target)
                    if candidate_donor["packed_items"]:
                        _refresh(candidate_donor, target)
                    else:
                        candidate.pop(donor_idx)

                    receiver_gate = validate_pallet_constraints(
                        candidate_receiver,
                        pallet_dims,
                        constraint_config=constraint_config,
                        target_mpm=target,
                    )
                    if not receiver_gate.get("is_valid"):
                        diag["directed_exchange_gate_rejected"] += 1
                        continue
                    if not _candidate_passes_gates(
                        raw_boxes, candidate, constraint_config
                    ):
                        diag["directed_exchange_gate_rejected"] += 1
                        continue
                    old_success = sum(
                        plan.get("mpm_status") == "SUCCESS"
                        for plan in type_plans
                    )
                    new_success = sum(
                        plan.get("mpm_status") == "SUCCESS"
                        for plan in candidate
                    )
                    if new_success <= old_success:
                        continue
                    type_plans[:] = candidate
                    diag["rescued"] += new_success - old_success
                    diag["directed_exchange_accepted"] += 1
                    accepted_this_round = True
                    break
                if accepted_this_round:
                    break
            if accepted_this_round:
                break
        if not accepted_this_round:
            break
    return diag
