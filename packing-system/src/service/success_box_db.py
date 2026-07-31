# -*- coding: utf-8 -*-
"""达标托盘箱子明细表 ``wcs_success_box``（MySQL / pymysql）。"""

from __future__ import annotations

import json
import random
from collections import Counter
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

import pymysql
from pymysql.cursors import DictCursor

from src.adapter.wcs_adapter import (
    WcsPlanResult,
    coerce_product_code,
    report_to_plan_result,
)
from src.utils.case_group import normalize_case_group

# Excel / 缺码时生成的内部码区间（与正式 WCS 短码区分开，仅本表内部用）
_INTERNAL_PRODUCT_CODE_MIN = 900_000_000_000_000
_INTERNAL_PRODUCT_CODE_MAX = 999_999_999_999_999
WCS_OUTPUT_LAYER_ID = 1

# is_send：2=未下传（默认），1=已下传
IS_SEND_UNSENT = "2"
IS_SEND_SENT = "1"

# 行元组：…, case_type, case_group, product_code, box_num
_PC_IDX = 14


@dataclass(frozen=True)
class DatabaseConfig:
    host: str = "localhost"
    port: int = 3306
    user: str = "root"
    password: str = ""
    database: str = "zhuangdb"
    charset: str = "utf8mb4"


def load_database_config(raw: Optional[Dict] = None) -> DatabaseConfig:
    raw = raw or {}
    return DatabaseConfig(
        host=str(raw.get("host") or "localhost"),
        port=int(raw.get("port") or 3306),
        user=str(raw.get("user") or "root"),
        password=str(raw.get("password") or ""),
        database=str(raw.get("database") or "zhuangdb"),
        charset=str(raw.get("charset") or "utf8mb4"),
    )


def load_database_config_from_yaml(config_path: Optional[Path] = None) -> DatabaseConfig:
    """从 packing_config.yaml 的 database 段读取连接信息。"""
    if config_path is None:
        config_path = (
            Path(__file__).resolve().parents[2] / "config" / "packing_config.yaml"
        )
    config_path = Path(config_path)
    try:
        from src.config import ConfigLoader

        raw = (ConfigLoader(config_path).config_data or {}).get("database") or {}
    except Exception:
        raw = {}
    return load_database_config(raw)


def _true_dim(item: Dict, axis: str) -> float:
    return float(
        item.get(
            f"raw_{axis}",
            item.get(f"original_{axis}", item.get(axis, 0)),
        )
        or 0
    )


def layout_state_from_raw_dims(raw_length: float, raw_width: float) -> int:
    """无相机垛型直判：与 packing-robot ``state_from_layout_dims`` 一致。

    ``raw_length`` 为 X、``raw_width`` 为 Y；Y>=X → 1（不转），否则 → 2（转90°）。
    非法尺寸时回退为 1，避免插入失败。
    """
    try:
        x_value = float(raw_length)
        y_value = float(raw_width)
    except (TypeError, ValueError):
        return 1
    if x_value <= 0 or y_value <= 0:
        return 1
    return 1 if y_value >= x_value else 2


def _product_code_to_db(value) -> Optional[str]:
    """入库用 varchar；缺码/0 → None（稍后补随机码）。"""
    pc = coerce_product_code(value)
    if pc is None or pc == 0:
        return None
    return str(pc)


def _product_code_for_wcs(value) -> int:
    """下传 JSON 里 product_code 尽量给 int。"""
    pc = coerce_product_code(value)
    if pc is None:
        text = str(value or "").strip()
        if text.isdigit():
            return int(text)
        return 0
    return int(pc)


def build_success_box_rows(
    execution_report: Optional[Dict],
    wcs_result: Optional[WcsPlanResult],
) -> List[Tuple]:
    """从执行方案 + WCS 映射构造插入行（仅 SUCCESS 盘）。

    元组：
    box_unique_id, seq, raw_length, raw_width, raw_height,
    pos_x, pos_y, pos_z, stack_height_before, state,
    pallet_id, order_id, case_type, case_group, product_code, box_num

    ``state``：按 ``raw_width``/``raw_length`` 垛型直判写入 1/2（无相机，插入即完成）。
    ``box_num``：该托盘箱子总数；同一 ``box_unique_id`` 下所有行相同。
    """
    if not execution_report or not wcs_result:
        return []

    height_by_box_id: Dict[object, float] = {}
    for pallet in execution_report.get("pallets") or []:
        if str(pallet.get("mpm_status") or "").strip().upper() != "SUCCESS":
            continue
        for item in pallet.get("packed_items") or []:
            box_id = item.get("id")
            if box_id is None:
                continue
            height_by_box_id[box_id] = float(
                item.get("stack_height_before") or 0.0
            )

    rows: List[Tuple] = []
    for unique_id, pallet in (wcs_result.plan_by_unique_id or {}).items():
        if str(pallet.get("mpm_status") or "").strip().upper() != "SUCCESS":
            continue
        uid = str(unique_id or "").strip()
        if not uid:
            continue
        pallet_id = str(pallet.get("pallet_id") or "").strip() or None
        order_id = str(pallet.get("sales_order_no") or "").strip() or None
        case_type = str(pallet.get("pallet_type") or "").strip() or None
        case_group = str(normalize_case_group(pallet.get("case_group")))
        items = [
            item
            for item in (pallet.get("packed_items") or [])
            if int(item.get("seq") or 0) > 0
        ]
        box_num = len(items)
        for item in items:
            seq = int(item.get("seq") or 0)
            pos = item.get("position") or {}
            product_code = _product_code_to_db(item.get("product_code"))
            box_id = item.get("id")
            raw_length = _true_dim(item, "length")
            raw_width = _true_dim(item, "width")
            rows.append(
                (
                    uid,
                    seq,
                    raw_length,
                    raw_width,
                    _true_dim(item, "height"),
                    float(pos.get("x") or 0.0),
                    float(pos.get("y") or 0.0),
                    float(pos.get("z") or 0.0),
                    float(height_by_box_id.get(box_id, 0.0)),
                    # 无相机联调：插入时即按垛型写 state（不经相机覆盖）
                    layout_state_from_raw_dims(raw_length, raw_width),
                    pallet_id,
                    order_id,
                    case_type,
                    case_group,
                    product_code,
                    box_num,
                )
            )
    return rows


def _new_internal_product_code(reserved: Set[str]) -> str:
    """生成不与 reserved 冲突的内部 product_code（字符串）。"""
    for _ in range(64):
        code = str(
            random.randint(_INTERNAL_PRODUCT_CODE_MIN, _INTERNAL_PRODUCT_CODE_MAX)
        )
        if code not in reserved:
            reserved.add(code)
            return code
    raise RuntimeError("无法生成可用的内部 product_code")


def build_wcs_case_from_box_rows(
    box_unique_id: str,
    box_rows: Sequence[Dict[str, Any]],
    *,
    box_index: int = 1,
) -> Dict[str, Any]:
    """把同一 box_unique_id 的表行拼成一个完整下传 case。"""
    rows = sorted(
        [r for r in box_rows if isinstance(r, dict)],
        key=lambda r: int(r.get("seq") or 0),
    )
    if not rows:
        raise ValueError(f"托盘 {box_unique_id} 没有箱子行")

    z_levels = sorted(
        {round(float(r.get("pos_z") or 0.0), 3) for r in rows}
    )
    layer_of = {z: idx + 1 for idx, z in enumerate(z_levels)}
    by_layer: Dict[int, List[Dict[str, Any]]] = {}
    total_height = 0.0
    for row in rows:
        z = round(float(row.get("pos_z") or 0.0), 3)
        height = float(row.get("raw_height") or 0.0)
        total_height = max(total_height, z + height)
        geometric_layer_id = layer_of[z]
        by_layer.setdefault(geometric_layer_id, []).append(
            {
                "length": float(row.get("raw_length") or 0.0),
                "width": float(row.get("raw_width") or 0.0),
                "height": height,
                "layer_id": WCS_OUTPUT_LAYER_ID,
                "seq": int(row.get("seq") or 0),
                "product_code": _product_code_for_wcs(row.get("product_code")),
            }
        )

    head = rows[0]
    case_group = head.get("case_group")
    if case_group is None or str(case_group).strip() == "":
        case_group = "0"
    else:
        case_group = str(normalize_case_group(case_group))

    return {
        "box_index": int(box_index),
        "box_unique_id": str(box_unique_id),
        "total_height": float(total_height),
        "order_id": str(head.get("order_id") or ""),
        "case_group": case_group,
        "case_type": str(head.get("case_type") or ""),
        "case_source": "DH",
        "layers": [
            {"cartons": by_layer[layer_id]} for layer_id in sorted(by_layer)
        ],
    }


class WcsSuccessBoxRepository:
    """``zhuangdb.wcs_success_box`` 仓储。"""

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
        """写入本批箱子行，并整盘替换包含相同 product_code 的旧结果。

        与本批 product_code 无交集的历史成功盘保留。查找旧盘、删除旧盘和
        插入本批数据在同一事务中完成；显式写 is_send=未下传，缺
        product_code 时随机补内部码。
        """
        if not rows:
            return 0

        filled = self._fill_missing_product_codes(list(rows))
        product_codes = [str(row[_PC_IDX]) for row in filled]
        duplicate_codes = sorted(
            code for code, count in Counter(product_codes).items() if count > 1
        )
        if duplicate_codes:
            samples = ", ".join(duplicate_codes[:5])
            raise ValueError(
                f"本批 product_code 重复，无法确定箱子唯一归属：{samples}"
            )
        known_codes = sorted(product_codes)
        prepared = [row + (IS_SEND_UNSENT,) for row in filled]

        sql = (
            "INSERT INTO wcs_success_box ("
            "box_unique_id, seq, raw_length, raw_width, raw_height, "
            "pos_x, pos_y, pos_z, stack_height_before, state, "
            "pallet_id, order_id, case_type, case_group, product_code, "
            "box_num, is_send"
            ") VALUES ("
            "%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, "
            "%s, %s"
            ")"
        )
        affected_uids: Set[str] = set()
        deleted = 0
        with self._cursor() as (_conn, cur):
            chunk = 500
            for i in range(0, len(known_codes), chunk):
                part = known_codes[i : i + chunk]
                placeholders = ",".join(["%s"] * len(part))
                cur.execute(
                    "SELECT box_unique_id FROM wcs_success_box "
                    f"WHERE product_code IN ({placeholders}) FOR UPDATE",
                    part,
                )
                for old_row in cur.fetchall() or []:
                    uid = str(old_row.get("box_unique_id") or "").strip()
                    if uid:
                        affected_uids.add(uid)

            old_uids = sorted(affected_uids)
            chunk = 200
            for i in range(0, len(old_uids), chunk):
                part = old_uids[i : i + chunk]
                placeholders = ",".join(["%s"] * len(part))
                cur.execute(
                    "DELETE FROM wcs_success_box "
                    f"WHERE box_unique_id IN ({placeholders})",
                    part,
                )
                deleted += int(cur.rowcount or 0)

            cur.executemany(sql, prepared)
            inserted = int(cur.rowcount or 0)
        if affected_uids:
            print(
                f"[WCS-DB] wcs_success_box：替换旧托盘 {len(affected_uids)} 个，"
                f"删除 {deleted} 行，写入 {max(inserted, 0)} 行"
            )
        return max(inserted, 0)

    def list_unsent_pallets(self) -> List[Dict[str, Any]]:
        """全库未下传托盘摘要（按 box_unique_id 聚合，新在前）。"""
        sql = (
            "SELECT box_unique_id, "
            "MAX(pallet_id) AS pallet_id, "
            "MAX(order_id) AS order_id, "
            "MAX(case_type) AS case_type, "
            "MAX(case_group) AS case_group, "
            "COUNT(*) AS box_count, "
            "MAX(created_at) AS created_at "
            "FROM wcs_success_box "
            "WHERE is_send = %s OR is_send IS NULL OR TRIM(IFNULL(is_send,'')) = '' "
            "GROUP BY box_unique_id "
            "ORDER BY MAX(created_at) DESC, box_unique_id"
        )
        with self._cursor() as (_conn, cur):
            cur.execute(sql, (IS_SEND_UNSENT,))
            rows = list(cur.fetchall() or [])
        out: List[Dict[str, Any]] = []
        for row in rows:
            out.append(
                {
                    "box_unique_id": str(row.get("box_unique_id") or ""),
                    "pallet_id": str(row.get("pallet_id") or "").strip(),
                    "order_id": str(row.get("order_id") or "").strip(),
                    "case_type": str(row.get("case_type") or "").strip(),
                    "case_group": str(row.get("case_group") or "0").strip() or "0",
                    "box_count": int(row.get("box_count") or 0),
                    "created_at": row.get("created_at"),
                }
            )
        return [r for r in out if r["box_unique_id"]]

    def count_unsent_pallets(self) -> int:
        return len(self.list_unsent_pallets())

    def fetch_boxes_by_unique_ids(
        self, box_unique_ids: Sequence[str]
    ) -> Dict[str, List[Dict[str, Any]]]:
        ids = [str(u).strip() for u in box_unique_ids if str(u or "").strip()]
        if not ids:
            return {}
        found: Dict[str, List[Dict[str, Any]]] = {uid: [] for uid in ids}
        chunk = 200
        with self._cursor() as (_conn, cur):
            for i in range(0, len(ids), chunk):
                part = ids[i : i + chunk]
                placeholders = ",".join(["%s"] * len(part))
                cur.execute(
                    "SELECT * FROM wcs_success_box "
                    f"WHERE box_unique_id IN ({placeholders}) "
                    "ORDER BY box_unique_id, seq",
                    part,
                )
                for row in cur.fetchall() or []:
                    uid = str(row.get("box_unique_id") or "")
                    if uid in found:
                        found[uid].append(dict(row))
        return found

    def build_wcs_cases_for_unique_ids(
        self, box_unique_ids: Sequence[str]
    ) -> List[Dict[str, Any]]:
        """按勾选顺序构造完整下传 case 数组（整盘全部箱子）。"""
        ids = [str(u).strip() for u in box_unique_ids if str(u or "").strip()]
        if not ids:
            raise ValueError("请至少选择一个达标托盘")
        by_uid = self.fetch_boxes_by_unique_ids(ids)
        cases: List[Dict[str, Any]] = []
        for box_index, uid in enumerate(ids, start=1):
            rows = by_uid.get(uid) or []
            if not rows:
                raise ValueError(f"库中找不到托盘 box_unique_id={uid}")
            # 仍允许未下传；若已混入已下传行也拼整盘（调用方应只选未下传）
            cases.append(
                build_wcs_case_from_box_rows(uid, rows, box_index=box_index)
            )
        return cases

    def mark_sent_by_unique_ids(self, box_unique_ids: Sequence[str]) -> int:
        """下传成功后：将这些盘全部箱子 is_send 置为已下传。"""
        ids = [str(u).strip() for u in box_unique_ids if str(u or "").strip()]
        if not ids:
            return 0
        updated = 0
        chunk = 200
        with self._cursor() as (_conn, cur):
            for i in range(0, len(ids), chunk):
                part = ids[i : i + chunk]
                placeholders = ",".join(["%s"] * len(part))
                cur.execute(
                    f"UPDATE wcs_success_box SET is_send = %s "
                    f"WHERE box_unique_id IN ({placeholders})",
                    [IS_SEND_SENT, *part],
                )
                updated += int(cur.rowcount or 0)
        return updated

    def _fill_missing_product_codes(self, rows: List[Tuple]) -> List[Tuple]:
        reserved: Set[str] = set()
        for row in rows:
            pc = row[_PC_IDX]
            if pc is not None and str(pc).strip() not in ("", "0"):
                reserved.add(str(pc))

        missing_idx = [
            i
            for i, row in enumerate(rows)
            if row[_PC_IDX] is None or str(row[_PC_IDX]).strip() in ("", "0")
        ]
        if not missing_idx:
            return rows

        candidates = [_new_internal_product_code(reserved) for _ in missing_idx]
        existing = self._existing_product_codes(candidates)
        for j, code in enumerate(candidates):
            if code not in existing:
                continue
            reserved.discard(code)
            for _ in range(64):
                alt = _new_internal_product_code(reserved)
                if alt not in existing:
                    candidates[j] = alt
                    break
            else:
                raise RuntimeError("无法生成不与库冲突的内部 product_code")

        out = list(rows)
        for i, code in zip(missing_idx, candidates):
            row = out[i]
            out[i] = row[:_PC_IDX] + (code,) + row[_PC_IDX + 1 :]
        print(
            f"[WCS-DB] wcs_success_box：Excel/缺码已随机补 {len(missing_idx)} 个内部 product_code"
        )
        return out

    def _existing_product_codes(self, codes: Sequence[str]) -> set:
        if not codes:
            return set()
        found = set()
        chunk = 500
        with self._cursor() as (_conn, cur):
            for i in range(0, len(codes), chunk):
                part = [str(c) for c in codes[i : i + chunk]]
                placeholders = ",".join(["%s"] * len(part))
                cur.execute(
                    f"SELECT product_code FROM wcs_success_box "
                    f"WHERE product_code IN ({placeholders})",
                    part,
                )
                for row in cur.fetchall() or []:
                    try:
                        found.add(str(row["product_code"]))
                    except (TypeError, KeyError):
                        continue
        return found


def persist_success_boxes(
    execution_report: Optional[Dict],
    wcs_result: Optional[WcsPlanResult],
    *,
    config_path: Optional[Path] = None,
    db_config: Optional[DatabaseConfig] = None,
) -> int:
    """写入达标箱子；失败只打日志，不打断主流程。"""
    rows = build_success_box_rows(execution_report, wcs_result)
    if not rows:
        print("[WCS-DB] wcs_success_box：无达标箱子可写，跳过。")
        return 0
    try:
        cfg = db_config or load_database_config_from_yaml(config_path)
        repo = WcsSuccessBoxRepository(cfg)
        n = repo.insert_rows(rows)
        print(
            f"[WCS-DB] wcs_success_box：本批候选 {len(rows)} 行，"
            f"本批写入 {n} 行。"
        )
        return n
    except Exception as exc:
        print(f"[WCS-DB] wcs_success_box 写入失败（不影响装箱结果）：{exc}")
        return 0


def persist_success_boxes_from_plan_file(
    plan_path: Path | str,
    *,
    config_path: Optional[Path] = None,
    db_config: Optional[DatabaseConfig] = None,
) -> int:
    """执行规划失败时：用原装箱 JSON（仅 SUCCESS 盘）写入库，供下传弹窗使用。"""
    path = Path(plan_path)
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, TypeError) as exc:
        print(f"[WCS-DB] 无法读取原装箱方案用于入库：{path}（{exc}）")
        return 0
    if not isinstance(report, dict):
        print(f"[WCS-DB] 原装箱方案根节点不是对象：{path}")
        return 0

    wcs_result = report_to_plan_result(report, include_failed=False)
    n = persist_success_boxes(
        report,
        wcs_result,
        config_path=config_path,
        db_config=db_config,
    )
    try:
        from src.service.box_orientation_db import persist_box_orientations

        persist_box_orientations(
            wcs_result,
            config_path=config_path,
            db_config=db_config,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"[WCS-DB] wcs_box_orientation 回退写入异常：{exc}")
    return n


def get_success_box_repo(
    config_path: Optional[Path] = None,
    db_config: Optional[DatabaseConfig] = None,
) -> WcsSuccessBoxRepository:
    cfg = db_config or load_database_config_from_yaml(config_path)
    return WcsSuccessBoxRepository(cfg)
