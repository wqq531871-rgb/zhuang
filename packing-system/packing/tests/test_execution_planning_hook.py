import json
from pathlib import Path

from src.postprocess.execution_planning_hook import (
    plan_has_success_pallets,
    resolve_execution_bucket_dir,
    run_execution_planning_for_plan,
)


def _write_runner(root: Path, body: str) -> None:
    (root / "run_execution_planning.py").write_text(body, encoding="utf-8")


def _source_files(tmp_path: Path, *, mpm_status: str = "SUCCESS"):
    plan = tmp_path / "packing_plan_20260721_120000.json"
    config = tmp_path / "packing_config.yaml"
    plan.write_text(
        json.dumps(
            {
                "pallets": [
                    {"pallet_id": "P1", "mpm_status": mpm_status, "packed_items": []}
                ]
            }
        ),
        encoding="utf-8",
    )
    config.write_text("execution_sequence:\n  enabled: true\n", encoding="utf-8")
    return plan, config


_MOCK_RUNNER = """
import json
import sys
from pathlib import Path

source = Path(sys.argv[1])
output = Path(sys.argv[sys.argv.index('--output') + 1])
wcs = Path(sys.argv[sys.argv.index('--wcs-output') + 1])
if '--wcs-map-output' in sys.argv:
    wcs_map = Path(sys.argv[sys.argv.index('--wcs-map-output') + 1])
else:
    wcs_map = wcs.with_name(wcs.stem + '_map.json')
output.parent.mkdir(parents=True, exist_ok=True)
wcs.parent.mkdir(parents=True, exist_ok=True)
output.write_text(json.dumps({'pallets': []}), encoding='utf-8')
wcs.write_text(json.dumps([]), encoding='utf-8')
wcs_map.write_text(json.dumps({}), encoding='utf-8')
"""


def test_success_returns_all_execution_artifact_paths(tmp_path):
    plan, config = _source_files(tmp_path)
    _write_runner(tmp_path, _MOCK_RUNNER)
    out_root = tmp_path / "packing-workspace" / "output"

    outcome = run_execution_planning_for_plan(
        plan,
        config,
        project_root=tmp_path,
        output_dir=out_root,
        log=lambda _message: None,
    )

    assert outcome.succeeded is True
    assert outcome.report_path.parent == out_root / "success"
    assert outcome.report_path.name == plan.stem + "_execution.json"
    assert outcome.wcs_path == out_root / "success" / (plan.stem + "_execution_wcs.json")
    assert outcome.wcs_map_path == out_root / "success" / (
        plan.stem + "_execution_wcs_map.json"
    )


def test_no_success_pallets_go_to_fail_bucket(tmp_path):
    plan, config = _source_files(tmp_path, mpm_status="FAILED")
    _write_runner(tmp_path, _MOCK_RUNNER)
    out_root = tmp_path / "output"

    outcome = run_execution_planning_for_plan(
        plan,
        config,
        project_root=tmp_path,
        output_dir=out_root,
        log=lambda _message: None,
    )

    assert outcome.succeeded is True
    assert outcome.report_path.parent == out_root / "fail"


def test_failure_falls_back_to_original_report_and_no_wcs_artifacts(tmp_path):
    plan, config = _source_files(tmp_path)
    _write_runner(tmp_path, "raise SystemExit(1)\n")

    outcome = run_execution_planning_for_plan(
        plan,
        config,
        project_root=tmp_path,
        output_dir=tmp_path / "output",
        log=lambda _message: None,
    )

    assert outcome.succeeded is False
    assert outcome.report_path == plan.resolve()
    assert outcome.wcs_path is None
    assert outcome.wcs_map_path is None


def test_zero_exit_without_complete_artifacts_is_treated_as_failure(tmp_path):
    plan, config = _source_files(tmp_path)
    _write_runner(tmp_path, "pass\n")

    outcome = run_execution_planning_for_plan(
        plan,
        config,
        project_root=tmp_path,
        output_dir=tmp_path / "output",
        log=lambda _message: None,
    )

    assert outcome.succeeded is False
    assert outcome.report_path == plan.resolve()


def test_mismatched_wcs_case_and_map_ids_are_treated_as_failure(tmp_path):
    plan, config = _source_files(tmp_path)
    _write_runner(
        tmp_path,
        """
import json
import sys
from pathlib import Path

output = Path(sys.argv[sys.argv.index('--output') + 1])
wcs = Path(sys.argv[sys.argv.index('--wcs-output') + 1])
wcs_map = Path(sys.argv[sys.argv.index('--wcs-map-output') + 1])
output.parent.mkdir(parents=True, exist_ok=True)
output.write_text(json.dumps({'pallets': []}), encoding='utf-8')
wcs.write_text(json.dumps([{'box_unique_id': 'missing'}]), encoding='utf-8')
wcs_map.write_text(json.dumps({}), encoding='utf-8')
""",
    )

    outcome = run_execution_planning_for_plan(
        plan,
        config,
        project_root=tmp_path,
        output_dir=tmp_path / "output",
        log=lambda _message: None,
    )

    assert outcome.succeeded is False
    assert outcome.report_path == plan.resolve()


def test_plan_has_success_and_bucket_helpers(tmp_path):
    ok_dir = tmp_path / "ok"
    bad_dir = tmp_path / "bad"
    ok_dir.mkdir()
    bad_dir.mkdir()
    ok, _ = _source_files(ok_dir, mpm_status="SUCCESS")
    bad, _ = _source_files(bad_dir, mpm_status="FAILED")
    assert plan_has_success_pallets(ok) is True
    assert plan_has_success_pallets(bad) is False
    out = tmp_path / "output"
    assert resolve_execution_bucket_dir(
        ok, output_dir=out, has_success=True
    ) == out / "success"
    assert resolve_execution_bucket_dir(
        bad, output_dir=out, has_success=False
    ) == out / "fail"
