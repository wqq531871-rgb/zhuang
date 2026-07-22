"""Apply manual packing-order edits and rewrite local result JSON triplet."""

from __future__ import annotations

import json
import re
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple


_PLAN_NAME_RE = re.compile(
    r"^(?P<prefix>(?:ui_)?packing_plan_)(?P<body>.+)\.json$",
    re.IGNORECASE,
)


def result_triplet_paths(packing_plan_path: Path) -> Tuple[Path, Path, Path]:
    """Return (packing_plan, wcs_plan, wcs_plan_map) for the same calculation.

    Supports both naming styles under ``packing-workspace/output``:
    - ``packing_plan_{ts}.json`` + ``wcs_plan_{ts}.json`` + ``wcs_plan_map_{ts}.json``
    - ``packing_plan_{ts}_execution.json`` + ``..._execution_wcs.json`` + ``..._execution_wcs_map.json``
    """

    path = Path(packing_plan_path)
    match = _PLAN_NAME_RE.match(path.name)
    if not match:
        raise ValueError(f"不是 packing_plan 结果文件：{path.name}")

    body = match.group("body")
    out_dir = path.parent
    if body.lower().endswith("_execution"):
        stem = path.stem  # packing_plan_{ts}_execution
        return (
            path,
            out_dir / f"{stem}_wcs.json",
            out_dir / f"{stem}_wcs_map.json",
        )

    return (
        path,
        out_dir / f"wcs_plan_{body}.json",
        out_dir / f"wcs_plan_map_{body}.json",
    )


def apply_seq_values(
    pallet: Dict[str, Any],
    ordered_box_ids: Sequence[str],
) -> Dict[str, int]:
    """Only update each box's ``seq`` field. Do not reorder ``packed_items``."""

    rank = {
        str(box_id): index
        for index, box_id in enumerate(ordered_box_ids, start=1)
        if str(box_id or "")
    }
    applied: Dict[str, int] = {}
    for item in list((pallet or {}).get("packed_items") or []):
        if not isinstance(item, dict):
            continue
        box_id = str(item.get("id") or "")
        if box_id not in rank:
            continue
        seq = rank[box_id]
        item.pop("original_packing_sequence", None)
        item.pop("robot_packing_sequence", None)
        item["seq"] = seq
        applied[box_id] = seq
    return applied


# Backward-compatible alias used by older call sites/tests.
def apply_seq_order_to_pallet(
    pallet: Dict[str, Any],
    ordered_box_ids: Sequence[str],
) -> List[Dict[str, Any]]:
    apply_seq_values(pallet, ordered_box_ids)
    return list((pallet or {}).get("packed_items") or [])


def _pallet_match_key(pallet: Dict[str, Any]) -> Tuple[str, str, str]:
    return (
        str(pallet.get("pallet_id") or ""),
        str(pallet.get("sales_order_no") or ""),
        str(pallet.get("pallet_type") or ""),
    )


def _find_map_uid(
    wcs_map: Dict[str, Any],
    pallet: Dict[str, Any],
) -> Optional[str]:
    key = _pallet_match_key(pallet)
    for uid, mapped in wcs_map.items():
        if isinstance(mapped, dict) and _pallet_match_key(mapped) == key:
            return str(uid)
    pallet_id = str(pallet.get("pallet_id") or "")
    if not pallet_id:
        return None
    for uid, mapped in wcs_map.items():
        if isinstance(mapped, dict) and str(mapped.get("pallet_id") or "") == pallet_id:
            return str(uid)
    return None


def find_pallet_in_plan(
    plan_data: Dict[str, Any],
    pallet: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    """Resolve the editable pallet dict inside plan_data (by identity or key)."""

    if not isinstance(plan_data, dict) or not isinstance(pallet, dict):
        return None
    pallets = list(plan_data.get("pallets") or [])
    for candidate in pallets:
        if candidate is pallet:
            return candidate
    key = _pallet_match_key(pallet)
    for candidate in pallets:
        if isinstance(candidate, dict) and _pallet_match_key(candidate) == key:
            return candidate
    pallet_id = str(pallet.get("pallet_id") or "")
    if not pallet_id:
        return None
    for candidate in pallets:
        if isinstance(candidate, dict) and str(candidate.get("pallet_id") or "") == pallet_id:
            return candidate
    return None


def _load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def _save_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def rewrite_result_triplet_for_pallet(
    packing_plan_path: Path,
    plan_data: Dict[str, Any],
    pallet: Dict[str, Any],
    ordered_box_ids: Sequence[str],
    *,
    build_layers,
) -> Tuple[Path, Path, Path, Dict[str, int]]:
    """Write packing_plan, then patch only this pallet's seq into wcs files."""

    if not isinstance(pallet, dict):
        raise ValueError("当前托盘无效，无法更新结果文件。")

    target = find_pallet_in_plan(plan_data, pallet) or pallet
    applied = apply_seq_values(target, ordered_box_ids)
    if not applied:
        raise ValueError("没有给任何箱子写入 seq，请确认箱子列表与托盘数据一致。")
    # Keep the caller's pallet object in sync even if plan_data held a different dict.
    if target is not pallet:
        apply_seq_values(pallet, ordered_box_ids)

    plan_path, wcs_path, map_path = result_triplet_paths(packing_plan_path)
    _save_json(plan_path, plan_data)

    wcs_map = _load_json(map_path, {})
    if not isinstance(wcs_map, dict):
        wcs_map = {}
    cases = _load_json(wcs_path, [])
    if not isinstance(cases, list):
        cases = []

    target_uid = _find_map_uid(wcs_map, target)
    if target_uid is None:
        target_uid = uuid.uuid4().hex
        wcs_map[target_uid] = target

    mapped = wcs_map.get(target_uid)
    if not isinstance(mapped, dict):
        mapped = target
        wcs_map[target_uid] = mapped
    apply_seq_values(mapped, ordered_box_ids)

    items = list(mapped.get("packed_items") or [])
    layers, total_height = build_layers(items)

    replaced = False
    for idx, case in enumerate(cases):
        if not isinstance(case, dict):
            continue
        if str(case.get("box_unique_id") or "") != str(target_uid):
            continue
        patched = dict(case)
        patched["layers"] = layers
        patched["total_height"] = total_height
        cases[idx] = patched
        replaced = True
        break
    if not replaced:
        cases.append(
            {
                "box_index": len(cases) + 1,
                "box_unique_id": target_uid,
                "total_height": total_height,
                "order_id": str(target.get("sales_order_no") or ""),
                "case_group": str(target.get("case_group") or "0"),
                "case_type": str(target.get("pallet_type") or ""),
                "layers": layers,
            }
        )

    _save_json(wcs_path, cases)
    _save_json(map_path, wcs_map)
    return plan_path, wcs_path, map_path, applied
