#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""清除现场码垛 / WCS 模拟联调残留，方便重新跑 simulate_wcs_inbound。

默认清除：
  1) packing-workspace/runtime 下 live_stack_*.json（历史托盘 / 当前会话 / 指令）
  2) MySQL wcs_success_box 的 camera_* 与 state（不改 is_send）
  3) MySQL wcs_plc_queue 全部队列

用法::

  python reset_live_stack_sim.py
  python reset_live_stack_sim.py --box-unique-id <id>
  python reset_live_stack_sim.py --logs
  python reset_live_stack_sim.py --dry-run
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

import pymysql
import yaml
from pymysql.cursors import DictCursor

ROOT = Path(__file__).resolve().parent
PACKING_SYSTEM = ROOT.parent
PACKING_CFG = PACKING_SYSTEM / "config" / "packing_config.yaml"


def _load_yaml(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def resolve_workspace() -> Path:
    env = os.environ.get("PACKING_WORKSPACE", "").strip()
    if env:
        return Path(env).expanduser().resolve()
    return (PACKING_SYSTEM.parent / "packing-workspace").resolve()


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


def clear_runtime_files(workspace: Path, *, dry_run: bool) -> List[str]:
    runtime = workspace / "runtime"
    actions: List[str] = []
    history = runtime / "live_stack_pallets.json"
    session = runtime / "live_stack_session.json"
    command = runtime / "live_stack_command.json"

    if history.is_file() or not dry_run:
        actions.append(f"写入 [] → {history}")
        if not dry_run:
            history.parent.mkdir(parents=True, exist_ok=True)
            history.write_text("[]\n", encoding="utf-8")

    for path in (session, command):
        if path.is_file():
            actions.append(f"删除 {path}")
            if not dry_run:
                try:
                    path.unlink()
                except OSError as exc:
                    actions.append(f"  删除失败: {exc}")
        else:
            actions.append(f"跳过（不存在）{path.name}")
    return actions


def clear_receiver_logs(*, dry_run: bool) -> List[str]:
    log_dir = ROOT / "logs"
    actions: List[str] = []
    if not log_dir.is_dir():
        return [f"跳过（无日志目录）{log_dir}"]
    files = sorted(p for p in log_dir.iterdir() if p.is_file())
    if not files:
        return [f"跳过（日志目录为空）{log_dir}"]
    for path in files:
        actions.append(f"删除 {path}")
        if not dry_run:
            try:
                path.unlink()
            except OSError as exc:
                actions.append(f"  删除失败: {exc}")
    return actions


def clear_db_sim_state(
    db: Dict[str, Any],
    box_unique_id: Optional[str],
    *,
    dry_run: bool,
) -> List[str]:
    """清空 camera_* / state；可选按托盘过滤。不清 is_send。"""
    actions: List[str] = []
    conn = pymysql.connect(cursorclass=DictCursor, autocommit=True, **db)
    try:
        with conn.cursor() as cur:
            if box_unique_id:
                uid = str(box_unique_id).strip()
                cur.execute(
                    "SELECT COUNT(*) AS n FROM wcs_success_box "
                    "WHERE box_unique_id = %s "
                    "  AND (state IS NOT NULL "
                    "       OR camera_length IS NOT NULL "
                    "       OR camera_width IS NOT NULL "
                    "       OR camera_height IS NOT NULL)",
                    (uid,),
                )
                n = int((cur.fetchone() or {}).get("n") or 0)
                actions.append(
                    f"wcs_success_box: 将清空托盘 {uid} 的 camera_*/state（匹配 {n} 行）"
                )
                if not dry_run and n:
                    cur.execute(
                        "UPDATE wcs_success_box "
                        "SET camera_length = NULL, camera_width = NULL, "
                        "    camera_height = NULL, state = NULL "
                        "WHERE box_unique_id = %s",
                        (uid,),
                    )
                    actions.append(f"  已 UPDATE {int(cur.rowcount or 0)} 行")
            else:
                cur.execute(
                    "SELECT COUNT(*) AS n FROM wcs_success_box "
                    "WHERE state IS NOT NULL "
                    "   OR camera_length IS NOT NULL "
                    "   OR camera_width IS NOT NULL "
                    "   OR camera_height IS NOT NULL"
                )
                n = int((cur.fetchone() or {}).get("n") or 0)
                actions.append(
                    f"wcs_success_box: 将清空全部托盘的 camera_*/state（匹配 {n} 行）"
                )
                if not dry_run and n:
                    cur.execute(
                        "UPDATE wcs_success_box "
                        "SET camera_length = NULL, camera_width = NULL, "
                        "    camera_height = NULL, state = NULL "
                        "WHERE state IS NOT NULL "
                        "   OR camera_length IS NOT NULL "
                        "   OR camera_width IS NOT NULL "
                        "   OR camera_height IS NOT NULL"
                    )
                    actions.append(f"  已 UPDATE {int(cur.rowcount or 0)} 行")

            if box_unique_id:
                uid = str(box_unique_id).strip()
                cur.execute(
                    "SELECT COUNT(*) AS n FROM wcs_plc_queue "
                    "WHERE box_unique_id = %s",
                    (uid,),
                )
                nq = int((cur.fetchone() or {}).get("n") or 0)
                actions.append(
                    f"wcs_plc_queue: 将删除托盘 {uid} 的队列（{nq} 行）"
                )
                if not dry_run and nq:
                    cur.execute(
                        "DELETE FROM wcs_plc_queue WHERE box_unique_id = %s",
                        (uid,),
                    )
                    actions.append(f"  已 DELETE {int(cur.rowcount or 0)} 行")
            else:
                cur.execute("SELECT COUNT(*) AS n FROM wcs_plc_queue")
                nq = int((cur.fetchone() or {}).get("n") or 0)
                actions.append(f"wcs_plc_queue: 将清空全部队列（{nq} 行）")
                if not dry_run and nq:
                    cur.execute("DELETE FROM wcs_plc_queue")
                    actions.append(f"  已 DELETE {int(cur.rowcount or 0)} 行")
    finally:
        conn.close()
    return actions


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="清除现场码垛 / WCS 模拟残留，便于重新联调"
    )
    p.add_argument(
        "--box-unique-id",
        default=None,
        help="只清该托盘的 DB camera/state 与 PLC 队列；默认清全部模拟残留",
    )
    p.add_argument(
        "--keep-db",
        action="store_true",
        help="只清 runtime 文件，不动 MySQL",
    )
    p.add_argument(
        "--logs",
        action="store_true",
        help="同时删除 local_wcs_receiver/logs 下请求落盘",
    )
    p.add_argument(
        "--packing-config",
        type=Path,
        default=PACKING_CFG,
        help="packing_config.yaml（读 database）",
    )
    p.add_argument(
        "--workspace",
        type=Path,
        default=None,
        help="packing-workspace 根目录；默认 PACKING_WORKSPACE 或仓库同级",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="只打印将执行的操作，不真正修改",
    )
    return p.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)
    workspace = (
        Path(args.workspace).expanduser().resolve()
        if args.workspace
        else resolve_workspace()
    )
    print(f"工作区: {workspace}")
    if args.dry_run:
        print("（dry-run，不会真正修改）")

    for line in clear_runtime_files(workspace, dry_run=args.dry_run):
        print(f"[runtime] {line}")

    if args.logs:
        for line in clear_receiver_logs(dry_run=args.dry_run):
            print(f"[logs] {line}")

    if not args.keep_db:
        db = load_db_config(args.packing_config)
        print(
            f"数据库: {db['user']}@{db['host']}:{db['port']}/{db['database']}"
        )
        for line in clear_db_sim_state(
            db, args.box_unique_id, dry_run=args.dry_run
        ):
            print(f"[db] {line}")
    else:
        print("[db] 已跳过（--keep-db）")

    print("\n完成。可重新运行 simulate_wcs_inbound.py。")
    print("提示：若看板仍显示旧托盘，点一次「刷新」或重启 UI。")
    print("注意：未改动 is_send（已下传标记保留）。")
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
