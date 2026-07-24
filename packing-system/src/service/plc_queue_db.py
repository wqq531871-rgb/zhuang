# -*- coding: utf-8 -*-
"""PLC 命令构造与队列表 ``wcs_plc_queue``。

正常路径：其它模块写好 ``wcs_success_box.state`` 后，监听自动入队并下传。
界面「应急补发」仍可对手动 pending 项调用 ``stub_send_plc_command``。
"""

from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

import pymysql
from pymysql.cursors import DictCursor

from src.service.success_box_db import (
    DatabaseConfig,
    load_database_config_from_yaml,
)

STATUS_PENDING = "pending"
STATUS_SENT = "sent"
STATUS_FAILED = "failed"


def _num(value: Any) -> float:
    return float(value or 0.0)


def build_plc_command_from_box_row(row: Dict[str, Any]) -> Dict[str, Any]:
    """从 ``wcs_success_box`` 一行构造 DB19 字段（不发送）。

    映射对齐 packing-robot 设计文档：
    DBW0/2/4 尺寸，DBW6/8 放置 xy，DBW10 顶高，DBW12 state，DBW16 seq。
    """
    length = _num(row.get("raw_length"))
    width = _num(row.get("raw_width"))
    height = _num(row.get("raw_height"))
    pos_x = _num(row.get("pos_x"))
    pos_y = _num(row.get("pos_y"))
    pos_z = _num(row.get("pos_z"))
    state = int(row.get("state") or 1)
    seq = int(row.get("seq") or 0)
    return {
        "dbw0_length": int(round(length)),
        "dbw2_width": int(round(width)),
        "dbw4_height": int(round(height)),
        "dbw6_pos_x": int(round(pos_x)),
        "dbw8_pos_y": int(round(pos_y)),
        "dbw10_top_z": int(round(pos_z + height)),
        "dbw12_state": state,
        "dbw16_seq": seq,
        "box_unique_id": str(row.get("box_unique_id") or ""),
        "product_code": str(row.get("product_code") or ""),
        "pallet_id": str(row.get("pallet_id") or ""),
        "order_id": str(row.get("order_id") or ""),
        "raw": {
            "raw_length": length,
            "raw_width": width,
            "raw_height": height,
            "pos_x": pos_x,
            "pos_y": pos_y,
            "pos_z": pos_z,
            "stack_height_before": _num(row.get("stack_height_before")),
        },
    }


class WcsPlcQueueRepository:
    def __init__(self, config: DatabaseConfig):
        self._cfg = config

    def _connect(self):
        return pymysql.connect(
            host=self._cfg.host,
            port=self._cfg.port,
            user=self._cfg.user,
            password=self._cfg.password,
            database=self._cfg.database,
            charset=self._cfg.charset,
            cursorclass=DictCursor,
            autocommit=False,
        )

    @contextmanager
    def _cursor(self):
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                yield conn, cur
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def fetch_success_box_row(
        self, box_unique_id: str, seq: int
    ) -> Optional[Dict[str, Any]]:
        uid = str(box_unique_id or "").strip()
        seq_i = int(seq)
        with self._cursor() as (_conn, cur):
            cur.execute(
                "SELECT * FROM wcs_success_box "
                "WHERE box_unique_id = %s AND seq = %s LIMIT 1",
                (uid, seq_i),
            )
            row = cur.fetchone()
            return dict(row) if row else None

    def count_boxes_on_pallet(self, box_unique_id: str) -> int:
        uid = str(box_unique_id or "").strip()
        with self._cursor() as (_conn, cur):
            cur.execute(
                "SELECT COUNT(*) AS n FROM wcs_success_box WHERE box_unique_id = %s",
                (uid,),
            )
            row = cur.fetchone() or {}
            return int(row.get("n") or 0)

    def _parse_queue_row(self, row: Dict[str, Any]) -> Dict[str, Any]:
        item = dict(row)
        cmd = item.get("command_json")
        if isinstance(cmd, (bytes, bytearray)):
            cmd = cmd.decode("utf-8", errors="replace")
        if isinstance(cmd, str):
            try:
                item["command"] = json.loads(cmd)
            except json.JSONDecodeError:
                item["command"] = {}
        elif isinstance(cmd, dict):
            item["command"] = cmd
        else:
            item["command"] = {}
        return item

    def enqueue(
        self,
        *,
        box_unique_id: str,
        seq: int,
        state: int,
        command: Dict[str, Any],
        product_code: Optional[str] = None,
        item_id: Optional[str] = None,
        target_orientation_deg: Optional[int] = None,
        camera_orientation_deg: Optional[int] = None,
    ) -> int:
        """构造结果入队；同一 (uid, seq) 已存在则覆盖命令并重置为 pending。"""
        uid = str(box_unique_id or "").strip()
        seq_i = int(seq)
        payload = json.dumps(command, ensure_ascii=False)
        sql = (
            "INSERT INTO wcs_plc_queue ("
            "box_unique_id, seq, product_code, item_id, state, "
            "target_orientation_deg, camera_orientation_deg, command_json, status"
            ") VALUES ("
            "%s, %s, %s, %s, %s, %s, %s, %s, %s"
            ") ON DUPLICATE KEY UPDATE "
            "product_code=VALUES(product_code), "
            "item_id=VALUES(item_id), "
            "state=VALUES(state), "
            "target_orientation_deg=VALUES(target_orientation_deg), "
            "camera_orientation_deg=VALUES(camera_orientation_deg), "
            "command_json=VALUES(command_json), "
            "status=%s, "
            "send_note=NULL, "
            "sent_at=NULL, "
            "created_at=CURRENT_TIMESTAMP"
        )
        with self._cursor() as (_conn, cur):
            cur.execute(
                sql,
                (
                    uid,
                    seq_i,
                    product_code,
                    item_id,
                    int(state),
                    target_orientation_deg,
                    camera_orientation_deg,
                    payload,
                    STATUS_PENDING,
                    STATUS_PENDING,
                ),
            )
            # 取该行 id
            cur.execute(
                "SELECT id FROM wcs_plc_queue "
                "WHERE box_unique_id = %s AND seq = %s LIMIT 1",
                (uid, seq_i),
            )
            row = cur.fetchone() or {}
            return int(row.get("id") or 0)

    def list_recent(self, limit: int = 30) -> List[Dict[str, Any]]:
        lim = max(1, min(int(limit), 200))
        with self._cursor() as (_conn, cur):
            cur.execute(
                "SELECT * FROM wcs_plc_queue "
                "ORDER BY "
                "CASE status WHEN 'pending' THEN 0 WHEN 'failed' THEN 1 ELSE 2 END, "
                "created_at DESC, id DESC "
                "LIMIT %s",
                (lim,),
            )
            return [self._parse_queue_row(row) for row in (cur.fetchall() or [])]

    def list_for_pallet(self, box_unique_id: str) -> List[Dict[str, Any]]:
        """当前托盘码放队列，按 seq 升序（跟计算结果该盘箱序一致）。"""
        uid = str(box_unique_id or "").strip()
        if not uid:
            return []
        with self._cursor() as (_conn, cur):
            cur.execute(
                "SELECT * FROM wcs_plc_queue "
                "WHERE box_unique_id = %s "
                "ORDER BY seq ASC, id ASC",
                (uid,),
            )
            return [self._parse_queue_row(row) for row in (cur.fetchall() or [])]

    def clear_all(self) -> int:
        """新一轮装箱结果入库后清空旧码放队列，避免界面一直显示上一盘残留。"""
        with self._cursor() as (_conn, cur):
            cur.execute("DELETE FROM wcs_plc_queue")
            return int(cur.rowcount or 0)

    def get_by_id(self, queue_id: int) -> Optional[Dict[str, Any]]:
        with self._cursor() as (_conn, cur):
            cur.execute(
                "SELECT * FROM wcs_plc_queue WHERE id = %s LIMIT 1",
                (int(queue_id),),
            )
            row = cur.fetchone()
            if not row:
                return None
            return self._parse_queue_row(row)

    def next_required_seq(self, box_unique_id: str) -> int:
        """同一托盘下一条必须下传的 seq（已发送最大序号 + 1，至少为 1）。"""
        uid = str(box_unique_id or "").strip()
        with self._cursor() as (_conn, cur):
            cur.execute(
                "SELECT COALESCE(MAX(seq), 0) AS m FROM wcs_plc_queue "
                "WHERE box_unique_id = %s AND status = %s",
                (uid, STATUS_SENT),
            )
            row = cur.fetchone() or {}
            return int(row.get("m") or 0) + 1

    def mark_sent_stub(self, queue_id: int, note: str = "stub_send") -> bool:
        """桩发送：不写 PLC，只标记 sent 并记说明。"""
        with self._cursor() as (_conn, cur):
            cur.execute(
                "UPDATE wcs_plc_queue "
                "SET status = %s, send_note = %s, sent_at = %s "
                "WHERE id = %s AND status = %s",
                (
                    STATUS_SENT,
                    str(note)[:500],
                    datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    int(queue_id),
                    STATUS_PENDING,
                ),
            )
            return int(cur.rowcount or 0) > 0

    def get_queue_status(
        self, box_unique_id: str, seq: int
    ) -> Optional[str]:
        uid = str(box_unique_id or "").strip()
        with self._cursor() as (_conn, cur):
            cur.execute(
                "SELECT status FROM wcs_plc_queue "
                "WHERE box_unique_id = %s AND seq = %s LIMIT 1",
                (uid, int(seq)),
            )
            row = cur.fetchone()
            if not row:
                return None
            return str(row.get("status") or "")

    def get_id_by_uid_seq(self, box_unique_id: str, seq: int) -> Optional[int]:
        uid = str(box_unique_id or "").strip()
        with self._cursor() as (_conn, cur):
            cur.execute(
                "SELECT id FROM wcs_plc_queue "
                "WHERE box_unique_id = %s AND seq = %s LIMIT 1",
                (uid, int(seq)),
            )
            row = cur.fetchone()
            if not row:
                return None
            return int(row.get("id") or 0) or None

    def list_state_ready_unsent(self, limit: int = 50) -> List[Dict[str, Any]]:
        """``state`` 已是 1/2，且尚未 sent 的 success_box 行（按 uid, seq）。"""
        lim = max(1, min(int(limit), 200))
        sql = (
            "SELECT s.* FROM wcs_success_box s "
            "WHERE s.state IN (1, 2) "
            "AND NOT EXISTS ("
            "  SELECT 1 FROM wcs_plc_queue q "
            "  WHERE q.box_unique_id = s.box_unique_id "
            "    AND q.seq = s.seq AND q.status = %s"
            ") "
            "ORDER BY s.box_unique_id ASC, s.seq ASC "
            "LIMIT %s"
        )
        with self._cursor() as (_conn, cur):
            cur.execute(sql, (STATUS_SENT, lim))
            return [dict(row) for row in (cur.fetchall() or [])]


def enqueue_plc_after_rotation(
    *,
    box_unique_id: str,
    seq: int,
    state: int,
    target_orientation_deg: Optional[int] = None,
    camera_orientation_deg: Optional[int] = None,
    item_id: Optional[str] = None,
    product_code: Optional[str] = None,
    config_path: Optional[Path] = None,
    db_config: Optional[DatabaseConfig] = None,
) -> Dict[str, Any]:
    """state 就绪后：读 success_box 行 → 构造命令 → 入队（不发送）。"""
    cfg = db_config or load_database_config_from_yaml(config_path)
    repo = WcsPlcQueueRepository(cfg)
    uid = str(box_unique_id or "").strip()
    seq_i = int(seq)
    row = repo.fetch_success_box_row(uid, seq_i)
    if row is None:
        return {
            "plc": {
                "ok": False,
                "reason": "success_box_row_missing",
                "box_unique_id": uid,
                "seq": seq_i,
            }
        }
    # 用刚写入的 state 覆盖（表行应已更新，再保险一次）
    row = dict(row)
    row["state"] = int(state)
    command = build_plc_command_from_box_row(row)
    qid = repo.enqueue(
        box_unique_id=uid,
        seq=seq_i,
        state=int(state),
        command=command,
        product_code=product_code or str(row.get("product_code") or "") or None,
        item_id=item_id,
        target_orientation_deg=target_orientation_deg,
        camera_orientation_deg=camera_orientation_deg,
    )
    total = repo.count_boxes_on_pallet(uid)
    print(
        f"[PLC入队] id={qid} box={uid} seq={seq_i}/{total} "
        f"state={state}（待自动/应急下传）"
    )
    return {
        "plc": {
            "ok": True,
            "reason": "enqueued",
            "queue_id": qid,
            "box_unique_id": uid,
            "seq": seq_i,
            "total_boxes": total,
            "state": int(state),
            "status": STATUS_PENDING,
            "command": command,
        }
    }


def enqueue_from_success_box_row(
    row: Dict[str, Any],
    *,
    config_path: Optional[Path] = None,
    db_config: Optional[DatabaseConfig] = None,
) -> Dict[str, Any]:
    """从 success_box 行构造入队（读表上的 state）。"""
    state = int(row.get("state") or 0)
    if state not in (1, 2):
        return {
            "plc": {
                "ok": False,
                "reason": "state_not_ready",
                "box_unique_id": str(row.get("box_unique_id") or ""),
                "seq": int(row.get("seq") or 0),
                "state": state,
            }
        }
    return enqueue_plc_after_rotation(
        box_unique_id=str(row.get("box_unique_id") or ""),
        seq=int(row.get("seq") or 0),
        state=state,
        product_code=str(row.get("product_code") or "") or None,
        config_path=config_path,
        db_config=db_config,
    )


def auto_process_state_ready_boxes(
    *,
    config_path: Optional[Path] = None,
    db_config: Optional[DatabaseConfig] = None,
    limit: int = 50,
) -> Dict[str, Any]:
    """扫描 state 就绪箱：入队（若尚未）并按 seq 自动下传。

    同一托盘仍强制升序：未轮到的箱只入队、本轮不发送。
    """
    cfg = db_config or load_database_config_from_yaml(config_path)
    repo = WcsPlcQueueRepository(cfg)
    ready = repo.list_state_ready_unsent(limit=limit)
    enqueued = 0
    sent = 0
    waiting_order = 0
    failed = 0
    details: List[Dict[str, Any]] = []

    for row in ready:
        uid = str(row.get("box_unique_id") or "").strip()
        seq = int(row.get("seq") or 0)
        state = int(row.get("state") or 0)
        if not uid or seq <= 0 or state not in (1, 2):
            continue

        status = repo.get_queue_status(uid, seq)
        qid = 0
        if status is None or status == STATUS_FAILED:
            part = enqueue_from_success_box_row(
                row, config_path=config_path, db_config=cfg
            )
            plc = part.get("plc") or {}
            if not plc.get("ok"):
                failed += 1
                details.append(
                    {
                        "box_unique_id": uid,
                        "seq": seq,
                        "action": "enqueue_failed",
                        "reason": plc.get("reason"),
                    }
                )
                continue
            qid = int(plc.get("queue_id") or 0)
            enqueued += 1
        elif status == STATUS_PENDING:
            qid = int(repo.get_id_by_uid_seq(uid, seq) or 0)
        else:
            # sent 已被 list 过滤；其它状态跳过
            continue

        if qid <= 0:
            failed += 1
            details.append(
                {
                    "box_unique_id": uid,
                    "seq": seq,
                    "action": "missing_queue_id",
                }
            )
            continue

        required = repo.next_required_seq(uid)
        if seq != required:
            waiting_order += 1
            details.append(
                {
                    "box_unique_id": uid,
                    "seq": seq,
                    "action": "waiting_order",
                    "required_seq": required,
                    "queue_id": qid,
                }
            )
            continue

        send_result = stub_send_plc_command(
            qid, config_path=config_path, db_config=cfg
        )
        if send_result.get("ok"):
            sent += 1
            details.append(
                {
                    "box_unique_id": uid,
                    "seq": seq,
                    "action": "sent",
                    "queue_id": qid,
                }
            )
        else:
            failed += 1
            details.append(
                {
                    "box_unique_id": uid,
                    "seq": seq,
                    "action": "send_failed",
                    "reason": send_result.get("reason"),
                    "queue_id": qid,
                }
            )

    return {
        "ok": True,
        "ready": len(ready),
        "processed": enqueued + sent + waiting_order + failed,
        "enqueued": enqueued,
        "sent": sent,
        "waiting_order": waiting_order,
        "failed": failed,
        "details": details,
    }


def get_plc_queue_repo(
    config_path: Optional[Path] = None,
    db_config: Optional[DatabaseConfig] = None,
) -> WcsPlcQueueRepository:
    cfg = db_config or load_database_config_from_yaml(config_path)
    return WcsPlcQueueRepository(cfg)


def clear_plc_queue_after_replan(
    *,
    config_path: Optional[Path] = None,
    db_config: Optional[DatabaseConfig] = None,
) -> int:
    """新一轮装箱结果写入后调用：清掉上一轮现场码放残留。"""
    n = get_plc_queue_repo(config_path=config_path, db_config=db_config).clear_all()
    print(f"[现场码垛] 新计算结果已入库，已清空旧码放队列 {n} 条")
    return n


def stub_send_plc_command(
    queue_id: int,
    *,
    config_path: Optional[Path] = None,
    db_config: Optional[DatabaseConfig] = None,
    note: str = "plc_send: auto/manual handoff marked sent",
) -> Dict[str, Any]:
    """下传已构造的码放数据并标记 sent（非 snap7 写硬件）。

    自动监听与界面应急补发共用。强制同一托盘按 seq 升序。
    """
    cfg = db_config or load_database_config_from_yaml(config_path)
    repo = WcsPlcQueueRepository(cfg)
    item = repo.get_by_id(queue_id)
    if item is None:
        return {"ok": False, "reason": "not_found", "queue_id": queue_id}
    if str(item.get("status") or "") != STATUS_PENDING:
        return {
            "ok": False,
            "reason": "not_pending",
            "queue_id": queue_id,
            "status": item.get("status"),
        }
    uid = str(item.get("box_unique_id") or "")
    seq = int(item.get("seq") or 0)
    required = repo.next_required_seq(uid)
    if seq != required:
        return {
            "ok": False,
            "reason": "out_of_order",
            "queue_id": queue_id,
            "box_unique_id": uid,
            "seq": seq,
            "required_seq": required,
            "message": f"必须按顺序下传：下一箱应为第 {required} 箱，不能先传第 {seq} 箱",
        }
    ok = repo.mark_sent_stub(queue_id, note=note)
    cmd = item.get("command") or {}
    print(
        f"[PLC下传] id={queue_id} box={item.get('box_unique_id')} "
        f"seq={item.get('seq')} state={item.get('state')} "
        f"dbw12={cmd.get('dbw12_state')} → {'sent' if ok else 'fail'}"
    )
    return {
        "ok": ok,
        "reason": "sent" if ok else "update_failed",
        "queue_id": queue_id,
        "command": cmd,
        "note": note,
        "seq": seq,
    }
