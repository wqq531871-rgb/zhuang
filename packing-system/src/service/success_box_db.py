# -*- coding: utf-8 -*-
"""达标托盘箱子明细表 ``wcs_success_box`` 写入（MySQL / pymysql）。"""

from __future__ import annotations

import random
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Set, Tuple

import pymysql
from pymysql.cursors import DictCursor

from src.adapter.wcs_adapter import WcsPlanResult, coerce_product_code

# Excel / 缺码时生成的内部码区间（与正式 WCS 短码区分开，仅本表内部用）
_INTERNAL_PRODUCT_CODE_MIN = 900_000_000_000_000
_INTERNAL_PRODUCT_CODE_MAX = 999_999_999_999_999


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


def build_success_box_rows(
    execution_report: Optional[Dict],
    wcs_result: Optional[WcsPlanResult],
) -> List[Tuple]:
    """从执行方案 + WCS 映射构造插入行（仅 SUCCESS 盘）。

    返回元组顺序与 INSERT 列一致：
    box_unique_id, seq, raw_length, raw_width, raw_height,
    pos_x, pos_y, pos_z, stack_height_before, state,
    pallet_id, order_id, case_type, product_code
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
        for item in pallet.get("packed_items") or []:
            seq = int(item.get("seq") or 0)
            if seq <= 0:
                continue
            pos = item.get("position") or {}
            product_code = coerce_product_code(item.get("product_code"))
            # Excel / 缺码常见 0 或空；入库前由仓储补随机内部码（列多为 NOT NULL）
            if product_code is None or product_code == 0:
                product_code = None
            box_id = item.get("id")
            rows.append(
                (
                    uid,
                    seq,
                    _true_dim(item, "length"),
                    _true_dim(item, "width"),
                    _true_dim(item, "height"),
                    float(pos.get("x") or 0.0),
                    float(pos.get("y") or 0.0),
                    float(pos.get("z") or 0.0),
                    float(height_by_box_id.get(box_id, 0.0)),
                    1,  # state：默认不转
                    pallet_id,
                    order_id,
                    case_type,
                    product_code,
                )
            )
    return rows


def _new_internal_product_code(reserved: Set[int]) -> int:
    """生成不与 reserved 冲突的内部 product_code。"""
    for _ in range(64):
        code = random.randint(
            _INTERNAL_PRODUCT_CODE_MIN, _INTERNAL_PRODUCT_CODE_MAX
        )
        if code not in reserved:
            reserved.add(code)
            return code
    raise RuntimeError("无法生成可用的内部 product_code")


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
        """插入箱子行；已存在的 (box_unique_id, seq) 或 product_code 跳过。

        缺 product_code（Excel）时随机生成内部码后再写，保证 NOT NULL / UNIQUE。
        """
        if not rows:
            return 0

        filled = self._fill_missing_product_codes(list(rows))
        known_codes = sorted({int(r[13]) for r in filled})
        existing_pc = (
            self._existing_product_codes(known_codes) if known_codes else set()
        )

        prepared: List[Tuple] = []
        skipped_pc = 0
        for row in filled:
            pc = int(row[13])
            if pc in existing_pc:
                skipped_pc += 1
                continue
            prepared.append(row)

        if not prepared:
            if skipped_pc:
                print(
                    f"[WCS-DB] wcs_success_box：product_code 已存在，跳过 {skipped_pc} 行"
                )
            return 0

        sql = (
            "INSERT INTO wcs_success_box ("
            "box_unique_id, seq, raw_length, raw_width, raw_height, "
            "pos_x, pos_y, pos_z, stack_height_before, state, "
            "pallet_id, order_id, case_type, product_code"
            ") VALUES ("
            "%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s"
            ") ON DUPLICATE KEY UPDATE id = id"
        )
        with self._cursor() as (_conn, cur):
            cur.executemany(sql, prepared)
            inserted = int(cur.rowcount or 0)
        if skipped_pc:
            print(
                f"[WCS-DB] wcs_success_box：product_code 已存在，跳过 {skipped_pc} 行"
            )
        return max(inserted, 0)

    def _fill_missing_product_codes(self, rows: List[Tuple]) -> List[Tuple]:
        """为 None/0 的 product_code 分配随机内部码（本批唯一，且尽量避开库中已有）。"""
        reserved: Set[int] = set()
        for row in rows:
            pc = row[13]
            if pc is not None and int(pc) != 0:
                reserved.add(int(pc))

        missing_idx = [
            i for i, row in enumerate(rows) if row[13] is None or int(row[13]) == 0
        ]
        if not missing_idx:
            return rows

        # 先本地生成一批候选，再查库冲突并替换
        candidates = [
            _new_internal_product_code(reserved) for _ in missing_idx
        ]
        existing = self._existing_product_codes(candidates)
        for j, code in enumerate(candidates):
            if code not in existing:
                continue
            reserved.discard(code)
            # 重新抽到不在库、也不在 reserved 的码
            for _ in range(64):
                alt = _new_internal_product_code(reserved)
                if alt not in existing and alt not in self._existing_product_codes([alt]):
                    candidates[j] = alt
                    break
            else:
                raise RuntimeError("无法生成不与库冲突的内部 product_code")

        out = list(rows)
        for i, code in zip(missing_idx, candidates):
            row = out[i]
            out[i] = row[:13] + (code,) + row[14:]
        print(
            f"[WCS-DB] wcs_success_box：Excel/缺码已随机补 {len(missing_idx)} 个内部 product_code"
        )
        return out

    def _existing_product_codes(self, codes: Sequence[int]) -> set:
        if not codes:
            return set()
        found = set()
        chunk = 500
        with self._cursor() as (_conn, cur):
            for i in range(0, len(codes), chunk):
                part = list(codes[i : i + chunk])
                placeholders = ",".join(["%s"] * len(part))
                cur.execute(
                    f"SELECT product_code FROM wcs_success_box "
                    f"WHERE product_code IN ({placeholders})",
                    part,
                )
                for row in cur.fetchall() or []:
                    try:
                        found.add(int(row["product_code"]))
                    except (TypeError, ValueError, KeyError):
                        continue
        return found


def persist_success_boxes(
    execution_report: Optional[Dict],
    wcs_result: Optional[WcsPlanResult],
    *,
    config_path: Optional[Path] = None,
    db_config: Optional[DatabaseConfig] = None,
) -> int:
    """写入达标箱子；失败只打日志，不打断主流程。返回尝试插入相关行数。"""
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
            f"写入影响 {n}（含已存在跳过）。"
        )
        return n
    except Exception as exc:
        print(f"[WCS-DB] wcs_success_box 写入失败（不影响装箱结果）：{exc}")
        return 0


def persist_success_boxes_from_paths(
    execution_path: Path,
    wcs_map_path: Path,
    wcs_cases_path: Optional[Path] = None,
    *,
    config_path: Optional[Path] = None,
) -> int:
    """从已落盘的 execution / map 文件写入（cases 可选，仅校验）。"""
    import json

    from src.adapter.wcs_adapter import WcsPlanResult

    execution_path = Path(execution_path)
    wcs_map_path = Path(wcs_map_path)
    try:
        execution_report = json.loads(execution_path.read_text(encoding="utf-8"))
        plan_map = json.loads(wcs_map_path.read_text(encoding="utf-8"))
        cases = []
        if wcs_cases_path and Path(wcs_cases_path).exists():
            cases = json.loads(Path(wcs_cases_path).read_text(encoding="utf-8"))
        wcs_result = WcsPlanResult(
            cases=cases if isinstance(cases, list) else [],
            plan_by_unique_id=plan_map if isinstance(plan_map, dict) else {},
        )
    except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
        print(f"[WCS-DB] 读取执行文件失败，跳过 wcs_success_box：{exc}")
        return 0
    return persist_success_boxes(
        execution_report, wcs_result, config_path=config_path
    )
