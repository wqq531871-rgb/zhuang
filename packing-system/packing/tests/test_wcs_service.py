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

from src.service.wcs_service import PackRunResult, WcsPackingService
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
        internal_path="/adaptor/api/wcs/internal",
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
        internal_path="/adaptor/api/wcs/internal",
        download_interval=10,
        input_dir=Path("."),
        bms_reference_file=Path("bms.xlsx"),
        output_dir=Path("."),
    )
    assert mock.effective_api_base_url == "https://mock.example"


def test_handle_fetch_error_stops_only_when_use_real_api():
    service = object.__new__(WcsPackingService)
    service._stop = _NeverStoppingEvent()
    service._db_insert_wake = Mock()
    service.stopped_by_api_failure = False
    service._ds = SimpleNamespace(use_real_api=True)

    assert service._handle_fetch_error(RuntimeError("boom"), "test") is True
    assert service.stopped_by_api_failure is True

    service2 = object.__new__(WcsPackingService)
    service2._stop = _NeverStoppingEvent()
    service2._db_insert_wake = Mock()
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
