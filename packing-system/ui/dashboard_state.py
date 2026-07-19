"""Pure frontend helpers shared by the dashboard variants."""

from __future__ import annotations

from dataclasses import dataclass
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
