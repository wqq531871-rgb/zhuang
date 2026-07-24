# -*- coding: utf-8 -*-
"""旋转判断表 ``wcs_box_orientation``：目标姿态写入 / 接口4查询判转。"""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import pymysql
from pymysql.cursors import DictCursor

from src.adapter.wcs_adapter import WcsPlanResult, coerce_product_code
from src.service.success_box_db import (
    DatabaseConfig,
    load_database_config_from_yaml,
)

# rotation_state：与 packing-robot / wcs_success_box.state 一致
STATE_NO_ROTATE = 1
STATE_ROTATE_90 = 2


def compute_target_orientation_deg(
    suction_orientation: Optional[str] = None,
    cup_x_size: Optional[float] = None,
    cup_y_size: Optional[float] = None,
) -> int:
    """与 packing-robot ``target_orientation`` 相同规则 → 0 或 90。"""
    text = str(suction_orientation or "").strip().lower()
    if "800x_600" in text:
        return 90
    if "600x_800" in text:
        return 0
    cup_x = float(cup_x_size if cup_x_size is not None else 600.0)
    cup_y = float(cup_y_size if cup_y_size is not None else 800.0)
    return 90 if cup_x > cup_y else 0


def judge_rotation_state(
    camera_orientation_deg: int, target_orientation_deg: int
) -> int:
    """相机角 vs 目标角 → state 1/2。"""
    camera = int(camera_orientation_deg)
    target = int(target_orientation_deg)
    if camera not in (0, 90) or target not in (0, 90):
        raise ValueError("相机姿态和目标姿态必须为 0 或 90")
    return STATE_ROTATE_90 if camera != target else STATE_NO_ROTATE


def _product_code_str(value) -> Optional[str]:
    pc = coerce_product_code(value)
    if pc is None:
        return None
    return str(pc)


def build_orientation_rows(
    wcs_result: Optional[WcsPlanResult],
) -> List[Tuple]:
    """从执行 WCS map 构造插入行（仅 SUCCESS 盘）。

    元组：
    box_unique_id, seq, item_id, product_code,
    suction_orientation, suction_cup_x_size, suction_cup_y_size,
    target_orientation_deg
    """
    if not wcs_result:
        return []
    rows: List[Tuple] = []
    for unique_id, pallet in (wcs_result.plan_by_unique_id or {}).items():
        if str(pallet.get("mpm_status") or "").strip().upper() != "SUCCESS":
            continue
        uid = str(unique_id or "").strip()
        if not uid:
            continue
        for item in pallet.get("packed_items") or []:
            seq = int(item.get("seq") or 0)
            if seq <= 0:
                continue
            orientation = str(item.get("suction_orientation") or "").strip() or None
            cup_x = item.get("suction_cup_x_size")
            cup_y = item.get("suction_cup_y_size")
            cup_x_f = float(cup_x) if cup_x is not None else None
            cup_y_f = float(cup_y) if cup_y is not None else None
            target = compute_target_orientation_deg(orientation, cup_x_f, cup_y_f)
            item_id = str(item.get("id") or "").strip() or None
            rows.append(
                (
                    uid,
                    seq,
                    item_id,
                    _product_code_str(item.get("product_code")),
                    orientation,
                    cup_x_f,
                    cup_y_f,
                    target,
                )
            )
    return rows


class WcsBoxOrientationRepository:
    """``zhuangdb.wcs_box_orientation`` + 更新 ``wcs_success_box.state``。"""

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

    def insert_rows(self, rows: Sequence[Tuple]) -> int:
        """插入目标姿态行；已存在的 (box_unique_id, seq) 跳过。"""
        if not rows:
            return 0
        sql = (
            "INSERT IGNORE INTO wcs_box_orientation ("
            "box_unique_id, seq, item_id, product_code, "
            "suction_orientation, suction_cup_x_size, suction_cup_y_size, "
            "target_orientation_deg"
            ") VALUES ("
            "%s, %s, %s, %s, %s, %s, %s, %s"
            ")"
        )
        with self._cursor() as (_conn, cur):
            cur.executemany(sql, list(rows))
            return int(cur.rowcount or 0)

    def get_by_unique_seq(
        self, box_unique_id: str, seq: int
    ) -> Optional[Dict[str, Any]]:
        uid = str(box_unique_id or "").strip()
        seq_i = int(seq)
        if not uid or seq_i <= 0:
            return None
        with self._cursor() as (_conn, cur):
            cur.execute(
                "SELECT * FROM wcs_box_orientation "
                "WHERE box_unique_id = %s AND seq = %s "
                "LIMIT 1",
                (uid, seq_i),
            )
            row = cur.fetchone()
            return dict(row) if row else None

    def list_pallet_demo_rows(self, box_unique_id: str) -> List[Dict[str, Any]]:
        """现场三维演示：按 uid JOIN orientation + success_box，按 seq 升序。"""
        uid = str(box_unique_id or "").strip()
        if not uid:
            return []
        sql = (
            "SELECT "
            "o.box_unique_id AS box_unique_id, "
            "o.seq AS seq, "
            "o.item_id AS item_id, "
            "COALESCE(o.product_code, s.product_code) AS product_code, "
            "o.suction_orientation AS suction_orientation, "
            "o.suction_cup_x_size AS suction_cup_x_size, "
            "o.suction_cup_y_size AS suction_cup_y_size, "
            "o.target_orientation_deg AS target_orientation_deg, "
            "s.raw_length AS raw_length, "
            "s.raw_width AS raw_width, "
            "s.raw_height AS raw_height, "
            "s.pos_x AS pos_x, "
            "s.pos_y AS pos_y, "
            "s.pos_z AS pos_z, "
            "s.state AS state, "
            "s.pallet_id AS pallet_id, "
            "s.order_id AS order_id, "
            "s.case_type AS case_type, "
            "s.stack_height_before AS stack_height_before "
            "FROM wcs_box_orientation o "
            "INNER JOIN wcs_success_box s "
            "ON s.box_unique_id = o.box_unique_id AND s.seq = o.seq "
            "WHERE o.box_unique_id = %s "
            "ORDER BY o.seq ASC, o.id ASC"
        )
        with self._cursor() as (_conn, cur):
            cur.execute(sql, (uid,))
            return [dict(row) for row in (cur.fetchall() or [])]

    def update_success_box_state(
        self, box_unique_id: str, seq: int, state: int
    ) -> int:
        """按 (box_unique_id, seq) 更新 ``wcs_success_box.state``。

        返回匹配行数（即使新值与旧值相同也算成功；避免 MySQL
        ``rowcount=0`` 把幂等更新误判成失败）。
        """
        if int(state) not in (STATE_NO_ROTATE, STATE_ROTATE_90):
            raise ValueError(f"state 必须为 1 或 2，收到 {state}")
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
                "UPDATE wcs_success_box SET state = %s "
                "WHERE box_unique_id = %s AND seq = %s",
                (int(state), uid, seq_i),
            )
            return len(found)


def persist_box_orientations(
    wcs_result: Optional[WcsPlanResult],
    *,
    config_path: Optional[Path] = None,
    db_config: Optional[DatabaseConfig] = None,
) -> int:
    """写入目标姿态；失败只打日志，不打断主流程。"""
    rows = build_orientation_rows(wcs_result)
    if not rows:
        print("[WCS-DB] wcs_box_orientation：无达标箱子可写，跳过。")
        return 0
    try:
        cfg = db_config or load_database_config_from_yaml(config_path)
        repo = WcsBoxOrientationRepository(cfg)
        n = repo.insert_rows(rows)
        print(
            f"[WCS-DB] wcs_box_orientation：本批候选 {len(rows)} 行，"
            f"写入影响 {n}（含已存在跳过）。"
        )
        return n
    except Exception as exc:
        print(f"[WCS-DB] wcs_box_orientation 写入失败（不影响装箱结果）：{exc}")
        return 0


def process_box_arrive_rotation(
    box_unique_id: str,
    seq: int,
    camera_orientation_deg: Optional[int],
    *,
    config_path: Optional[Path] = None,
    db_config: Optional[DatabaseConfig] = None,
) -> Dict[str, Any]:
    """接口4：查目标角；有相机角则判转并写 ``wcs_success_box.state``。

    返回写入响应 ``data`` 的摘要字典。
    """
    cfg = db_config or load_database_config_from_yaml(config_path)
    repo = WcsBoxOrientationRepository(cfg)
    uid = str(box_unique_id or "").strip()
    seq_i = int(seq)
    orient = repo.get_by_unique_seq(uid, seq_i)
    if orient is None:
        return {
            "rotation": {
                "ok": False,
                "reason": "orientation_not_found",
                "box_unique_id": uid,
                "seq": seq_i,
            }
        }

    target = int(orient.get("target_orientation_deg") or 0)
    result: Dict[str, Any] = {
        "rotation": {
            "ok": True,
            "box_unique_id": uid,
            "seq": seq_i,
            "item_id": orient.get("item_id"),
            "product_code": orient.get("product_code"),
            "suction_orientation": orient.get("suction_orientation"),
            "target_orientation_deg": target,
            "camera_orientation_deg": None,
            "state": None,
            "state_updated": False,
            "success_box_rows": 0,
            "reason": None,
        }
    }
    rot = result["rotation"]

    if camera_orientation_deg is None:
        rot["reason"] = "waiting_camera"
        print(
            f"[接口4-旋转] 已查目标角 box={uid} seq={seq_i} "
            f"target={target}°，等待相机姿态"
        )
        return result

    camera = int(camera_orientation_deg)
    state = judge_rotation_state(camera, target)
    updated = repo.update_success_box_state(uid, seq_i, state)
    rot["camera_orientation_deg"] = camera
    rot["state"] = state
    rot["state_updated"] = updated > 0
    rot["success_box_rows"] = updated
    if updated <= 0:
        rot["reason"] = "success_box_row_missing"
        print(
            f"[接口4-旋转] 已算 state={state}，但 wcs_success_box "
            f"无匹配行 box={uid} seq={seq_i}"
        )
        return result

    rot["reason"] = "judged"
    print(
        f"[接口4-旋转] box={uid} seq={seq_i} "
        f"camera={camera}° target={target}° → state={state} "
        f"（已更新 {updated} 行）"
    )
    # 方案 C：判转完成后立刻构造 PLC 命令入队（不发送，等界面按钮）
    try:
        from src.service.plc_queue_db import enqueue_plc_after_rotation

        plc_part = enqueue_plc_after_rotation(
            box_unique_id=uid,
            seq=seq_i,
            state=state,
            target_orientation_deg=target,
            camera_orientation_deg=camera,
            item_id=str(orient.get("item_id") or "") or None,
            product_code=str(orient.get("product_code") or "") or None,
            config_path=config_path,
            db_config=cfg,
        )
        result.update(plc_part)
    except Exception as exc:
        print(f"[接口4-PLC] 构造入队失败：{exc}")
        result["plc"] = {
            "ok": False,
            "reason": "enqueue_exception",
            "error": str(exc),
        }
    return result


def get_orientation_repo(
    config_path: Optional[Path] = None,
    db_config: Optional[DatabaseConfig] = None,
) -> WcsBoxOrientationRepository:
    cfg = db_config or load_database_config_from_yaml(config_path)
    return WcsBoxOrientationRepository(cfg)


def load_pallet_demo_rows(
    box_unique_id: str,
    *,
    config_path: Optional[Path] = None,
    db_config: Optional[DatabaseConfig] = None,
) -> List[Dict[str, Any]]:
    """三维演示入口：按 box_unique_id 读 orientation JOIN success_box。"""
    return get_orientation_repo(
        config_path=config_path, db_config=db_config
    ).list_pallet_demo_rows(box_unique_id)
