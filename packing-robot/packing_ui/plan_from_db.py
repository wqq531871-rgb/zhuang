"""从 MySQL（orientation JOIN success_box）加载三维演示托盘。"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping, Optional

import pymysql
from pymysql.cursors import DictCursor
import yaml

from .data import PackedItem, PalletPlan, _derive_suction_rect, _number


def default_packing_config_path() -> Path:
    # packing_ui/ → packing-robot/ → zhuang/
    zhuang = Path(__file__).resolve().parents[2]
    return zhuang / "packing-system" / "config" / "packing_config.yaml"


def load_mysql_settings(config_path: Path | None = None) -> dict[str, Any]:
    path = Path(config_path) if config_path else default_packing_config_path()
    if not path.is_file():
        raise FileNotFoundError(f"找不到数据库配置：{path}")
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    db = raw.get("database") if isinstance(raw, dict) else None
    if not isinstance(db, dict):
        raise ValueError(f"配置缺少 database 段：{path}")
    return {
        "host": str(db.get("host") or "localhost"),
        "port": int(db.get("port") or 3306),
        "user": str(db.get("user") or "root"),
        "password": str(db.get("password") or ""),
        "database": str(db.get("database") or "zhuangdb"),
        "charset": str(db.get("charset") or "utf8mb4"),
    }


_DEMO_SQL = (
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
    "s.camera_length AS camera_length, "
    "s.camera_width AS camera_width, "
    "s.camera_height AS camera_height, "
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


def fetch_pallet_demo_rows(
    box_unique_id: str, *, config_path: Path | None = None
) -> list[dict[str, Any]]:
    uid = str(box_unique_id or "").strip()
    if not uid:
        return []
    cfg = load_mysql_settings(config_path)
    conn = pymysql.connect(
        host=cfg["host"],
        port=cfg["port"],
        user=cfg["user"],
        password=cfg["password"],
        database=cfg["database"],
        charset=cfg["charset"],
        cursorclass=DictCursor,
        autocommit=True,
    )
    try:
        with conn.cursor() as cur:
            cur.execute(_DEMO_SQL, (uid,))
            return [dict(row) for row in (cur.fetchall() or [])]
    finally:
        conn.close()


def _row_to_item(row: Mapping[str, Any], index: int) -> PackedItem:
    x = _number(row.get("pos_x"))
    y = _number(row.get("pos_y"))
    z = _number(row.get("pos_z"))
    length = _number(row.get("raw_length"))
    width = _number(row.get("raw_width"))
    height = _number(row.get("raw_height"))
    cup_x = _number(row.get("suction_cup_x_size"), 600.0)
    cup_y = _number(row.get("suction_cup_y_size"), 800.0)
    state_raw = row.get("state")
    try:
        state_val = int(state_raw) if state_raw is not None and state_raw != "" else None
    except (TypeError, ValueError):
        state_val = None
    cam_l = row.get("camera_length")
    cam_w = row.get("camera_width")
    cam_h = row.get("camera_height")
    raw = {
        "id": row.get("item_id") or f"box-{int(row.get('seq') or index + 1)}",
        "seq": int(row.get("seq") or index + 1),
        "product_code": row.get("product_code"),
        "raw_length": length,
        "raw_width": width,
        "raw_height": height,
        "camera_length": float(cam_l) if cam_l is not None else None,
        "camera_width": float(cam_w) if cam_w is not None else None,
        "camera_height": float(cam_h) if cam_h is not None else None,
        "length": length,
        "width": width,
        "height": height,
        "position": {"x": x, "y": y, "z": z},
        "suction_orientation": row.get("suction_orientation") or "cup_600x_800y",
        "suction_cup_x_size": cup_x,
        "suction_cup_y_size": cup_y,
        "suction_box_corner": "x_min_y_min",
        "suction_cup_corner": "x_min_y_min",
        "target_orientation_deg": int(row.get("target_orientation_deg") or 0),
        "state": state_val,
    }
    derived = _derive_suction_rect(raw, x, y, length, width)
    item_id = str(raw["id"])
    return PackedItem(
        id=item_id,
        box_type=str(row.get("product_code") or "UNKNOWN"),
        length=length,
        width=width,
        height=height,
        raw_length=length,
        raw_width=width,
        raw_height=height,
        x=x,
        y=y,
        z=z,
        box_corner="x_min_y_min",
        cup_corner="x_min_y_min",
        suction_orientation=str(raw["suction_orientation"]),
        cup_x_size=cup_x,
        cup_y_size=cup_y,
        suction_x_min=derived[0],
        suction_x_max=derived[1],
        suction_y_min=derived[2],
        suction_y_max=derived[3],
        sequence=int(raw["seq"]),
        sequence_source="seq",
        original=raw,
    )


def build_plan_from_demo_rows(
    box_unique_id: str, rows: list[Mapping[str, Any]]
) -> PalletPlan:
    uid = str(box_unique_id or "").strip()
    if not rows:
        raise ValueError(f"库中没有托盘数据：box_unique_id={uid or '—'}")
    items = tuple(_row_to_item(row, i) for i, row in enumerate(rows))
    first = rows[0]
    return PalletPlan(
        source_key=uid,
        pallet_id=str(first.get("pallet_id") or uid),
        pallet_type=str(first.get("case_type") or "UNKNOWN"),
        sales_order_no=str(first.get("order_id") or ""),
        mpm_status="SUCCESS",
        sequence_status="FROM_DB",
        robot_verified=True,
        pallet_length=1440.0,
        pallet_width=2240.0,
        pallet_height=720.0,
        items=items,
        original={"box_unique_id": uid, "rows": list(rows)},
    )


def load_plan_from_db(
    box_unique_id: str, *, config_path: Path | None = None
) -> PalletPlan:
    uid = str(box_unique_id or "").strip()
    if not uid:
        raise ValueError("缺少 box_unique_id")
    rows = fetch_pallet_demo_rows(uid, config_path=config_path)
    return build_plan_from_demo_rows(uid, rows)
