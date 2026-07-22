"""FastAPI 应用：局域网可访问的 WCS 接收端。"""

from __future__ import annotations

from typing import Any, Dict

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse

from .config_loader import ReceiverSettings
from .handlers import (
    handle_boxarrive,
    handle_palletarrive,
    handle_sendcasetask,
    handle_status,
)


def create_app(settings: ReceiverSettings) -> FastAPI:
    swagger_path = settings.swagger_path
    # 与对方 http://…/swagger/index.html 对齐；同时保留 /docs 别名。
    app = FastAPI(
        title="Local WCS Receiver",
        description=(
            "机器人侧局域网接收端（sendcasetask / boxarrive / palletarrive / status）。"
            f" 对外根地址：{settings.advertise_base_url}；"
            f" 接口文档：{settings.advertise_base_url}{swagger_path}"
        ),
        version="0.1.0",
        docs_url=swagger_path,
        redoc_url="/redoc",
        openapi_url="/openapi.json",
    )
    app.state.settings = settings

    @app.get("/", include_in_schema=False)
    def root() -> Dict[str, Any]:
        return {
            "service": "local_wcs_receiver",
            "advertise_base_url": settings.advertise_base_url,
            "swagger": f"{settings.advertise_base_url}{swagger_path}",
            "peer_swagger_reference": "http://192.168.0.191:8092/swagger/index.html",
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
