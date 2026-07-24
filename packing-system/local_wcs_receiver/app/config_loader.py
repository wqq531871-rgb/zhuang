"""加载 receiver_config.yaml。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

import yaml


@dataclass
class ReceiverSettings:
    host: str
    port: int
    advertise_base_url: str
    sendcasetask_path: str
    boxarrive_path: str
    palletarrive_path: str
    status_path: str
    swagger_path: str
    log_dir: Path
    save_requests: bool
    device_status: int
    strict_validation: bool
    lookup_plan_map: bool
    plan_map_glob: str
    config_path: Path
    packing_config_path: Path
    # PLC 自动监听：发现 state=1/2 后入队并下传
    plc_auto_enabled: bool
    plc_auto_poll_interval_sec: float
    # 接法 B：camera_* 已写、state 空 → 自动判态
    state_judge_enabled: bool
    state_judge_poll_interval_sec: float
    state_judge_tol_mm: float


def _as_path(value: Any, default: str) -> str:
    text = str(value if value is not None else default).strip()
    if not text.startswith("/"):
        text = "/" + text
    return text


def load_settings(config_path: Path) -> ReceiverSettings:
    config_path = Path(config_path).resolve()
    if not config_path.exists():
        raise FileNotFoundError(f"配置文件不存在: {config_path}")
    with open(config_path, "r", encoding="utf-8") as f:
        raw: Dict[str, Any] = yaml.safe_load(f) or {}

    base_dir = config_path.parent.parent  # local_wcs_receiver/
    packing_system_root = base_dir.parent
    server = dict(raw.get("server") or {})
    paths = dict(raw.get("paths") or {})
    rotation = dict(raw.get("rotation_judge") or {})
    plc_auto = dict(raw.get("plc_auto") or {})
    state_judge = dict(raw.get("state_judge") or {})

    # 兼容旧扁平字段 host/port
    host = str(server.get("host") or raw.get("host") or "0.0.0.0")
    port = int(server.get("port") or raw.get("port") or 8093)

    log_dir = Path(str(raw.get("log_dir") or "logs"))
    if not log_dir.is_absolute():
        log_dir = (base_dir / log_dir).resolve()

    advertise = str(
        raw.get("advertise_base_url") or f"http://127.0.0.1:{port}"
    ).rstrip("/")

    packing_cfg = Path(
        str(
            plc_auto.get("packing_config")
            or state_judge.get("packing_config")
            or rotation.get("packing_config")
            or raw.get("packing_config")
            or (packing_system_root / "config" / "packing_config.yaml")
        )
    )
    if not packing_cfg.is_absolute():
        packing_cfg = (base_dir / packing_cfg).resolve()

    poll = plc_auto.get("poll_interval_sec", 0.5)
    try:
        poll_f = float(poll)
    except (TypeError, ValueError):
        poll_f = 0.5

    judge_poll = state_judge.get("poll_interval_sec", poll_f)
    try:
        judge_poll_f = float(judge_poll)
    except (TypeError, ValueError):
        judge_poll_f = poll_f

    tol = state_judge.get("tol_mm", 5.0)
    try:
        tol_f = float(tol)
    except (TypeError, ValueError):
        tol_f = 5.0

    return ReceiverSettings(
        host=host,
        port=port,
        advertise_base_url=advertise,
        sendcasetask_path=_as_path(
            paths.get("sendcasetask_path"), "/adaptor/api/wcs/sendcasetask"
        ),
        boxarrive_path=_as_path(
            paths.get("boxarrive_path"), "/adaptor/api/wcs/boxarrive"
        ),
        palletarrive_path=_as_path(
            paths.get("palletarrive_path"), "/adaptor/api/wcs/palletarrive"
        ),
        status_path=_as_path(paths.get("status_path"), "/api/status"),
        swagger_path=_as_path(paths.get("swagger_path"), "/swagger/index.html"),
        log_dir=log_dir,
        save_requests=bool(raw.get("save_requests", True)),
        device_status=int(raw.get("device_status", 0)),
        strict_validation=bool(raw.get("strict_validation", False)),
        lookup_plan_map=bool(raw.get("lookup_plan_map", False)),
        plan_map_glob=str(raw.get("plan_map_glob") or ""),
        config_path=config_path,
        packing_config_path=packing_cfg,
        plc_auto_enabled=bool(plc_auto.get("enabled", True)),
        plc_auto_poll_interval_sec=max(0.1, poll_f),
        state_judge_enabled=bool(state_judge.get("enabled", True)),
        state_judge_poll_interval_sec=max(0.1, judge_poll_f),
        state_judge_tol_mm=max(0.0, tol_f),
    )
