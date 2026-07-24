"""FastAPI 应用：局域网可访问的 WCS 接收端。"""

from __future__ import annotations

import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse

from .config_loader import ReceiverSettings
from .handlers import (
    handle_boxarrive,
    handle_palletarrive,
    handle_sendcasetask,
    handle_status,
)

_PACKING_SYSTEM_ROOT = Path(__file__).resolve().parents[2]


def _ensure_packing_system_import() -> None:
    root = str(_PACKING_SYSTEM_ROOT.resolve())
    src = str((_PACKING_SYSTEM_ROOT / "src").resolve())
    sys.path[:] = [
        p for p in sys.path if Path(p).resolve().as_posix() != Path(src).as_posix()
    ]
    if root not in sys.path:
        sys.path.insert(0, root)


def _start_plc_watcher(settings: ReceiverSettings):
    _ensure_packing_system_import()
    from src.service.plc_state_watcher import PlcStateWatcher

    watcher = PlcStateWatcher(
        config_path=settings.packing_config_path,
        poll_interval_sec=settings.plc_auto_poll_interval_sec,
        enabled=settings.plc_auto_enabled,
    )
    watcher.start()
    return watcher


def _start_camera_state_watcher(settings: ReceiverSettings):
    _ensure_packing_system_import()
    from src.service.camera_state_watcher import CameraStateWatcher

    watcher = CameraStateWatcher(
        config_path=settings.packing_config_path,
        poll_interval_sec=settings.state_judge_poll_interval_sec,
        enabled=settings.state_judge_enabled,
        tol_mm=settings.state_judge_tol_mm,
    )
    watcher.start()
    return watcher


def create_app(settings: ReceiverSettings) -> FastAPI:
    swagger_path = settings.swagger_path
    watcher_holder: Dict[str, Any] = {
        "plc_watcher": None,
        "camera_watcher": None,
    }

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        watcher_holder["camera_watcher"] = _start_camera_state_watcher(settings)
        watcher_holder["plc_watcher"] = _start_plc_watcher(settings)
        try:
            yield
        finally:
            for key, label in (
                ("plc_watcher", "PLC监听"),
                ("camera_watcher", "判态监听"),
            ):
                watcher = watcher_holder.get(key)
                if watcher is not None:
                    try:
                        watcher.stop()
                    except Exception as exc:
                        print(f"[{label}] 停止失败：{exc}")
                    watcher_holder[key] = None

    # 与对方 http://…/swagger/index.html 对齐；同时保留 /docs 别名。
    app = FastAPI(
        title="Local WCS Receiver",
        description=(
            "机器人侧局域网接收端（sendcasetask / boxarrive / palletarrive / status）。"
            f" 对外根地址：{settings.advertise_base_url}；"
            f" 接口文档：{settings.advertise_base_url}{swagger_path}"
        ),
        version="0.2.0",
        docs_url=swagger_path,
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.plc_watcher = watcher_holder
    app.state.watchers = watcher_holder

    @app.get("/", include_in_schema=False)
    def root() -> Dict[str, Any]:
        return {
            "service": "local_wcs_receiver",
            "advertise_base_url": settings.advertise_base_url,
            "swagger": f"{settings.advertise_base_url}{swagger_path}",
            "peer_swagger_reference": "http://192.168.0.191:8092/swagger/index.html",
            "plc_auto": {
                "enabled": settings.plc_auto_enabled,
                "poll_interval_sec": settings.plc_auto_poll_interval_sec,
            },
            "state_judge": {
                "enabled": settings.state_judge_enabled,
                "poll_interval_sec": settings.state_judge_poll_interval_sec,
                "tol_mm": settings.state_judge_tol_mm,
            },
            "endpoints": [
                f"POST {settings.sendcasetask_path}",
                f"POST {settings.boxarrive_path}",
                f"POST {settings.palletarrive_path}",
                f"GET  {settings.status_path}",
            ],
        }

    @app.get("/docs", include_in_schema=False)
    def docs_alias() -> RedirectResponse:
        return RedirectResponse(url=swagger_path)

    @app.get("/swagger", include_in_schema=False)
    def swagger_alias() -> RedirectResponse:
        return RedirectResponse(url=swagger_path)

    @app.post(settings.sendcasetask_path)
    async def sendcasetask(request: Request) -> Dict[str, Any]:
        body = await _json_body(request)
        return handle_sendcasetask(settings, body)

    @app.post(settings.boxarrive_path)
    async def boxarrive(request: Request) -> Dict[str, Any]:
        body = await _json_body(request)
        return handle_boxarrive(settings, body)

    @app.post(settings.palletarrive_path)
    async def palletarrive(request: Request) -> Dict[str, Any]:
        body = await _json_body(request)
        return handle_palletarrive(settings, body)

    @app.get(settings.status_path)
    def status_get() -> Dict[str, Any]:
        return handle_status(settings)

    @app.post(settings.status_path)
    def status_post() -> Dict[str, Any]:
        return handle_status(settings)

    return app


async def _json_body(request: Request) -> Dict[str, Any]:
    try:
        data = await request.json()
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}
