#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""模拟 WCS → 本地接收端：先 sendcasetask（整盘汇报），再按箱 boxarrive。

从 ``wcs_success_box`` 挑一个已下传托盘（is_send='1'），按 seq 顺序：
  1) POST sendcasetask 一次（robot_id / box_unique_id / order_id）
  2) 对每个箱子 POST boxarrive（含尺寸与 seq）；箱与箱间隔默认 60 秒

用法（先启动 local_wcs_receiver）::

  python simulate_wcs_inbound.py
  python simulate_wcs_inbound.py --interval 60
  python simulate_wcs_inbound.py --box-unique-id <id>
  python simulate_wcs_inbound.py --dry-run
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import pymysql
import requests
import yaml
from pymysql.cursors import DictCursor

ROOT = Path(__file__).resolve().parent
RECEIVER_CFG = ROOT / "config" / "receiver_config.yaml"
PACKING_CFG = ROOT.parent / "config" / "packing_config.yaml"

IS_SEND_SENT = "1"
DEFAULT_ROBOT_ID = "001"
DEFAULT_INTERVAL_SEC = 60


def _load_yaml(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _as_path(value: Any, default: str) -> str:
    text = str(value if value is not None else default).strip()
    if not text.startswith("/"):
        text = "/" + text
    return text


def _num(value: Any) -> Any:
    """尺寸尽量用整型（与对方示例一致），否则保留 float。"""
    n = float(value or 0)
    if abs(n - round(n)) < 1e-9:
        return int(round(n))
    return n


def load_receiver_endpoints(
    config_path: Path, base_url: Optional[str]
) -> Dict[str, str]:
    raw = _load_yaml(config_path)
    server = dict(raw.get("server") or {})
    paths = dict(raw.get("paths") or {})
    port = int(server.get("port") or raw.get("port") or 8093)
    root = (base_url or f"http://127.0.0.1:{port}").rstrip("/")
    return {
        "base_url": root,
        "sendcasetask": root
        + _as_path(paths.get("sendcasetask_path"), "/adaptor/api/wcs/sendcasetask"),
        "boxarrive": root
        + _as_path(paths.get("boxarrive_path"), "/adaptor/api/wcs/boxarrive"),
    }


def load_db_config(packing_config: Path) -> Dict[str, Any]:
    raw = (_load_yaml(packing_config).get("database") or {})
    return {
        "host": str(raw.get("host") or "localhost"),
        "port": int(raw.get("port") or 3306),
        "user": str(raw.get("user") or "root"),
        "password": str(raw.get("password") or ""),
        "database": str(raw.get("database") or "zhuangdb"),
        "charset": str(raw.get("charset") or "utf8mb4"),
    }


def fetch_sent_pallet_boxes(
    db: Dict[str, Any], box_unique_id: Optional[str]
) -> List[Dict[str, Any]]:
    """返回同一托盘全部箱子行，按 seq 升序。"""
    conn = pymysql.connect(cursorclass=DictCursor, autocommit=True, **db)
    try:
        with conn.cursor() as cur:
            if box_unique_id:
                uid = str(box_unique_id).strip()
            else:
                cur.execute(
                    "SELECT box_unique_id "
                    "FROM wcs_success_box "
                    "WHERE is_send = %s "
                    "GROUP BY box_unique_id "
                    "ORDER BY MAX(created_at) DESC, box_unique_id "
                    "LIMIT 1",
                    (IS_SEND_SENT,),
                )
                row = cur.fetchone()
                if not row:
                    raise RuntimeError(
                        "wcs_success_box 中没有 is_send='1' 的已下传托盘，"
                        "请先在 UI 完成「下传 WCS」。"
                    )
                uid = str(row["box_unique_id"])

            cur.execute(
                "SELECT * FROM wcs_success_box "
                "WHERE box_unique_id = %s "
                "ORDER BY seq ASC",
                (uid,),
            )
            rows = list(cur.fetchall() or [])
            if not rows:
                raise RuntimeError(f"找不到托盘 box_unique_id={uid}")
            # 若指定了 id，仍要求已下传，避免误测未下传盘
            if all(str(r.get("is_send") or "").strip() != IS_SEND_SENT for r in rows):
                print(
                    f"[WARN] 托盘 {uid} 的箱子均非 is_send='1'，仍按所选托盘继续模拟。"
                )
            return rows
    finally:
        conn.close()


def post_json(url: str, payload: Dict[str, Any], *, dry_run: bool) -> Dict[str, Any]:
    print(f"\n→ POST {url}")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    if dry_run:
        print("(dry-run，未真正发送)")
        return {"code": 0, "msg": "dry-run", "data": {}}
    resp = requests.post(url, json=payload, timeout=30)
    try:
        body = resp.json()
    except Exception:
        body = {"code": -1, "msg": resp.text[:500], "data": {}}
    print(f"← HTTP {resp.status_code}  {json.dumps(body, ensure_ascii=False)}")
    resp.raise_for_status()
    if isinstance(body, dict) and body.get("code") not in (None, 0):
        raise RuntimeError(f"接口返回错误: code={body.get('code')}, msg={body.get('msg')}")
    return body if isinstance(body, dict) else {"code": 0, "msg": "ok", "data": body}


def build_sendcasetask(robot_id: str, row: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "robot_id": robot_id,
        "box_unique_id": str(row.get("box_unique_id") or ""),
        "order_id": str(row.get("order_id") or ""),
    }


def build_boxarrive(robot_id: str, row: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "robot_id": robot_id,
        "box_unique_id": str(row.get("box_unique_id") or ""),
        "order_id": str(row.get("order_id") or ""),
        "length": _num(row.get("raw_length")),
        "width": _num(row.get("raw_width")),
        "height": _num(row.get("raw_height")),
        "seq": int(row.get("seq") or 0),
    }


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="模拟 WCS sendcasetask + 按箱 boxarrive")
    p.add_argument(
        "--interval",
        type=float,
        default=DEFAULT_INTERVAL_SEC,
        help=f"相邻两次 boxarrive 间隔秒数（默认 {DEFAULT_INTERVAL_SEC}）",
    )
    p.add_argument("--robot-id", default=DEFAULT_ROBOT_ID, help="机器人编号")
    p.add_argument(
        "--box-unique-id",
        default=None,
        help="指定已下传托盘；默认取库中最近一个 is_send='1' 的托盘",
    )
    p.add_argument(
        "--base-url",
        default=None,
        help="接收端根地址；默认 http://127.0.0.1:<receiver.port>",
    )
    p.add_argument(
        "--receiver-config",
        type=Path,
        default=RECEIVER_CFG,
        help="local_wcs_receiver 配置路径",
    )
    p.add_argument(
        "--packing-config",
        type=Path,
        default=PACKING_CFG,
        help="packing_config.yaml（读 database）",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="只打印将发送的 JSON，不真正 POST",
    )
    return p.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)
    endpoints = load_receiver_endpoints(args.receiver_config, args.base_url)
    db = load_db_config(args.packing_config)
    rows = fetch_sent_pallet_boxes(db, args.box_unique_id)

    uid = str(rows[0].get("box_unique_id") or "")
    order_id = str(rows[0].get("order_id") or "")
    print(
        f"选用托盘 box_unique_id={uid}  order_id={order_id}  "
        f"箱数={len(rows)}  interval={args.interval}s"
    )
    print(f"目标接收端 {endpoints['base_url']}")

    # 1) 整盘汇报：WCS 选中该托盘准备码垛
    post_json(
        endpoints["sendcasetask"],
        build_sendcasetask(args.robot_id, rows[0]),
        dry_run=args.dry_run,
    )

    # 2) 按 seq 逐箱到达：每条表示该箱已到、可启动码垛
    for i, row in enumerate(rows):
        if i > 0 and args.interval > 0:
            print(f"\n等待 {args.interval:g}s 后发送下一箱 (seq={row.get('seq')}) …")
            if not args.dry_run:
                time.sleep(args.interval)
            else:
                print("(dry-run，跳过等待)")
        post_json(
            endpoints["boxarrive"],
            build_boxarrive(args.robot_id, row),
            dry_run=args.dry_run,
        )
        print(
            f"[boxarrive] 第 {i + 1}/{len(rows)} 箱已通知 "
            f"(seq={row.get('seq')}, product_code={row.get('product_code')})"
        )

    print("\n全部完成。")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\n已中断。", file=sys.stderr)
        raise SystemExit(130)
    except Exception as exc:
        print(f"失败：{exc}", file=sys.stderr)
        raise SystemExit(1)
