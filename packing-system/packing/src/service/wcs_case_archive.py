# -*- coding: utf-8 -*-
"""Recover WCS case_data from generated result archives when DB rows are gone."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Tuple


_ARCHIVE_PATTERNS = (
    "*_execution_wcs.json",
    "wcs_plan_*.json",
    "wcs_push_multi_*.json",
)


def find_wcs_case_in_archives(
    box_unique_id: str,
    *,
    workspace: Path,
) -> Tuple[Dict[str, Any], Path]:
    uid = str(box_unique_id or "").strip()
    if not uid:
        raise ValueError("box_unique_id 不能为空")
    success_dir = Path(workspace) / "output" / "success"
    candidates = []
    for pattern in _ARCHIVE_PATTERNS:
        candidates.extend(success_dir.rglob(pattern) if success_dir.is_dir() else [])
    candidates = sorted(
        {path.resolve() for path in candidates if path.is_file()},
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    for path in candidates:
        try:
            data = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError, TypeError):
            continue
        if not isinstance(data, list):
            continue
        for case in data:
            if not isinstance(case, dict):
                continue
            if str(case.get("box_unique_id") or "").strip() != uid:
                continue
            if not isinstance(case.get("layers"), list):
                continue
            return dict(case), path
    raise ValueError(
        f"数据库和历史装箱结果中都找不到 box_unique_id={uid}"
    )
