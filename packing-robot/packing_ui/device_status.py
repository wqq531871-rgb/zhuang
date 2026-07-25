"""接口 4.7 data.status 写入（与 packing-system device_status_store 同文件）。

PLC 侧在读到 DBW12 KONGXIAN==0 时调用，避免强依赖 packing-system 包导入。
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

STATUS_READY = 0
STATUS_BUSY = 1
STATUS_ERROR = 99
_VALID = frozenset({STATUS_READY, STATUS_BUSY, STATUS_ERROR})


def default_runtime_dir() -> Path:
    env = (os.environ.get("PACKING_WORKSPACE") or "").strip()
    if env:
        root = Path(env).expanduser().resolve()
    else:
        root = Path(__file__).resolve().parents[2] / "packing-workspace"
    path = root / "runtime"
    path.mkdir(parents=True, exist_ok=True)
    return path


def device_status_path() -> Path:
    return default_runtime_dir() / "wcs_device_status.json"


def _atomic_write(path: Path, payload: dict[str, Any]) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    tmp.replace(path)
    return path


def read_device_status(*, default: int = STATUS_READY) -> int:
    path = device_status_path()
    if not path.is_file():
        return int(default)
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError, TypeError):
        return int(default)
    if not isinstance(data, dict):
        return int(default)
    try:
        value = int(data.get("status"))
    except (TypeError, ValueError):
        return int(default)
    return value if value in _VALID else int(default)


def write_device_status(status: int, *, source: str = "") -> dict[str, Any]:
    value = int(status)
    if value not in _VALID:
        raise ValueError(f"非法 device status: {status}")
    payload = {
        "status": value,
        "source": str(source or ""),
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    path = _atomic_write(device_status_path(), payload)
    print(
        f"[4.7-状态] status={value} source={payload['source'] or '-'} → {path.name}"
    )
    return payload


def mark_ready_on_kongxian_idle(kongxian: int) -> dict[str, Any] | None:
    """DBW12 KONGXIAN==0 → data.status=0；已是 0 则不重复写。"""
    try:
        idle = int(kongxian)
    except (TypeError, ValueError):
        return None
    if idle != 0:
        return None
    if read_device_status(default=STATUS_BUSY) == STATUS_READY:
        return None
    return write_device_status(STATUS_READY, source="plc_kongxian")
