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


def resolve_execution_report_path(plan_path: Path) -> Path:
    """Prefer ``*_execution.json`` sibling / workspace output bucket when given a base plan."""
    path = Path(plan_path).resolve()
    stem = path.stem
    if stem.lower().endswith("_execution"):
        return path
    sibling = path.with_name(f"{stem}_execution.json")
    if sibling.exists():
        return sibling.resolve()
    for ancestor in path.parents:
        if ancestor.name != "packing-workspace":
            continue
        for bucket in ("success", "fail"):
            candidate = ancestor / "output" / bucket / f"{stem}_execution.json"
            if candidate.exists():
                return candidate.resolve()
        break
    return path


def load_execution_wcs_case_for_pallet(
    plan_path: Path,
    pallet: Dict[str, Any],
    *,
    box_index: int = 1,
) -> Dict[str, Any]:
    """从执行规划产物 ``*_execution_wcs.json`` / map 取出该托盘的 WCS case。

    使用已生成的 ``box_unique_id`` 与执行顺序 layers，不再从旧 packing_plan 重算。
    """
    exec_path = resolve_execution_report_path(plan_path)
    if not exec_path.stem.lower().endswith("_execution"):
        raise ValueError(
            f"未找到执行方案（*_execution.json），无法按执行顺序下传：{plan_path}"
        )
    _plan, wcs_path, map_path = result_triplet_paths(exec_path)
    if not wcs_path.exists():
        raise ValueError(f"缺少执行 WCS 文件：{wcs_path.name}")
    if not map_path.exists():
        raise ValueError(f"缺少执行映射文件：{map_path.name}")

    wcs_map = _load_json(map_path, {})
    cases = _load_json(wcs_path, [])
    if not isinstance(wcs_map, dict) or not isinstance(cases, list):
        raise ValueError("执行 WCS 文件格式无效（期望 map=对象、cases=数组）")

    uid = _find_map_uid(wcs_map, pallet)
    if uid is None:
        pallet_id = str((pallet or {}).get("pallet_id") or "")
        raise ValueError(
            f"执行映射中找不到托盘 {pallet_id or '?'}，请确认加载的是本次 execution 结果"
        )

    for case in cases:
        if not isinstance(case, dict):
            continue
        if str(case.get("box_unique_id") or "") != str(uid):
            continue
        out = dict(case)
        out["box_index"] = int(box_index)
        return out

    raise ValueError(
        f"执行 WCS 数组中缺少 box_unique_id={uid} 的 case"
    )


def load_execution_wcs_cases(plan_path: Path) -> List[Dict[str, Any]]:
    """读取整份 ``*_execution_wcs.json``（WCS 下传数组）。"""
    exec_path = resolve_execution_report_path(plan_path)
    if not exec_path.stem.lower().endswith("_execution"):
        raise ValueError(
            f"未找到执行方案（*_execution.json）：{plan_path}"
        )
    _plan, wcs_path, _map_path = result_triplet_paths(exec_path)
    if not wcs_path.exists():
        raise ValueError(f"缺少执行 WCS 文件：{wcs_path.name}")
    cases = _load_json(wcs_path, [])
    if not isinstance(cases, list):
        raise ValueError(f"执行 WCS 文件不是 JSON 数组：{wcs_path}")
    return [c for c in cases if isinstance(c, dict)]


def resolve_wcs_bundle_paths(plan_path: Path) -> Tuple[Path, Path, Path]:
    """定位下传用的 (报告, wcs数组, map)。优先 execution 三件套，否则回退 base。"""
    preferred = resolve_execution_report_path(plan_path)
    candidates: List[Path] = [preferred]
    if preferred.stem.lower().endswith("_execution"):
        candidates.append(
            preferred.with_name(preferred.stem[: -len("_execution")] + ".json")
        )
    original = Path(plan_path).resolve()
    candidates.append(original)

    seen = set()
    for candidate in candidates:
        try:
            key = str(candidate.resolve())
        except OSError:
            key = str(candidate)
        if key in seen:
            continue
        seen.add(key)
        try:
            report, wcs_path, map_path = result_triplet_paths(candidate)
        except ValueError:
            continue
        if wcs_path.exists() and map_path.exists():
            return report, wcs_path, map_path
    raise ValueError(
        f"找不到与结果配套的 WCS 文件（期望与 {preferred.name} 同目录的 "
        f"*_execution_wcs.json / *_map.json，或 wcs_plan_*.json）"
    )


def build_wcs_cases_for_pallet_ids(
    plan_path: Path,
    pallet_ids: Sequence[str],
) -> Tuple[List[Dict[str, Any]], Path]:
    """按勾选顺序构造完整达标托盘 case 数组；复用文件内 box_unique_id，重编 box_index=1..N。

    每个 case 含该盘 layers 下全部箱子，不做部分箱截取。
    """
    ids = [str(pid or "").strip() for pid in pallet_ids if str(pid or "").strip()]
    if not ids:
        raise ValueError("请至少选择一个达标托盘")

    report_path, wcs_path, map_path = resolve_wcs_bundle_paths(plan_path)
    wcs_map = _load_json(map_path, {})
    cases = _load_json(wcs_path, [])
    if not isinstance(wcs_map, dict) or not isinstance(cases, list):
        raise ValueError("WCS 文件格式无效（期望 map=对象、cases=数组）")

    cases_by_uid = {
        str(case.get("box_unique_id") or ""): case
        for case in cases
        if isinstance(case, dict) and case.get("box_unique_id")
    }

    built: List[Dict[str, Any]] = []
    for box_index, pallet_id in enumerate(ids, start=1):
        uid = None
        mapped = None
        for unique_id, pallet in wcs_map.items():
            if not isinstance(pallet, dict):
                continue
            if str(pallet.get("pallet_id") or "").strip() != pallet_id:
                continue
            uid = str(unique_id)
            mapped = pallet
            break
        if uid is None or mapped is None:
            raise ValueError(f"映射中找不到托盘：{pallet_id}")
        status = str(mapped.get("mpm_status") or "").strip().upper()
        if status != "SUCCESS":
            raise ValueError(f"托盘 {pallet_id} 不是达标盘（{status or 'UNKNOWN'}），不能下传")
        case = cases_by_uid.get(uid)
        if case is None:
            raise ValueError(f"WCS 数组中缺少托盘 {pallet_id}（box_unique_id={uid}）")
        layers = case.get("layers")
        if not isinstance(layers, list) or not layers:
            raise ValueError(f"托盘 {pallet_id} 的 layers 为空，拒绝下传不完整盘")
        carton_n = sum(
            len(layer.get("cartons") or [])
            for layer in layers
            if isinstance(layer, dict)
        )
        if carton_n <= 0:
            raise ValueError(f"托盘 {pallet_id} 没有任何箱子，拒绝下传")
        out = dict(case)
        out["box_index"] = int(box_index)
        built.append(out)
    return built, report_path

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
