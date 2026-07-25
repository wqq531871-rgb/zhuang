"""
Packing report persisters.

Writes one full packing_plan JSON (+ Excel summary) per run under
output/success or output/fail: any SUCCESS pallet → success, else fail.
"""

import json
from pathlib import Path
from typing import Callable, Dict

import pandas as pd

from src.main.output_split import resolve_report_bucket_dir


class JsonFileReportPersister:
    """Persist packing reports to local files."""

    def __init__(self, output_dir: Path, timestamp_fn: Callable[[str], str]):
        self._output_dir = output_dir
        self._timestamp_fn = timestamp_fn

    def persist(self, report: Dict, total_runtime: float) -> None:
        """Save one full JSON (+ Excel) under output/success or output/fail."""
        timestamp = self._timestamp_fn("%Y%m%d_%H%M%S")
        bucket = resolve_report_bucket_dir(self._output_dir, report)
        bucket_label = bucket.name

        json_path = bucket / f"packing_plan_{timestamp}.json"
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, ensure_ascii=False)
        excel_path = bucket / f"packing_plan_summary_{timestamp}.xlsx"
        self._write_pallet_summary_excel(report, excel_path)

        print("=" * 40)
        print(f"[{bucket_label}] 装箱方案：{json_path}")
        print(f"[{bucket_label}] 托盘统计：{excel_path}")
        print("=" * 40)
        print(f"算法总运行时间：{total_runtime:.2f} 秒")
        print("=" * 40)

    def _write_pallet_summary_excel(self, report: Dict, path: Path) -> None:
        rows = []
        for pallet in report.get("pallets", []):
            items = pallet.get("packed_items", []) or []
            dims = items[0].get("pallet_dims") if items else {}
            dims = dims or {}
            length = dims.get("length", "")
            width = dims.get("width", "")
            height = dims.get("height", "")
            if length != "" and width != "" and height != "":
                pallet_size = (
                    f"{float(length):g}x{float(width):g}x{float(height):g}"
                )
            else:
                pallet_size = ""

            rows.append({
                "托盘ID": pallet.get("pallet_id", ""),
                "托盘尺寸(mm)": pallet_size,
                "箱子数量": len(items),
                "稳定性状态": (pallet.get("stability_checks") or {}).get(
                    "status", ""
                ),
                "指数": pallet.get("mpm_total", ""),
                "目标指数": pallet.get("mpm_target", ""),
                "指数缺口": pallet.get("mpm_gap", ""),
                "指数状态": pallet.get("mpm_status", ""),
            })

        pd.DataFrame(rows).to_excel(path, index=False, engine="openpyxl")


class NullReportPersister:
    """Persister that intentionally does nothing."""

    def persist(self, report: Dict, total_runtime: float) -> None:
        return
