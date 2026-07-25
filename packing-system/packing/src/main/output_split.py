"""Choose output/success vs output/fail for a packing run (no content split)."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Dict, List, Optional, Tuple


SUCCESS_DIR_NAME = "success"
FAIL_DIR_NAME = "fail"


def is_success_pallet(pallet: Dict) -> bool:
    return str((pallet or {}).get("mpm_status") or "").strip().upper() == "SUCCESS"


def report_has_success_pallets(report: Optional[Dict]) -> bool:
    """True if the report contains at least one SUCCESS pallet."""
    for pallet in (report or {}).get("pallets") or []:
        if is_success_pallet(pallet):
            return True
    return False


def success_fail_dirs(output_dir: Path) -> Tuple[Path, Path]:
    root = Path(output_dir)
    return root / SUCCESS_DIR_NAME, root / FAIL_DIR_NAME


def ensure_success_fail_dirs(output_dir: Path) -> Tuple[Path, Path]:
    success_dir, fail_dir = success_fail_dirs(output_dir)
    success_dir.mkdir(parents=True, exist_ok=True)
    fail_dir.mkdir(parents=True, exist_ok=True)
    return success_dir, fail_dir


def resolve_report_bucket_dir(output_dir: Path, report: Optional[Dict]) -> Path:
    """有任一达标盘 → output/success；否则 → output/fail。"""
    success_dir, fail_dir = ensure_success_fail_dirs(output_dir)
    return success_dir if report_has_success_pallets(report) else fail_dir


def _refresh_overall_summary(report: Dict) -> None:
    pallets = list(report.get("pallets") or [])
    success_n = sum(1 for p in pallets if is_success_pallet(p))
    failed_n = len(pallets) - success_n
    gaps = [
        float(p.get("mpm_gap") or 0.0)
        for p in pallets
        if not is_success_pallet(p)
    ]
    summary = dict(report.get("summary") or {})
    overall = dict(summary.get("overall") or {})
    overall["total_pallets"] = len(pallets)
    overall["success_pallets"] = success_n
    overall["failed_pallets"] = failed_n
    overall["avg_mpm_gap"] = (
        round(sum(gaps) / len(gaps), 2) if gaps else 0.0
    )
    summary["overall"] = overall
    report["summary"] = summary


def split_report_by_status(report: Optional[Dict]) -> Tuple[Dict, Dict]:
    """Deprecated helper: return (success_only, fail_only) copies.

    Persist paths no longer split; kept for tests / ad-hoc filtering.
    """
    base = report if isinstance(report, dict) else {}
    pallets = list(base.get("pallets") or [])
    success_pallets = [p for p in pallets if is_success_pallet(p)]
    fail_pallets = [p for p in pallets if not is_success_pallet(p)]

    success_report = copy.deepcopy(base)
    fail_report = copy.deepcopy(base)
    success_report["pallets"] = copy.deepcopy(success_pallets)
    fail_report["pallets"] = copy.deepcopy(fail_pallets)
    _refresh_overall_summary(success_report)
    _refresh_overall_summary(fail_report)
    return success_report, fail_report


def iter_output_search_dirs(output_dir: Path) -> List[Path]:
    """Dirs to scan for packing_plan files (success/fail first, then legacy root)."""
    root = Path(output_dir)
    success_dir, fail_dir = success_fail_dirs(root)
    dirs = [success_dir, fail_dir, root]
    return [d for d in dirs if d.exists()]
