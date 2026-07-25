"""WCS 库存表 ``wcs_stock_box`` / ``wcs_stock_box_all`` 的读写（MySQL / pymysql）。

- ``wcs_stock_box``：当前立库快照（插入新码、跳过已有、删除本次没有的）+ 达标状态
- ``wcs_stock_box_all``：历史全量（只插入新码、跳过已有，不删除）无达标字段
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import pymysql
from pymysql.cursors import DictCursor

from src.adapter.wcs_adapter import coerce_product_code


@dataclass(frozen=True)
class DatabaseConfig:
    host: str = "localhost"
    port: int = 3306
    user: str = "root"
    password: str = ""
    database: str = "zhuangdb"
    charset: str = "utf8mb4"


@dataclass(frozen=True)
class StockSyncStats:
    """一次库存同步/追加的统计。"""

    inserted: int = 0
    skipped_existing: int = 0
    deleted: int = 0
    skipped_invalid: int = 0

    @property
    def wake_packing(self) -> bool:
        """有新插入才应唤醒装箱。"""
        return self.inserted > 0


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


def format_box_spec(length, width, height, box_type, weight=None) -> str:
    """存库格式：(length,width,height,box_type[,weight])。"""
    base = f"({float(length)},{float(width)},{float(height)},{box_type}"
    if weight is None:
        return base + ")"
    return base + f",{float(weight)})"


def parse_box_spec(spec: str) -> Dict:
    """解析 box_spec → length/width/height/box_type/weight。"""
    text = (spec or "").strip()
    if text.startswith("(") and text.endswith(")"):
        text = text[1:-1]
    parts = [p.strip() for p in text.split(",")]
    if len(parts) < 4:
        raise ValueError(f"box_spec 格式无效: {spec!r}")
    weight = float(parts[4]) if len(parts) >= 5 else 0.0
    return {
        "length": float(parts[0]),
        "width": float(parts[1]),
        "height": float(parts[2]),
        "box_type": str(parts[3]),
        "weight": weight,
    }


def prepare_stock_rows(
    entries: Sequence[Dict],
) -> Tuple[List[Tuple], int, List[str]]:
    """接口条目 → 入库行（不含 up_to_standard）。

    返回 ``(rows, skipped_invalid, invalid_samples)``。
    每行：(box_spec, case_type, target_num, order_id, case_group, product_code, priority)
    """
    prepared: List[Tuple] = []
    seen_in_batch: set = set()
    skipped_invalid = 0
    invalid_samples: List[str] = []
    for entry in entries:
        pc_raw = entry.get("product_code")
        pc = coerce_product_code(pc_raw)
        if pc is None:
            skipped_invalid += 1
            if len(invalid_samples) < 5:
                invalid_samples.append(repr(pc_raw))
            continue
        if pc in seen_in_batch:
            continue
        seen_in_batch.add(pc)
        prepared.append((
            format_box_spec(
                entry.get("length") or 0,
                entry.get("width") or 0,
                entry.get("height") or 0,
                entry.get("box_type") or "",
                entry.get("weight"),
            ),
            str(entry.get("case_type") or ""),
            int(entry.get("target_num") or 1),
            str(entry.get("order_id") or ""),
            str(
                entry.get("case_group")
                if entry.get("case_group") is not None
                else "0"
            ),
            pc,
            int(entry.get("priority") or 0),
        ))
    return prepared, skipped_invalid, invalid_samples


class _BaseStockRepository:
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

    def _existing_product_codes(self, codes: Sequence[int], table: str) -> set:
        if not codes:
            return set()
        uniq = list({int(c) for c in codes})
        found: set = set()
        chunk = 500
        with self._cursor() as (_conn, cur):
            for i in range(0, len(uniq), chunk):
                part = uniq[i:i + chunk]
                placeholders = ",".join(["%s"] * len(part))
                cur.execute(
                    f"SELECT product_code FROM {table} "
                    f"WHERE product_code IN ({placeholders})",
                    part,
                )
                for row in cur.fetchall():
                    found.add(int(row["product_code"]))
        return found

    def _all_product_codes(self, table: str) -> set:
        with self._cursor() as (_conn, cur):
            cur.execute(f"SELECT product_code FROM {table}")
            return {int(row["product_code"]) for row in cur.fetchall()}

    def _delete_product_codes(self, codes: Sequence[int], table: str) -> int:
        if not codes:
            return 0
        uniq = list({int(c) for c in codes})
        deleted = 0
        chunk = 500
        with self._cursor() as (_conn, cur):
            for i in range(0, len(uniq), chunk):
                part = uniq[i:i + chunk]
                placeholders = ",".join(["%s"] * len(part))
                cur.execute(
                    f"DELETE FROM {table} WHERE product_code IN ({placeholders})",
                    part,
                )
                deleted += int(cur.rowcount or 0)
        return deleted


class WcsStockRepository(_BaseStockRepository):
    """``zhuangdb.wcs_stock_box``：当前立库快照 + 达标状态。"""

    TABLE = "wcs_stock_box"

    def sync_stock_entries(self, entries: Sequence[Dict]) -> StockSyncStats:
        """同步为本次拉取快照：插入新码、跳过已有、删除本次没有的。

        已有行不更新字段（保留 ``up_to_standard``）。
        本次无任何合法 product_code 时不删除，避免空包洗库。
        """
        prepared, skipped_invalid, invalid_samples = prepare_stock_rows(entries)
        if skipped_invalid:
            print(
                f"[WCS-DB] {self.TABLE} 跳过无法解析的 product_code "
                f"{skipped_invalid} 条（样例：{', '.join(invalid_samples)}）"
            )

        if not prepared:
            return StockSyncStats(skipped_invalid=skipped_invalid)

        codes = [row[5] for row in prepared]
        code_set = set(codes)
        existing_in_batch = self._existing_product_codes(codes, self.TABLE)
        to_insert_rows = [
            row + ("0",) for row in prepared if row[5] not in existing_in_batch
        ]
        skipped_existing = len(prepared) - len(to_insert_rows)

        inserted = 0
        if to_insert_rows:
            sql = (
                f"INSERT IGNORE INTO {self.TABLE} "
                "(box_spec, case_type, target_num, order_id, case_group, "
                "product_code, priority, up_to_standard) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s)"
            )
            with self._cursor() as (_conn, cur):
                cur.executemany(sql, to_insert_rows)
            after = self._existing_product_codes(codes, self.TABLE)
            inserted = max(0, len(after) - len(existing_in_batch))

        if skipped_existing:
            print(
                f"[WCS-DB] {self.TABLE} product_code 已存在、跳过 "
                f"{skipped_existing} 条"
            )

        all_existing = self._all_product_codes(self.TABLE)
        to_delete = sorted(all_existing - code_set)
        deleted = self._delete_product_codes(to_delete, self.TABLE)
        if deleted:
            print(
                f"[WCS-DB] {self.TABLE} 删除本次立库未出现的 product_code "
                f"{deleted} 条"
            )

        return StockSyncStats(
            inserted=inserted,
            skipped_existing=skipped_existing,
            deleted=deleted,
            skipped_invalid=skipped_invalid,
        )

    def insert_new_stock_entries(self, entries: Sequence[Dict]) -> int:
        """兼容旧接口：同步后返回新插入行数。"""
        return self.sync_stock_entries(entries).inserted

    def fetch_unmet_rows(self) -> List[Dict]:
        """读取当前所有未达标行（up_to_standard='0'）。"""
        with self._cursor() as (_conn, cur):
            cur.execute(
                "SELECT id, box_spec, case_type, target_num, order_id, "
                "case_group, product_code, priority, up_to_standard "
                f"FROM {self.TABLE} WHERE up_to_standard = '0' "
                "ORDER BY id ASC"
            )
            return list(cur.fetchall())

    def mark_standard_by_product_codes(self, product_codes: Iterable) -> int:
        """将达标箱子的 up_to_standard 更新为 '1'。返回影响行数。"""
        codes = []
        for pc in product_codes:
            coerced = coerce_product_code(pc)
            if coerced is not None:
                codes.append(coerced)
        codes = list({c for c in codes})
        if not codes:
            return 0
        updated = 0
        chunk = 500
        with self._cursor() as (_conn, cur):
            for i in range(0, len(codes), chunk):
                part = codes[i:i + chunk]
                placeholders = ",".join(["%s"] * len(part))
                cur.execute(
                    f"UPDATE {self.TABLE} SET up_to_standard = '1' "
                    f"WHERE product_code IN ({placeholders}) "
                    f"AND up_to_standard = '0'",
                    part,
                )
                updated += int(cur.rowcount or 0)
        return updated

    def rows_to_stock_entries(self, rows: Sequence[Dict]) -> List[Dict]:
        """DB 行 → 接口库存条目结构（供 stock_to_boxes）。"""
        entries: List[Dict] = []
        for row in rows:
            try:
                dims = parse_box_spec(row.get("box_spec") or "")
            except ValueError:
                continue
            entries.append({
                "length": dims["length"],
                "width": dims["width"],
                "height": dims["height"],
                "weight": dims["weight"],
                "box_type": dims["box_type"],
                "case_type": row.get("case_type") or "",
                "target_num": int(row.get("target_num") or 1),
                "order_id": row.get("order_id") or "",
                "case_group": row.get("case_group") or "0",
                "product_code": row.get("product_code"),
                "priority": row.get("priority") or 0,
            })
        return entries


class WcsStockAllRepository(_BaseStockRepository):
    """``zhuangdb.wcs_stock_box_all``：历史立库全量（只增不删）。"""

    TABLE = "wcs_stock_box_all"

    def insert_new_stock_entries(self, entries: Sequence[Dict]) -> StockSyncStats:
        """按 product_code 去重追加；已存在跳过；不删除。"""
        prepared, skipped_invalid, invalid_samples = prepare_stock_rows(entries)
        if skipped_invalid:
            print(
                f"[WCS-DB] {self.TABLE} 跳过无法解析的 product_code "
                f"{skipped_invalid} 条（样例：{', '.join(invalid_samples)}）"
            )
        if not prepared:
            return StockSyncStats(skipped_invalid=skipped_invalid)

        codes = [row[5] for row in prepared]
        existing = self._existing_product_codes(codes, self.TABLE)
        to_insert = [row for row in prepared if row[5] not in existing]
        skipped_existing = len(prepared) - len(to_insert)
        if skipped_existing:
            print(
                f"[WCS-DB] {self.TABLE} product_code 已存在、跳过 "
                f"{skipped_existing} 条"
            )
        if not to_insert:
            return StockSyncStats(
                skipped_existing=skipped_existing,
                skipped_invalid=skipped_invalid,
            )

        sql = (
            f"INSERT IGNORE INTO {self.TABLE} "
            "(box_spec, case_type, target_num, order_id, case_group, "
            "product_code, priority) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s)"
        )
        with self._cursor() as (_conn, cur):
            cur.executemany(sql, to_insert)
        after = self._existing_product_codes(codes, self.TABLE)
        inserted = max(0, len(after) - len(existing))
        return StockSyncStats(
            inserted=inserted,
            skipped_existing=skipped_existing,
            skipped_invalid=skipped_invalid,
        )
