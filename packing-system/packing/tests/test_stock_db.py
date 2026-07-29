"""wcs_stock_box 全量替换 / wcs_stock_box_all 追加 单元测试（无真实 MySQL）。"""

from __future__ import annotations

import sys
import types
from contextlib import contextmanager
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    import pymysql  # noqa: F401
except ModuleNotFoundError:
    pymysql_module = types.ModuleType("pymysql")
    pymysql_cursors = types.ModuleType("pymysql.cursors")
    pymysql_cursors.DictCursor = object
    pymysql_module.cursors = pymysql_cursors
    pymysql_module.connect = None
    sys.modules["pymysql"] = pymysql_module
    sys.modules["pymysql.cursors"] = pymysql_cursors

from src.service.stock_db import (
    DatabaseConfig,
    WcsStockAllRepository,
    WcsStockRepository,
    prepare_stock_rows,
)


def _entry(pc, **kwargs):
    base = {
        "product_code": pc,
        "length": 350,
        "width": 530,
        "height": 240,
        "box_type": "YZX",
        "case_type": "MH423C",
        "target_num": 1,
        "order_id": "ORD1",
        "case_group": "0",
        "priority": 0,
    }
    base.update(kwargs)
    return base


def test_prepare_stock_rows_dedupes_and_skips_invalid():
    rows, skipped, samples = prepare_stock_rows([
        _entry(100),
        _entry(100),
        _entry("bad"),
        _entry(200),
    ])
    assert [r[5] for r in rows] == [100, 200]
    assert skipped == 1
    assert samples


def _patch_stock_repo(repo, store: dict):
    """store: product_code -> row tuple or None."""

    def existing(codes, table):
        return {int(c) for c in codes if int(c) in store}

    def all_codes(table):
        return set(store)

    class FakeCur:
        def __init__(self):
            self._last = None

        def execute(self, sql, args=None):
            text = str(sql).upper()
            if text.startswith("DELETE FROM"):
                store.clear()
            self._last = ("execute", sql, args)

        def executemany(self, sql, rows):
            for row in rows:
                store[int(row[5])] = row

        def fetchall(self):
            return [{"product_code": pc} for pc in store]

    @contextmanager
    def fake_cursor():
        yield None, FakeCur()

    repo._existing_product_codes = existing  # type: ignore[method-assign]
    repo._all_product_codes = all_codes  # type: ignore[method-assign]
    repo._cursor = fake_cursor  # type: ignore[method-assign]
    return store


def test_wcs_stock_box_unchanged_when_codes_match():
    repo = WcsStockRepository(DatabaseConfig())
    store = {100: None, 200: None}
    _patch_stock_repo(repo, store)

    stats = repo.sync_stock_entries([_entry(100), _entry(200)])

    assert stats.unchanged is True
    assert stats.changed is False
    assert stats.wake_packing is False
    assert set(store) == {100, 200}


def test_wcs_stock_box_replace_all_when_codes_differ():
    repo = WcsStockRepository(DatabaseConfig())
    store = {100: None, 200: None}
    _patch_stock_repo(repo, store)

    stats = repo.sync_stock_entries([_entry(100), _entry(300)])

    assert stats.changed is True
    assert stats.wake_packing is True
    assert stats.deleted == 2
    assert stats.inserted == 2
    assert set(store) == {100, 300}


def test_wcs_stock_box_empty_pull_does_not_wipe():
    repo = WcsStockRepository(DatabaseConfig())
    store = {100: None, 200: None}
    _patch_stock_repo(repo, store)

    stats = repo.sync_stock_entries([])

    assert stats.unchanged is True
    assert stats.changed is False
    assert set(store) == {100, 200}


def test_wcs_stock_box_can_explicitly_replace_with_empty_snapshot():
    repo = WcsStockRepository(DatabaseConfig())
    store = {100: None, 200: None}
    _patch_stock_repo(repo, store)

    stats = repo.sync_stock_entries([], allow_empty_replace=True)

    assert stats.changed is True
    assert stats.wake_packing is True
    assert stats.deleted == 2
    assert stats.inserted == 0
    assert store == {}


def test_wcs_stock_box_all_appends_without_delete():
    repo = WcsStockAllRepository(DatabaseConfig())
    store = {100: None, 200: None}
    _patch_stock_repo(repo, store)

    stats = repo.insert_new_stock_entries([_entry(100), _entry(300)])

    assert stats.inserted == 1
    assert stats.skipped_existing == 1
    assert stats.deleted == 0
    assert set(store) == {100, 200, 300}
