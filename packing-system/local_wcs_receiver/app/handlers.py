"""接收接口业务处理。

接口4（boxarrive）：只登记箱子到达；
state 由其它模块写入；PLC 由 PlcStateWatcher 监听后自动下传。
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from .config_loader import ReceiverSettings
from .request_log import log_request

# packing-system/（其下有 src/service/...）；不要把 src 本身塞进 path
_PACKING_SYSTEM_ROOT = Path(__file__).resolve().parents[2]


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


def _ensure_packing_system_import() -> Path:
    """保证 ``from src.service...`` 可用（cwd 常为 local_wcs_receiver）。"""
    root = _PACKING_SYSTEM_ROOT.resolve()
    root_s = str(root)
    # 去掉误加的 .../src，避免挡住正确的 packing-system 根
    src_s = str(root / "src")
    sys.path[:] = [
        p
        for p in sys.path
        if Path(p).resolve().as_posix() != Path(src_s).as_posix()
    ]
    if root_s not in sys.path:
        sys.path.insert(0, root_s)
    return root


def _record_selected_pallet(
    settings: ReceiverSettings, body: Dict[str, Any]
) -> Dict[str, Any]:
    """接口3：记录 WCS 选定托盘，供三维整盘模拟。"""
    _ensure_packing_system_import()
    from src.service.live_stack_bridge import write_selected_pallet_session

    session = write_selected_pallet_session(
        box_unique_id=str(body.get("box_unique_id") or ""),
        order_id=str(body.get("order_id") or ""),
        robot_id=str(body.get("robot_id") or ""),
        source="sendcasetask",
    )
    return {"session": {"ok": True, **session}}


def _record_box_arrive(
    settings: ReceiverSettings, body: Dict[str, Any]
) -> Dict[str, Any]:
    """接口4：只登记到达，不判转、不入队 PLC。"""
    _ensure_packing_system_import()
    from src.service.live_stack_bridge import record_box_arrive

    uid = str(body.get("box_unique_id") or "").strip()
    try:
        seq = int(body.get("seq"))
    except (TypeError, ValueError):
        return {
            "arrive": {
                "ok": False,
                "reason": "invalid_seq",
                "box_unique_id": uid,
            }
        }

    session = record_box_arrive(
        box_unique_id=uid,
        seq=seq,
        order_id=str(body.get("order_id") or ""),
        robot_id=str(body.get("robot_id") or ""),
        product_code=str(body.get("product_code") or body.get("sku") or ""),
    )
    return {
        "arrive": {
            "ok": True,
            "reason": "registered",
            "box_unique_id": session.get("box_unique_id"),
            "seq": seq,
            "order_id": session.get("order_id"),
            "note": "等待其它模块写 state；PLC 监听将自动下传",
        }
    }


def handle_sendcasetask(
    settings: ReceiverSettings, body: Dict[str, Any]
) -> Dict[str, Any]:
    required = ["robot_id", "box_unique_id", "order_id"]
    missing = _missing_fields(body, required)
    data: Dict[str, Any] = {}
    if missing and settings.strict_validation:
        resp = fail(1, f"missing fields: {', '.join(missing)}")
    else:
        if missing:
            print(f"[WARN] sendcasetask 缺少字段 {missing}，strict_validation=false 仍回成功")
        # 接口3：WCS 选定托盘 → 写现场会话，三维可整盘加载（不必等接口4）
        try:
            data = _record_selected_pallet(settings, body)
        except Exception as exc:
            print(f"[接口3-会话] 写入失败：{exc}")
            data = {"session": {"ok": False, "error": str(exc)}}
        resp = ok(data)
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
    data: Dict[str, Any] = {}
    if missing and settings.strict_validation:
        resp = fail(1, f"missing fields: {', '.join(missing)}")
    else:
        if missing:
            print(f"[WARN] boxarrive 缺少字段 {missing}，strict_validation=false 仍回成功")
        try:
            data = _record_box_arrive(settings, body)
        except Exception as exc:
            print(f"[接口4-到达] 登记失败：{exc}")
            data = {
                "arrive": {
                    "ok": False,
                    "reason": "exception",
                    "error": str(exc),
                }
            }
        resp = ok(data)
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
