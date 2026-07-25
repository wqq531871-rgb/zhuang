# -*- coding: utf-8 -*-
"""接口 4.7 ``data.status`` 共享状态（WCS 轮询就绪/执行中）。

约定（与接口文档一致）：
- 0：准备就绪（MAX VP 运行中 + 无任务）
- 1：执行中（MAX VP 运行中 + 有任务）
- 99：停止/异常

状态机：
- PLC DBW12 ``KONGXIAN==0`` → 写 0
- 接口 4.6 ``palletarrive`` → 写 1
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

STATUS_READY = 0
STATUS_BUSY = 1
STATUS_ERROR = 99

_VALID = frozenset({STATUS_READY, STATUS_BUSY, STATUS_ERROR})


def workspace_root() -> Path:
    env = (os.environ.get("PACKING_WORKSPACE") or "").strip()
    if env:
        return Path(env).expanduser().resolve()
    # packing-system/src/service → packing-system → zhuang
    return Path(__file__).resolve().parents[3] / "packing-workspace"


def runtime_dir(workspace: Optional[Path] = None) -> Path:
    root = Path(workspace) if workspace else workspace_root()
    path = root / "runtime"
    path.mkdir(parents=True, exist_ok=True)
    return path


def device_status_path(workspace: Optional[Path] = None) -> Path:
    return runtime_dir(workspace) / "wcs_device_status.json"


def _atomic_write(path: Path, payload: Dict[str, Any]) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    tmp.replace(path)
    return path


def write_device_status(
    status: int,
    *,
    source: str = "",
    workspace: Optional[Path] = None,
) -> Dict[str, Any]:
    """写入设备状态；非法 status 抛 ValueError。"""
    value = int(status)
    if value not in _VALID:
        raise ValueError(f"非法 device status: {status}")
    payload = {
        "status": value,
        "source": str(source or ""),
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    path = _atomic_write(device_status_path(workspace), payload)
    print(
        f"[4.7-状态] status={value} source={payload['source'] or '-'} → {path.name}"
    )
    return payload


def read_device_status(
    *,
    default: int = STATUS_READY,
    workspace: Optional[Path] = None,
) -> int:
    """读取当前设备状态；文件缺失或损坏时返回 default。"""
    path = device_status_path(workspace)
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
    if value not in _VALID:
        return int(default)
    return value


def mark_busy_on_palletarrive(workspace: Optional[Path] = None) -> Dict[str, Any]:
    """接口 4.6：托盘到达 → 执行中。"""
    return write_device_status(
        STATUS_BUSY, source="palletarrive", workspace=workspace
    )


def mark_ready_on_kongxian_idle(
    kongxian: int,
    *,
    workspace: Optional[Path] = None,
) -> Optional[Dict[str, Any]]:
    """PLC DBW12 KONGXIAN==0 → 就绪；其它值不改状态。"""
    try:
        idle = int(kongxian)
    except (TypeError, ValueError):
        return None
    if idle != 0:
        return None
    current = read_device_status(default=STATUS_BUSY, workspace=workspace)
    if current == STATUS_READY:
        return None
    return write_device_status(
        STATUS_READY, source="plc_kongxian", workspace=workspace
    )
