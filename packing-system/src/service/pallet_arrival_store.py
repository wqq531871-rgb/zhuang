# -*- coding: utf-8 -*-
"""Persist the latest physical pallet reported by WCS interface 4.6."""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional


def workspace_root() -> Path:
    configured = (os.environ.get("PACKING_WORKSPACE") or "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    return Path(__file__).resolve().parents[3] / "packing-workspace"


def runtime_dir(workspace: Optional[Path] = None) -> Path:
    path = (Path(workspace) if workspace else workspace_root()) / "runtime"
    path.mkdir(parents=True, exist_ok=True)
    return path


def latest_pallet_arrival_path(workspace: Optional[Path] = None) -> Path:
    return runtime_dir(workspace) / "wcs_latest_pallet_arrival.json"


def write_latest_pallet_arrival(
    body: Dict[str, Any],
    *,
    workspace: Optional[Path] = None,
) -> Dict[str, Any]:
    payload = {
        "robot_id": str(body.get("robot_id") or "").strip(),
        "station_id": str(body.get("station_id") or "").strip(),
        "pallet_code": str(body.get("pallet_code") or "").strip(),
        "case_type": str(body.get("case_type") or "").strip(),
        "source": "palletarrive",
        "received_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    path = latest_pallet_arrival_path(workspace)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)
    print(
        f"[4.6-托盘] pallet_code={payload['pallet_code'] or '-'} "
        f"station={payload['station_id'] or '-'} → {path.name}"
    )
    return payload


def read_latest_pallet_arrival(
    *,
    workspace: Optional[Path] = None,
    legacy_log_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    path = latest_pallet_arrival_path(workspace)
    if path.is_file():
        try:
            data = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError, TypeError):
            data = None
        if isinstance(data, dict):
            return data

    log_dir = Path(legacy_log_dir) if legacy_log_dir else None
    if log_dir is None or not log_dir.is_dir():
        return {}
    arrivals = _read_legacy_arrivals(log_dir)
    return arrivals[0] if arrivals else {}


def _read_legacy_arrivals(log_dir: Path) -> list[Dict[str, Any]]:
    arrivals = []
    candidates = sorted(
        Path(log_dir).glob("*palletarrive*.json"),
        key=lambda candidate: candidate.name,
        reverse=True,
    )
    for candidate in candidates:
        try:
            record = json.loads(candidate.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError, TypeError):
            continue
        body = record.get("body") if isinstance(record, dict) else None
        if not isinstance(body, dict):
            continue
        raw_time = str(record.get("time") or "").strip()
        try:
            received_at = datetime.strptime(
                raw_time, "%Y%m%d_%H%M%S_%f"
            ).strftime("%Y-%m-%d %H:%M:%S")
        except ValueError:
            received_at = raw_time
        arrival = {
            "robot_id": str(body.get("robot_id") or "").strip(),
            "station_id": str(body.get("station_id") or "").strip(),
            "pallet_code": str(body.get("pallet_code") or "").strip(),
            "case_type": str(body.get("case_type") or "").strip(),
            "source": "palletarrive_log",
            "received_at": received_at,
        }
        if arrival["pallet_code"]:
            arrivals.append(arrival)
    return arrivals


def list_recent_pallet_arrivals(
    *,
    workspace: Optional[Path] = None,
    legacy_log_dir: Optional[Path] = None,
    limit: int = 20,
) -> list[Dict[str, Any]]:
    """Return newest distinct physical pallets for the editable UI selector."""
    records = []
    current_path = latest_pallet_arrival_path(workspace)
    if current_path.is_file():
        try:
            current = json.loads(current_path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError, TypeError):
            current = None
        if isinstance(current, dict) and current.get("pallet_code"):
            records.append(current)
    if legacy_log_dir and Path(legacy_log_dir).is_dir():
        records.extend(_read_legacy_arrivals(Path(legacy_log_dir)))

    distinct = []
    seen = set()
    for record in records:
        pallet_code = str(record.get("pallet_code") or "").strip()
        if not pallet_code or pallet_code in seen:
            continue
        seen.add(pallet_code)
        distinct.append(dict(record))
        if len(distinct) >= max(1, int(limit)):
            break
    return distinct
