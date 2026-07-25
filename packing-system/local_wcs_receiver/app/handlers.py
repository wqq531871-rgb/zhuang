"""接收接口业务处理。

当前约定（联调阶段）：
- 4.3 sendcasetask：记录 WCS 选定托盘（现场码垛「托盘已选定」依赖此写入）。
- 4.4 boxarrive：对方请求后按示例回成功，暂不做业务处理。
- 4.6 palletarrive：回成功，并将 4.7 data.status 置为 1（执行中）。
- 4.5 reqpallet：我方→WCS 出站，暂不实现。
- 4.7 /api/status：返回 data.status（0 就绪 / 1 执行中 / 99 异常）；
  PLC KONGXIAN==0 时由控序侧写 0，本服务只读共享状态文件。
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from .config_loader import ReceiverSettings
from .request_log import log_request

# packing-system/（其下有 src/service/...）；不要把 src 本身塞进 path
_PACKING_SYSTEM_ROOT = Path(__file__).resolve().parents[2]


def ok(data: Optional[Dict[str, Any]] = None, msg: str = "success") -> Dict[str, Any]:
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
    """4.3：记录 WCS 选定托盘，供现场码垛 / 三维整盘模拟。"""
    _ensure_packing_system_import()
    from src.service.live_stack_bridge import write_selected_pallet_session

    session = write_selected_pallet_session(
        box_unique_id=str(body.get("box_unique_id") or ""),
        order_id=str(body.get("order_id") or ""),
        robot_id=str(body.get("robot_id") or ""),
        source="sendcasetask",
    )
    return {"session": {"ok": True, **session}}


def handle_sendcasetask(
    settings: ReceiverSettings, body: Dict[str, Any]
) -> Dict[str, Any]:
    """4.3 拼箱物料信息下发：写选定托盘会话，并回成功。"""
    required = ["robot_id", "box_unique_id", "order_id"]
    missing = _missing_fields(body, required)
    data: Dict[str, Any] = {}
    if missing and settings.strict_validation:
        resp = fail(1, f"missing fields: {', '.join(missing)}")
    else:
        if missing:
            print(f"[WARN] sendcasetask 缺少字段 {missing}，strict_validation=false 仍回成功")
        try:
            data = _record_selected_pallet(settings, body)
        except Exception as exc:
            print(f"[4.3-会话] 写入失败：{exc}")
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
    """4.6 托盘到达：回成功，并将 4.7 data.status 置为 1（执行中）。"""
    status_info: Dict[str, Any] = {}
    try:
        _ensure_packing_system_import()
        from src.service.device_status_store import mark_busy_on_palletarrive

        status_info = mark_busy_on_palletarrive()
    except Exception as exc:
        print(f"[4.6-状态] 写入 data.status=1 失败：{exc}")
        status_info = {"ok": False, "error": str(exc)}
    resp = ok({"device_status": status_info})
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
    """4.7：顶层 code 恒为 0；data.status 读共享状态（缺省回退配置）。"""
    fallback = int(settings.device_status)
    try:
        _ensure_packing_system_import()
        from src.service.device_status_store import read_device_status

        status = read_device_status(default=fallback)
    except Exception as exc:
        print(f"[4.7-状态] 读取失败，回退配置 device_status={fallback}：{exc}")
        status = fallback
    resp = {
        "code": 0,
        "msg": "success",
        "data": {"status": int(status)},
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
