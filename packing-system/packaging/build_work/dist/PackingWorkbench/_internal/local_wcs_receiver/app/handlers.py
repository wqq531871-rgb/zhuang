"""接收接口业务处理（P0：固定成功回包）。"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from .config_loader import ReceiverSettings
from .request_log import log_request


def ok(data: Optional[Dict[str, Any]] = None, msg: str = "ok") -> Dict[str, Any]:
    return {"code": 0, "msg": msg, "data": data if data is not None else {}}


def fail(code: int, msg: str, data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    return {"code": code, "msg": msg, "data": data if data is not None else {}}


def _missing_fields(body: Dict[str, Any], required: List[str]) -> List[str]:
    missing = []
    for key in required:
        if key not in body or body.get(key) in (None, ""):
            missing.append(key)
    return missing


def handle_sendcasetask(
    settings: ReceiverSettings, body: Dict[str, Any]
) -> Dict[str, Any]:
    required = ["robot_id", "box_unique_id", "order_id"]
    missing = _missing_fields(body, required)
    if missing and settings.strict_validation:
        resp = fail(1, f"missing fields: {', '.join(missing)}")
    else:
        # TODO(P1): lookup_plan_map=true 时按 box_unique_id 查 wcs_plan_map 并填 data
        if missing:
            print(f"[WARN] sendcasetask 缺少字段 {missing}，strict_validation=false 仍回成功")
        resp = ok({})
    log_request(
        log_dir=settings.log_dir,
        save_requests=settings.save_requests,
        endpoint=settings.sendcasetask_path,
        method="POST",
        body=body,
        response=resp,
    )
    return resp


def handle_boxarrive(
    settings: ReceiverSettings, body: Dict[str, Any]
) -> Dict[str, Any]:
    required = [
        "robot_id",
        "box_unique_id",
        "order_id",
        "length",
        "width",
        "height",
        "seq",
    ]
    missing = _missing_fields(body, required)
    if missing and settings.strict_validation:
        resp = fail(1, f"missing fields: {', '.join(missing)}")
    else:
        # TODO(P2): 按 box_unique_id + seq 与本地执行方案对账
        if missing:
            print(f"[WARN] boxarrive 缺少字段 {missing}，strict_validation=false 仍回成功")
        resp = ok({})
    log_request(
        log_dir=settings.log_dir,
        save_requests=settings.save_requests,
        endpoint=settings.boxarrive_path,
        method="POST",
        body=body,
        response=resp,
    )
    return resp


def handle_palletarrive(
    settings: ReceiverSettings, body: Dict[str, Any]
) -> Dict[str, Any]:
    required = ["robot_id", "station_id", "pallet_code", "case_type", "case_data"]
    missing = _missing_fields(body, required)
    if "empty_flag" not in body and settings.strict_validation:
        missing.append("empty_flag")
    if missing and settings.strict_validation:
        resp = fail(1, f"missing fields: {', '.join(missing)}")
    else:
        if missing:
            print(f"[WARN] palletarrive 缺少字段 {missing}，strict_validation=false 仍回成功")
        case_data = body.get("case_data")
        if case_data is not None and not isinstance(case_data, list):
            if settings.strict_validation:
                resp = fail(1, "case_data must be a list")
            else:
                print("[WARN] palletarrive case_data 不是列表，strict_validation=false 仍回成功")
                resp = ok({})
        else:
            resp = ok({})
    log_request(
        log_dir=settings.log_dir,
        save_requests=settings.save_requests,
        endpoint=settings.palletarrive_path,
        method="POST",
        body=body,
        response=resp,
    )
    return resp


def handle_status(settings: ReceiverSettings) -> Dict[str, Any]:
    resp = {
        "code": 0,
        "msg": "success",
        "data": {"status": int(settings.device_status)},
    }
    log_request(
        log_dir=settings.log_dir,
        save_requests=settings.save_requests,
        endpoint=settings.status_path,
        method="GET",
        body=None,
        response=resp,
    )
    return resp
