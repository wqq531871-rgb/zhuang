"""接收接口业务处理。

当前约定（联调阶段）：
- 4.3 sendcasetask / 4.4 boxarrive / 4.6 palletarrive：对方请求后按示例回成功，不做业务处理。
- 4.7 /api/status：返回配置中的 device_status。
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from .config_loader import ReceiverSettings
from .request_log import log_request


def ok(data: Optional[Dict[str, Any]] = None, msg: str = "success") -> Dict[str, Any]:
    return {"code": 0, "msg": msg, "data": data if data is not None else {}}


def fail(code: int, msg: str, data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    return {"code": code, "msg": msg, "data": data if data is not None else {}}


def handle_sendcasetask(
    settings: ReceiverSettings, body: Dict[str, Any]
) -> Dict[str, Any]:
    """4.3 拼箱物料信息下发：仅回成功示例，暂不落库/不查方案。"""
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
    """4.4 物料到达：仅回成功示例，暂不登记到达。"""
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
    """4.6 托盘到达：仅回成功示例，暂不驱动站台状态机。"""
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
