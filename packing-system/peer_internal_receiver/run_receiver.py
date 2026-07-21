#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Peer-side receiver: accept full packing_plan JSON and save locally.

Give this folder to the other party. They run:

    pip install fastapi uvicorn pyyaml
    python run_receiver.py

Default listen: 0.0.0.0:8094
Default save:   D:\\research_code\\xiafa\\packing_plan_YYYYMMDD_HHMMSS.json

POST body = entire packing_plan JSON (same as packing-workspace/output/packing_plan_*.json).
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict

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

    save_dir = Path(str(cfg.get("save_dir") or r"D:\research_code\xiafa"))
    internal_path = str(cfg.get("internal_path") or "/adaptor/api/wcs/internal").strip()
    if not internal_path.startswith("/"):
        internal_path = "/" + internal_path

    app = FastAPI(
        title="Peer Internal Plan Receiver",
        description="Receives full packing_plan JSON and saves to save_dir.",
        version="0.1.0",
        docs_url="/swagger/index.html",
    )

    @app.get("/")
    def root() -> Dict[str, Any]:
        return {
            "service": "peer_internal_receiver",
            "save_dir": str(save_dir),
            "endpoint": f"POST {internal_path}",
            "swagger": "/swagger/index.html",
        }

    @app.post(internal_path)
    async def receive_internal(request: Request) -> Dict[str, Any]:
        try:
            payload = await request.json()
        except Exception:
            return {"code": 1, "msg": "invalid json body", "data": {}}
        if not isinstance(payload, dict):
            return {"code": 1, "msg": "body must be a JSON object", "data": {}}

        save_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        # Prefer original-like name if present in payload id fields, else timestamp.
        plan_id = str(payload.get("packing_plan_id") or "").strip()
        safe = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in plan_id)[:40]
        name = f"packing_plan_{safe}_{stamp}.json" if safe else f"packing_plan_{stamp}.json"
        out_path = save_dir / name
        out_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(f"[SAVE] {out_path} ({out_path.stat().st_size} bytes)")
        return {
            "code": 0,
            "msg": "ok",
            "data": {"saved_path": str(out_path), "bytes": out_path.stat().st_size},
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

    host = str(cfg.get("host") or "0.0.0.0")
    port = int(cfg.get("port") or 8094)
    save_dir = Path(str(cfg.get("save_dir") or r"D:\research_code\xiafa"))
    path = str(cfg.get("internal_path") or "/adaptor/api/wcs/internal")

    app = create_app(cfg)
    print("=" * 56)
    print("Peer Internal Receiver")
    print(f"  config : {cfg_path}")
    print(f"  listen : http://{host}:{port}")
    print(f"  POST   : http://{host}:{port}{path}")
    print(f"  save   : {save_dir}")
    print(f"  swagger: http://127.0.0.1:{port}/swagger/index.html")
    print("=" * 56)
    print("TODO: packing side api_base_url must point to this host:port when testing.")

    try:
        import uvicorn
    except ImportError:
        print("Missing deps. Run: pip install fastapi uvicorn pyyaml", file=sys.stderr)
        return 1

    uvicorn.run(app, host=host, port=port, log_level="info")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
