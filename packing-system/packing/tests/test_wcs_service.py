import copy
import json
import sys
import types
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

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

from src.service.wcs_service import (
    PackRunResult,
    WcsPackingService,
    _split_positive_dimension_entries,
    select_wcs_plan_result,
)
import src.service.wcs_service as wcs_service_module
import run_wcs_service


class _NeverStoppingEvent:
    def __init__(self):
        self.wait_calls = []

    def is_set(self):
        return False

    def set(self):
        return None

    def wait(self, timeout=None):
        self.wait_calls.append(timeout)
        return False


def _stock_entry(product_code, **overrides):
    entry = {
        "length": 350,
        "width": 530,
        "height": 360,
        "target_num": 1,
        "box_type": "YZX507",
        "case_type": "MH423C",
        "product_code": product_code,
        "order_id": "ORDER-1",
    }
    entry.update(overrides)
    return entry


def test_split_positive_dimension_entries_rejects_every_invalid_dimension():
    entries = [
        _stock_entry(1),
        _stock_entry(2, length=0),
        _stock_entry(3, width=-1),
        _stock_entry(4, height=None),
        _stock_entry(5, length="not-a-number"),
        _stock_entry(6, width=float("inf")),
        _stock_entry(7, height=float("nan")),
    ]
    original = copy.deepcopy(entries)

    valid, invalid = _split_positive_dimension_entries(entries)

    assert [entry["product_code"] for entry in valid] == [1]
    assert [entry["product_code"] for entry in invalid] == [2, 3, 4, 5, 6, 7]
    assert entries == original


def test_fetch_once_filters_invalid_dimensions_before_both_stock_tables(
    tmp_path, monkeypatch, capsys
):
    valid = _stock_entry(100)
    invalid = _stock_entry(200, length=0, width=530, height=360)
    service = object.__new__(WcsPackingService)
    service._ds = SimpleNamespace(
        effective_api_base_url="https://wcs.example",
        stock_path="/stock",
        input_dir=tmp_path / "input",
        output_dir=tmp_path / "output",
    )
    service._repo = Mock()
    service._repo.sync_stock_entries.return_value = SimpleNamespace(
        unchanged=False,
        changed=True,
        deleted=2,
        inserted=1,
    )
    service._repo_all = Mock()
    service._repo_all.insert_new_stock_entries.return_value = SimpleNamespace(
        inserted=1,
        skipped_existing=0,
    )
    service._need_repack = Mock()
    service._ensure_dirs()
    monkeypatch.setattr(
        wcs_service_module,
        "fetch_stock_response",
        lambda *_args: {"data": [valid, invalid]},
    )

    result = service.fetch_once()

    assert result == 1
    service._repo.sync_stock_entries.assert_called_once_with([valid])
    service._repo_all.insert_new_stock_entries.assert_called_once_with([valid])
    service._need_repack.set.assert_called_once_with()
    raw_files = list(service.raw_dir.glob("*.json"))
    assert len(raw_files) == 1
    assert json.loads(raw_files[0].read_text(encoding="utf-8"))["data"] == [
        valid,
        invalid,
    ]
    output = capsys.readouterr().out
    assert "忽略 1 条" in output
    assert "product_code=200" in output
    assert "0×530×360" in output


def test_fetch_once_clears_current_snapshot_when_all_candidates_have_invalid_dimensions(
    tmp_path, monkeypatch
):
    invalid = _stock_entry(200, length=0)
    service = object.__new__(WcsPackingService)
    service._ds = SimpleNamespace(
        effective_api_base_url="https://wcs.example",
        stock_path="/stock",
        input_dir=tmp_path / "input",
        output_dir=tmp_path / "output",
    )
    service._repo = Mock()
    service._repo.sync_stock_entries.return_value = SimpleNamespace(
        unchanged=False,
        changed=True,
        deleted=1,
        inserted=0,
    )
    service._repo_all = Mock()
    service._repo_all.insert_new_stock_entries.return_value = SimpleNamespace(
        inserted=0,
        skipped_existing=0,
    )
    service._need_repack = Mock()
    service._ensure_dirs()
    monkeypatch.setattr(
        wcs_service_module,
        "fetch_stock_response",
        lambda *_args: {"data": [invalid]},
    )

    result = service.fetch_once()

    assert result == 1
    service._repo.sync_stock_entries.assert_called_once_with(
        [], allow_empty_replace=True
    )
    service._repo_all.insert_new_stock_entries.assert_called_once_with([])
    service._need_repack.set.assert_called_once_with()


def _make_service(fetch_results):
    service = object.__new__(WcsPackingService)
    service._stop = _NeverStoppingEvent()
    service._ds = SimpleNamespace(download_interval=37)
    service.fetch_once = Mock(side_effect=list(fetch_results))
    service._reload_reference_data = Mock()
    return service


def test_until_success_repeats_until_pack_result_has_success():
    service = _make_service([1, 1])
    service.pack_once = Mock(
        side_effect=[
            PackRunResult(executed=True, success_pallets=0),
            PackRunResult(
                executed=True,
                success_pallets=2,
                report_path=Path("success.json"),
            ),
        ]
    )

    assert service.run_until_success() is True
    assert service.pack_once.call_count == 2
    assert service._stop.wait_calls == [37]


def test_until_success_does_not_repack_when_fetch_has_no_new_data():
    service = _make_service([0, 0, 1])
    service.pack_once = Mock(
        return_value=PackRunResult(executed=True, success_pallets=1)
    )

    assert service.run_until_success() is True
    service.pack_once.assert_called_once_with()
    assert service._stop.wait_calls == [37, 37]


def test_until_success_stops_when_success_and_failed_pallets_coexist():
    service = _make_service([1])
    service.pack_once = Mock(
        return_value=PackRunResult(executed=True, success_pallets=1)
    )

    assert service.run_until_success() is True
    assert service._stop.wait_calls == []


def test_effective_url_switches_with_use_real_api():
    from src.service.wcs_service import DataSourceConfig

    real = DataSourceConfig(
        mode="api",
        use_real_api=True,
        api_base_url="http://10.205.46.191:8092",
        api_fallback_url="https://mock.example",
        stock_path="/adaptor/api/wcs/reqstockinfo",
        plan_path="/adaptor/api/wcs/sendpalletplanresult",
        download_interval=10,
        input_dir=Path("."),
        bms_reference_file=Path("bms.xlsx"),
        output_dir=Path("."),
    )
    assert real.effective_api_base_url == "http://10.205.46.191:8092"

    mock = DataSourceConfig(
        mode="api",
        use_real_api=False,
        api_base_url="http://10.205.46.191:8092",
        api_fallback_url="https://mock.example",
        stock_path="/adaptor/api/wcs/reqstockinfo",
        plan_path="/adaptor/api/wcs/sendpalletplanresult",
        download_interval=10,
        input_dir=Path("."),
        bms_reference_file=Path("bms.xlsx"),
        output_dir=Path("."),
    )
    assert mock.effective_api_base_url == "https://mock.example"


def test_handle_fetch_error_stops_only_when_use_real_api():
    service = object.__new__(WcsPackingService)
    service._stop = _NeverStoppingEvent()
    service._need_repack = Mock()
    service.stopped_by_api_failure = False
    service._ds = SimpleNamespace(use_real_api=True)

    assert service._handle_fetch_error(RuntimeError("boom"), "test") is True
    assert service.stopped_by_api_failure is True

    service2 = object.__new__(WcsPackingService)
    service2._stop = _NeverStoppingEvent()
    service2._need_repack = Mock()
    service2.stopped_by_api_failure = False
    service2._ds = SimpleNamespace(use_real_api=False)
    assert service2._handle_fetch_error(RuntimeError("boom"), "test") is False
    assert service2.stopped_by_api_failure is False


@pytest.mark.parametrize(
    ("mode", "method_name"),
    [
        ("continuous", "run_loop"),
        ("once", "run_once"),
        ("until-success", "run_until_success"),
    ],
)
def test_wcs_cli_routes_each_run_mode(monkeypatch, mode, method_name):
    service = Mock()
    service.stopped_by_api_failure = False
    service.run_once.return_value = True
    service.run_until_success.return_value = True
    service_factory = Mock(return_value=service)
    monkeypatch.setattr(run_wcs_service, "WcsPackingService", service_factory)

    assert run_wcs_service.main(["--run-mode", mode]) == 0

    getattr(service, method_name).assert_called_once_with()
    other_methods = {
        "run_loop",
        "run_once",
        "run_until_success",
    } - {method_name}
    for other in other_methods:
        getattr(service, other).assert_not_called()


def test_wcs_cli_defaults_to_continuous_and_rejects_unknown_mode():
    assert run_wcs_service._parse_cli([])[2] == "continuous"
    with pytest.raises(SystemExit, match="不支持的运行方式"):
        run_wcs_service._parse_cli(["--run-mode", "unknown"])


def test_wcs_uses_execution_cases_and_map_when_planning_succeeds(tmp_path):
    cases = [{"box_unique_id": "execution-id", "layers": []}]
    plan_map = {"execution-id": {"pallet_id": "P1", "packed_items": []}}
    wcs_path = tmp_path / "packing_execution_wcs.json"
    map_path = tmp_path / "packing_execution_wcs_map.json"
    wcs_path.write_text(json.dumps(cases), encoding="utf-8")
    map_path.write_text(json.dumps(plan_map), encoding="utf-8")
    outcome = SimpleNamespace(
        succeeded=True,
        wcs_path=wcs_path,
        wcs_map_path=map_path,
    )

    selected = select_wcs_plan_result({"pallets": []}, outcome)

    assert selected.cases == cases
    assert selected.plan_by_unique_id == plan_map


def test_wcs_falls_back_to_original_plan_when_execution_planning_fails():
    report = {"pallets": []}
    outcome = SimpleNamespace(
        succeeded=False,
        wcs_path=None,
        wcs_map_path=None,
    )

    selected = select_wcs_plan_result(report, outcome)

    assert selected.cases == []
    assert selected.plan_by_unique_id == {}


def test_wcs_rejects_execution_case_missing_from_plan_map(tmp_path):
    wcs_path = tmp_path / "packing_execution_wcs.json"
    map_path = tmp_path / "packing_execution_wcs_map.json"
    wcs_path.write_text(
        json.dumps([{"box_unique_id": "missing", "layers": []}]),
        encoding="utf-8",
    )
    map_path.write_text(json.dumps({}), encoding="utf-8")
    outcome = SimpleNamespace(
        succeeded=True,
        wcs_path=wcs_path,
        wcs_map_path=map_path,
    )

    with pytest.raises(ValueError, match="box_unique_id"):
        select_wcs_plan_result({"pallets": []}, outcome)
