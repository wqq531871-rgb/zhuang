#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""启动局域网 WCS 接收端。

用法:
    python run_receiver.py
    python run_receiver.py --config config/receiver_config.yaml
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def _parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Local WCS receiver (LAN)")
    parser.add_argument(
        "--config",
        default=str(_ROOT / "config" / "receiver_config.yaml"),
        help="专用配置文件路径（默认 config/receiver_config.yaml）",
    )
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = _parse_args(argv)
    config_path = Path(args.config)
    if not config_path.is_absolute():
        config_path = (_ROOT / config_path).resolve()

    from app.config_loader import load_settings
    from app.server import create_app

    settings = load_settings(config_path)
    app = create_app(settings)

    print("=" * 56)
    print("Local WCS Receiver 已启动配置")
    print(f"  config : {settings.config_path}")
    print(f"  listen : http://{settings.host}:{settings.port}")
    print(f"  告知对方: {settings.advertise_base_url}")
    print("  路径:")
    print(f"    POST {settings.advertise_base_url}{settings.sendcasetask_path}")
    print(f"    POST {settings.advertise_base_url}{settings.boxarrive_path}")
    print(f"    POST {settings.advertise_base_url}{settings.palletarrive_path}")
    print(f"    GET  {settings.advertise_base_url}{settings.status_path}")
    print(f"  Swagger: {settings.advertise_base_url}{settings.swagger_path}")
    print(f"  对方文档参考: http://192.168.0.191:8092/swagger/index.html")
    print(f"  logs   : {settings.log_dir}")
    print("=" * 56)
    print("TODO(防火墙): Windows 请放行端口入站，否则对方连不上。")
    print("路径核对: 接口2下传=/api/wcs/sendpalletplanresult；状态=/api/status")

    try:
        import uvicorn
    except ImportError:
        print(
            "缺少依赖。请先: pip install -r requirements.txt",
            file=sys.stderr,
        )
        return 1

    uvicorn.run(
        app,
        host=settings.host,
        port=settings.port,
        log_level="info",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
