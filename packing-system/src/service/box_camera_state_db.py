# -*- coding: utf-8 -*-
"""相机长宽高 → ``wcs_success_box.state``（0/1/2）。

对比同托盘同箱（uid+seq）的 camera_* 与 raw_*：
- 0：异型（高度不符或平面尺寸对不上）
- 1：同型、平面与计划一致（不旋转）
- 2：同型、平面对调（需转 90°）
"""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, List, Optional

import pymysql
from pymysql.cursors import DictCursor

from src.service.success_box_db import (
    DatabaseConfig,
    load_database_config_from_yaml,
)

STATE_MISMATCH = 0
STATE_NO_ROTATE = 1
STATE_ROTATE_90 = 2

DEFAULT_DIM_TOLERANCE_MM = 5.0


def judge_state_from_dims(
    camera_length: float,
    camera_width: float,
    camera_height: float,
    raw_length: float,
    raw_width: float,
    raw_height: float,
    tol_mm: float = DEFAULT_DIM_TOLERANCE_MM,
) -> int:
    """相机 LWH vs 计划 raw LWH → state 0/1/2。"""
    cam_l = float(camera_length)
    cam_w = float(camera_width)
    cam_h = float(camera_height)
    raw_l = float(raw_length)
    raw_w = float(raw_width)
    raw_h = float(raw_height)
    tol = max(0.0, float(tol_mm))

    if any(v <= 0 for v in (cam_l, cam_w, cam_h, raw_l, raw_w, raw_h)):
        return STATE_MISMATCH

    if abs(cam_h - raw_h) > tol:
        return STATE_MISMATCH

    aligned = abs(cam_l - raw_l) <= tol and abs(cam_w - raw_w) <= tol
    swapped = abs(cam_l - raw_w) <= tol and abs(cam_w - raw_l) <= tol
    if aligned:
        return STATE_NO_ROTATE
    if swapped:
        return STATE_ROTATE_90
    return STATE_MISMATCH


def camera_dims_complete(
    camera_length: Any, camera_width: Any, camera_height: Any
) -> bool:
    try:
        vals = (
            float(camera_length),
            float(camera_width),
            float(camera_height),
        )
    except (TypeError, ValueError):
        return False
    return all(v > 0 for v in vals)


class WcsCameraStateRepository:
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

    def fetch_row(self, box_unique_id: str, seq: int) -> Optional[Dict[str, Any]]:
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

    def update_camera_dims_only(
        self,
        box_unique_id: str,
        seq: int,
        *,
        camera_length: float,
        camera_width: float,
        camera_height: float,
    ) -> int:
        """接法 B：相机模块只写尺寸，不写 state。"""
        uid = str(box_unique_id or "").strip()
        seq_i = int(seq)
        with self._cursor() as (_conn, cur):
            cur.execute(
                "SELECT id FROM wcs_success_box "
                "WHERE box_unique_id = %s AND seq = %s",
                (uid, seq_i),
            )
            found = list(cur.fetchall() or [])
            if not found:
                return 0
            cur.execute(
                "UPDATE wcs_success_box SET "
                "camera_length = %s, camera_width = %s, camera_height = %s "
                "WHERE box_unique_id = %s AND seq = %s",
                (
                    float(camera_length),
                    float(camera_width),
                    float(camera_height),
                    uid,
                    seq_i,
                ),
            )
            return len(found)

    def list_camera_ready_unjudged(self, limit: int = 50) -> List[Dict[str, Any]]:
        """camera_* 已齐、state 仍为空的行（按 uid, seq）。"""
        lim = max(1, min(int(limit), 200))
        sql = (
            "SELECT * FROM wcs_success_box "
            "WHERE camera_length IS NOT NULL AND camera_length > 0 "
            "  AND camera_width IS NOT NULL AND camera_width > 0 "
            "  AND camera_height IS NOT NULL AND camera_height > 0 "
            "  AND state IS NULL "
            "ORDER BY box_unique_id ASC, seq ASC "
            "LIMIT %s"
        )
        with self._cursor() as (_conn, cur):
            cur.execute(sql, (lim,))
            return [dict(row) for row in (cur.fetchall() or [])]

    def update_camera_dims_and_state(
        self,
        box_unique_id: str,
        seq: int,
        *,
        camera_length: float,
        camera_width: float,
        camera_height: float,
        state: int,
    ) -> int:
        """写入 camera_* 与 state；返回匹配行数（幂等更新也算成功）。"""
        if int(state) not in (STATE_MISMATCH, STATE_NO_ROTATE, STATE_ROTATE_90):
            raise ValueError(f"state 必须为 0/1/2，收到 {state}")
        uid = str(box_unique_id or "").strip()
        seq_i = int(seq)
        with self._cursor() as (_conn, cur):
            cur.execute(
                "SELECT id FROM wcs_success_box "
                "WHERE box_unique_id = %s AND seq = %s",
                (uid, seq_i),
            )
            found = list(cur.fetchall() or [])
            if not found:
                return 0
            cur.execute(
                "UPDATE wcs_success_box SET "
                "camera_length = %s, camera_width = %s, camera_height = %s, "
                "state = %s "
                "WHERE box_unique_id = %s AND seq = %s",
                (
                    float(camera_length),
                    float(camera_width),
                    float(camera_height),
                    int(state),
                    uid,
                    seq_i,
                ),
            )
            return len(found)


def apply_camera_dims_and_judge(
    box_unique_id: str,
    seq: int,
    camera_length: float,
    camera_width: float,
    camera_height: float,
    *,
    tol_mm: float = DEFAULT_DIM_TOLERANCE_MM,
    config_path: Optional[Path] = None,
    db_config: Optional[DatabaseConfig] = None,
) -> Dict[str, Any]:
    """写 camera LWH，对比 raw_* 写 state；供相机模块 / 联调调用。"""
    cfg = db_config or load_database_config_from_yaml(config_path)
    repo = WcsCameraStateRepository(cfg)
    uid = str(box_unique_id or "").strip()
    seq_i = int(seq)

    if not camera_dims_complete(camera_length, camera_width, camera_height):
        return {
            "ok": False,
            "reason": "camera_dims_incomplete",
            "box_unique_id": uid,
            "seq": seq_i,
        }

    row = repo.fetch_row(uid, seq_i)
    if row is None:
        return {
            "ok": False,
            "reason": "success_box_row_missing",
            "box_unique_id": uid,
            "seq": seq_i,
        }

    raw_l = float(row.get("raw_length") or 0)
    raw_w = float(row.get("raw_width") or 0)
    raw_h = float(row.get("raw_height") or 0)
    cam_l = float(camera_length)
    cam_w = float(camera_width)
    cam_h = float(camera_height)
    state = judge_state_from_dims(
        cam_l, cam_w, cam_h, raw_l, raw_w, raw_h, tol_mm=tol_mm
    )
    updated = repo.update_camera_dims_and_state(
        uid,
        seq_i,
        camera_length=cam_l,
        camera_width=cam_w,
        camera_height=cam_h,
        state=state,
    )
    if updated <= 0:
        return {
            "ok": False,
            "reason": "update_failed",
            "box_unique_id": uid,
            "seq": seq_i,
            "state": state,
        }

    label = {0: "异型", 1: "同型不转", 2: "同型转90°"}.get(state, "?")
    print(
        f"[相机判态] box={uid} seq={seq_i} "
        f"cam={cam_l:g}×{cam_w:g}×{cam_h:g} "
        f"raw={raw_l:g}×{raw_w:g}×{raw_h:g} → state={state}（{label}）"
    )
    result = {
        "ok": True,
        "reason": "judged",
        "box_unique_id": uid,
        "seq": seq_i,
        "state": state,
        "state_label": label,
        "camera_length": cam_l,
        "camera_width": cam_w,
        "camera_height": cam_h,
        "raw_length": raw_l,
        "raw_width": raw_w,
        "raw_height": raw_h,
        "tol_mm": float(tol_mm),
        "rows_updated": updated,
        "product_code": row.get("product_code"),
        "order_id": row.get("order_id"),
        "item_id": None,
    }
    # state=0：立刻通知三维显示（不播成功装载）；1/2 由 PLC 自动下传后再 play
    if state == STATE_MISMATCH:
        try:
            from src.service.live_stack_bridge import write_live_play_box

            result["ui"] = write_live_play_box(
                box_unique_id=uid,
                seq=seq_i,
                state=state,
                order_id=str(row.get("order_id") or ""),
                product_code=str(row.get("product_code") or ""),
                camera_length=cam_l,
                camera_width=cam_w,
                camera_height=cam_h,
                auto_play=False,
            )
        except Exception as exc:
            print(f"[相机判态] 写三维指令失败：{exc}")
            result["ui_error"] = str(exc)
    return result


def write_camera_dims_only(
    box_unique_id: str,
    seq: int,
    camera_length: float,
    camera_width: float,
    camera_height: float,
    *,
    config_path: Optional[Path] = None,
    db_config: Optional[DatabaseConfig] = None,
) -> Dict[str, Any]:
    """接法 B：只写 camera_*，留给判态监听写 state。"""
    cfg = db_config or load_database_config_from_yaml(config_path)
    repo = WcsCameraStateRepository(cfg)
    uid = str(box_unique_id or "").strip()
    seq_i = int(seq)
    if not camera_dims_complete(camera_length, camera_width, camera_height):
        return {
            "ok": False,
            "reason": "camera_dims_incomplete",
            "box_unique_id": uid,
            "seq": seq_i,
        }
    n = repo.update_camera_dims_only(
        uid,
        seq_i,
        camera_length=float(camera_length),
        camera_width=float(camera_width),
        camera_height=float(camera_height),
    )
    if n <= 0:
        return {
            "ok": False,
            "reason": "success_box_row_missing",
            "box_unique_id": uid,
            "seq": seq_i,
        }
    print(
        f"[相机写库] box={uid} seq={seq_i} "
        f"cam={float(camera_length):g}×{float(camera_width):g}×{float(camera_height):g} "
        f"（待判态监听写 state）"
    )
    return {
        "ok": True,
        "reason": "camera_written",
        "box_unique_id": uid,
        "seq": seq_i,
        "camera_length": float(camera_length),
        "camera_width": float(camera_width),
        "camera_height": float(camera_height),
        "rows_updated": n,
    }


def auto_judge_pending_camera_rows(
    *,
    config_path: Optional[Path] = None,
    db_config: Optional[DatabaseConfig] = None,
    tol_mm: float = DEFAULT_DIM_TOLERANCE_MM,
    limit: int = 50,
) -> Dict[str, Any]:
    """接法 B 监听：camera_* 已齐且 state 为空 → 自动判写 state。"""
    cfg = db_config or load_database_config_from_yaml(config_path)
    repo = WcsCameraStateRepository(cfg)
    pending = repo.list_camera_ready_unjudged(limit=limit)
    judged = 0
    failed = 0
    details: List[Dict[str, Any]] = []
    for row in pending:
        uid = str(row.get("box_unique_id") or "")
        seq = int(row.get("seq") or 0)
        part = apply_camera_dims_and_judge(
            uid,
            seq,
            float(row.get("camera_length") or 0),
            float(row.get("camera_width") or 0),
            float(row.get("camera_height") or 0),
            tol_mm=tol_mm,
            config_path=config_path,
            db_config=cfg,
        )
        if part.get("ok"):
            judged += 1
            details.append(
                {
                    "box_unique_id": uid,
                    "seq": seq,
                    "state": part.get("state"),
                    "action": "judged",
                }
            )
        else:
            failed += 1
            details.append(
                {
                    "box_unique_id": uid,
                    "seq": seq,
                    "action": "judge_failed",
                    "reason": part.get("reason"),
                }
            )
    return {
        "ok": True,
        "pending": len(pending),
        "judged": judged,
        "failed": failed,
        "details": details,
    }
