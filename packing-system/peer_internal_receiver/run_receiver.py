#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Peer-side receiver: accept full packing_plan JSON and save locally.

对方电脑运行。我方 POST 到:
  http://192.168.0.202:8094/adaptor/api/wcs/internal

本接收端不做字段 schema 校验，整份 body 原样落盘（适合大 JSON）。
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def _load_config(path: Path) -> Dict[str, Any]:
    import yaml

    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        raise ValueError(f"invalid config: {path}")
    return data


def create_app(cfg: Dict[str, Any]):
    from fastapi import FastAPI, Request
    from fastapi.exceptions import RequestValidationError
    from fastapi.responses import JSONResponse

    server = dict(cfg.get("server") or {})
    save_dir = Path(
        str(cfg.get("save_dir") or server.get("save_dir") or r"D:\research_code\xiafa")
    )
    internal_path = str(cfg.get("internal_path") or "/adaptor/api/wcs/internal").strip()
    if not internal_path.startswith("/"):
        internal_path = "/" + internal_path

    app = FastAPI(
        title="Peer Internal Plan Receiver",
        description="Receives full packing_plan JSON bytes and saves to save_dir.",
        version="0.1.1",
        docs_url="/swagger/index.html",
    )

    @app.exception_handler(RequestValidationError)
    async def _validation_handler(request: Request, exc: RequestValidationError):
        # 把 422 原因打到控制台，便于联调（通常不是“文件太大”）
        detail = exc.errors()
        print(f"[422] path={request.url.path} detail={detail}")
        return JSONResponse(
            status_code=422,
            content={
                "code": 422,
                "msg": "request validation failed (not file-size)",
                "data": {"detail": detail},
            },
        )

    @app.get("/")
    def root() -> Dict[str, Any]:
        advertise = str(cfg.get("advertise_base_url") or "").rstrip("/")
        return {
            "service": "peer_internal_receiver",
            "save_dir": str(save_dir),
            "advertise_base_url": advertise,
            "endpoint": f"POST {internal_path}",
            "full_url_example": f"{advertise}{internal_path}" if advertise else None,
            "swagger": "/swagger/index.html",
            "note": "body saved as raw bytes; no schema validation",
        }

    @app.post(internal_path)
    async def receive_internal(request: Request) -> Dict[str, Any]:
        """整份 body 原样存盘；不按托盘字段 schema 校验（避免 422）。"""
        raw = await request.body()
        nbytes = len(raw)
        print(f"[RECV] bytes={nbytes} content-type={request.headers.get('content-type')}")

        if nbytes == 0:
            return {"code": 1, "msg": "empty body", "data": {}}

        # 可选：确认是 JSON 对象；失败仍把原文存盘，方便排查
        plan_id = ""
        parse_ok = False
        try:
            payload = json.loads(raw.decode("utf-8"))
            parse_ok = True
            if isinstance(payload, dict):
                plan_id = str(payload.get("packing_plan_id") or "").strip()
        except Exception as exc:
            print(f"[WARN] JSON parse failed, still save raw bytes: {exc}")

        save_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in plan_id)[:40]
        name = f"packing_plan_{safe}_{stamp}.json" if safe else f"packing_plan_{stamp}.json"
        out_path = save_dir / name
        out_path.write_bytes(raw)
        print(f"[SAVE] {out_path} ({nbytes} bytes, parse_ok={parse_ok})")
        return {
            "code": 0,
            "msg": "ok",
            "data": {
                "saved_path": str(out_path),
                "bytes": nbytes,
                "parse_ok": parse_ok,
            },
        }

    return app


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Peer internal plan receiver")
    parser.add_argument(
        "--config",
        default=str(_ROOT / "config" / "receiver_config.yaml"),
        help="config yaml path",
    )
    args = parser.parse_args(argv)
    cfg_path = Path(args.config)
    if not cfg_path.is_absolute():
        cfg_path = (_ROOT / cfg_path).resolve()
    cfg = _load_config(cfg_path)

    server = dict(cfg.get("server") or {})
    host = str(server.get("host") or cfg.get("host") or "0.0.0.0")
    port = int(server.get("port") or cfg.get("port") or 8094)
    save_dir = Path(str(cfg.get("save_dir") or r"D:\research_code\xiafa"))
    path = str(cfg.get("internal_path") or "/adaptor/api/wcs/internal")
    advertise = str(cfg.get("advertise_base_url") or f"http://127.0.0.1:{port}").rstrip("/")

    app = create_app(cfg)
    print("=" * 56)
    print("Peer Internal Receiver（对方接收端）")
    print(f"  config : {cfg_path}")
    print(f"  listen : http://{host}:{port}   ← 0.0.0.0=本机监听，不是 POST 目标")
    print(f"  请我方 POST 到: {advertise}{path}")
    print(f"  save   : {save_dir}")
    print(f"  swagger: http://127.0.0.1:{port}/swagger/index.html")
    print("=" * 56)
    print("NOTE: 422 = 校验失败（不是文件太大）。本版已关闭 schema 校验，请对方重启本脚本。")

    try:
        import uvicorn
    except ImportError:
        print("Missing deps. Run: pip install fastapi uvicorn pyyaml", file=sys.stderr)
        return 1

    # limit_concurrency 等默认即可；大 JSON 靠 raw body 落盘
    uvicorn.run(app, host=host, port=port, log_level="info", timeout_keep_alive=75)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
