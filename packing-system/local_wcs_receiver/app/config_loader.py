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
    # 接口4：到达后查 wcs_box_orientation 并判旋转
    rotation_judge_enabled: bool
    packing_config_path: Path
    mock_camera_orientation_deg: Optional[int]


def _as_path(value: Any, default: str) -> str:
    text = str(value if value is not None else default).strip()
    if not text.startswith("/"):
        text = "/" + text
    return text


def _optional_orientation(value: Any) -> Optional[int]:
    if value is None or value == "":
        return None
    try:
        deg = int(value)
    except (TypeError, ValueError):
        return None
    if deg not in (0, 90):
        return None
    return deg


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
            rotation.get("packing_config")
            or raw.get("packing_config")
            or (packing_system_root / "config" / "packing_config.yaml")
        )
    )
    if not packing_cfg.is_absolute():
        packing_cfg = (base_dir / packing_cfg).resolve()

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
        rotation_judge_enabled=bool(rotation.get("enabled", True)),
        packing_config_path=packing_cfg,
        mock_camera_orientation_deg=_optional_orientation(
            rotation.get("mock_camera_orientation_deg")
        ),
    )
