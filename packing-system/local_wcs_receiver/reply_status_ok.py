#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""仅提供接口 4.7：GET /api/status，固定返回 code=0。

对方轮询系统状态时用。一运行即可联调，不依赖 FastAPI / 完整 receiver。

用法::

  python reply_status_ok.py
  python reply_status_ok.py --port 7002
  python reply_status_ok.py --host 0.0.0.0 --port 7002 --status 0

对方请求::

  GET http://<本机IP>:7002/api/status

固定回复::

  {"code": 0, "msg": "success", "data": {"status": 0}}
"""

from __future__ import annotations

import argparse
import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Optional


DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 7002
STATUS_PATH = "/api/status"


def parse_args(argv: Optional[list] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="接口 4.7 固定回 code=0")
    p.add_argument("--host", default=DEFAULT_HOST, help="监听地址（默认 0.0.0.0）")
    p.add_argument(
        "--port",
        type=int,
        default=DEFAULT_PORT,
        help=f"端口（默认 {DEFAULT_PORT}，与 receiver_config 一致）",
    )
    p.add_argument(
        "--status",
        type=int,
        default=0,
        help="data.status：0=就绪，1=执行中，99=停止/异常（默认 0）",
    )
    p.add_argument(
        "--path",
        default=STATUS_PATH,
        help=f"接口 path（默认 {STATUS_PATH}）",
    )
    return p.parse_args(argv)


def main(argv: Optional[list] = None) -> int:
    args = parse_args(argv)
    path = args.path if str(args.path).startswith("/") else f"/{args.path}"
    device_status = int(args.status)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt: str, *a) -> None:
            print(f"[4.7] {self.address_string()} - {fmt % a}")

        def _send_json(self, code_http: int, payload: dict) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(code_http)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:  # noqa: N802
            req_path = self.path.split("?", 1)[0]
            if req_path.rstrip("/") == path.rstrip("/") or req_path == path:
                payload = {
                    "code": 0,
                    "msg": "success",
                    "data": {"status": device_status},
                }
                print(f"[4.7] ← GET {req_path} → {payload}")
                self._send_json(200, payload)
                return
            self._send_json(
                404,
                {"code": 1, "msg": f"only {path} supported", "data": {}},
            )

        def do_POST(self) -> None:  # noqa: N802
            self._send_json(
                405,
                {"code": 1, "msg": "4.7 is GET only", "data": {}},
            )

    server = ThreadingHTTPServer((args.host, int(args.port)), Handler)
    print("=" * 50)
    print("接口 4.7 就绪应答（固定 code=0）")
    print(f"  监听：http://{args.host}:{args.port}{path}")
    print(f"  回复：code=0, data.status={device_status}")
    print("  按 Ctrl+C 结束")
    print("=" * 50)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止。")
        return 0
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
