"""Pure frontend helpers shared by the dashboard variants."""

from __future__ import annotations

from typing import Iterable, MutableMapping


DEFAULT_DOWNLOAD_INTERVAL = 200
MIN_DOWNLOAD_INTERVAL = 1
MAX_DOWNLOAD_INTERVAL = 86400


def successful_pallet_count(pallets: Iterable[dict]) -> int:
    """Return the global successful-pallet count for a loaded result."""
    return sum(
        1
        for pallet in (pallets or [])
        if str((pallet or {}).get("mpm_status") or "").strip().upper()
        == "SUCCESS"
    )


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
