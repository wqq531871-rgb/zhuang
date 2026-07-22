"""Pure helpers for the single sequence used by playback, WCS, and robots."""

from __future__ import annotations

from typing import Dict, List


EXECUTION_MODE_LABEL = "统一执行顺序（seq）"


def sequence_mode_key(_value: object) -> str:
    """Map legacy UI mode values to the only supported execution mode."""

    return "execution"


def _positive_int(value):
    try:
        result = int(value)
    except (TypeError, ValueError):
        return None
    return result if result > 0 else None


def ordered_packed_items(
    pallet: Dict,
    _mode: object = "execution",
) -> List[Dict]:
    """Return items ordered only by seq, preserving array order as fallback."""

    items = list((pallet or {}).get("packed_items", []) or [])
    indexed = list(enumerate(items, start=1))
    return [
        item
        for _, item in sorted(
            indexed,
            key=lambda pair: (
                _positive_int(pair[1].get("seq")) or pair[0],
                pair[0],
            ),
        )
    ]
