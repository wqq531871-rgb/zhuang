"""Selectable packing target used by algorithms and final reporting."""

from dataclasses import dataclass
from typing import Dict, Mapping, Optional

from src.utils.case_group import normalize_case_group


_FILL_RATE_STEPS = (0.70, 0.75, 0.80, 0.85, 0.90)


@dataclass(frozen=True)
class SuccessTarget:
    mode: str = "index"
    threshold: float = 192.0

    @classmethod
    def from_mapping(cls, value: Optional[Mapping]) -> "SuccessTarget":
        raw = dict(value or {})
        mode = str(raw.get("mode") or "index").strip().lower()
        threshold = float(raw.get("threshold", 192.0 if mode == "index" else 0.85))
        if mode == "index":
            if threshold <= 0:
                raise ValueError("指数目标必须大于 0")
            return cls(mode=mode, threshold=threshold)
        if mode == "fill_rate":
            if not any(abs(threshold - step) <= 1e-9 for step in _FILL_RATE_STEPS):
                raise ValueError("装载率目标只允许 70%、75%、80%、85%、90%")
            return cls(mode=mode, threshold=threshold)
        raise ValueError(f"未知成功目标模式：{mode}")

    def to_dict(self) -> Dict[str, float | str]:
        return {"mode": self.mode, "threshold": self.threshold}


def _status_counts(pallets):
    statuses = [
        str((pallet or {}).get("mpm_status") or "UNKNOWN").strip().upper()
        for pallet in pallets
    ]
    return {
        "total_pallets": len(statuses),
        "success_pallets": statuses.count("SUCCESS"),
        "failed_pallets": statuses.count("FAILED"),
        "unknown_pallets": sum(
            status not in {"SUCCESS", "FAILED"} for status in statuses
        ),
    }


def _sync_summary_counts(report: Dict) -> None:
    pallets = list(report.get("pallets") or [])
    summary = report.setdefault("summary", {})
    summary.setdefault("overall", {}).update(_status_counts(pallets))

    by_type = summary.get("by_pallet_type") or {}
    for group_key, stats in by_type.items():
        pallet_type = stats.get("pallet_type")
        sales_order_no = stats.get("sales_order_no")
        case_group = normalize_case_group(stats.get("case_group"))
        matching = [
            pallet
            for pallet in pallets
            if (
                pallet.get("_summary_group_key") == group_key
                if pallet.get("_summary_group_key") is not None
                else (
                    pallet.get("pallet_type") == pallet_type
                    and pallet.get("sales_order_no") == sales_order_no
                    and normalize_case_group(pallet.get("case_group")) == case_group
                )
            )
        ]
        stats.update(_status_counts(matching))


def apply_success_target(report: Dict, target: SuccessTarget) -> Dict:
    """Apply the selected final success rule to a completed report in place."""
    report["success_target"] = target.to_dict()
    for pallet in report.get("pallets") or []:
        index_status = str(
            pallet.get("index_status")
            or pallet.get("mpm_status")
            or "UNKNOWN"
        ).strip().upper()
        pallet["index_status"] = index_status
        if target.mode == "fill_rate":
            goal_value = float(pallet.get("fill_rate") or 0.0)
            final_status = (
                "SUCCESS" if goal_value + 1e-12 >= target.threshold else "FAILED"
            )
        else:
            goal_value = float(pallet.get("mpm_total") or 0.0)
            final_status = index_status

        pallet["goal_mode"] = target.mode
        pallet["goal_threshold"] = target.threshold
        pallet["goal_value"] = goal_value
        pallet["goal_status"] = final_status
        pallet["final_status"] = final_status
        # Legacy consumers (UI/WCS/output buckets) already use mpm_status.
        pallet["mpm_status"] = final_status

    _sync_summary_counts(report)
    for pallet in report.get("pallets") or []:
        pallet.pop("_summary_group_key", None)
    return report
