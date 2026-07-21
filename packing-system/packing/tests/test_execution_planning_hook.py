import json
from pathlib import Path

from src.postprocess.execution_planning_hook import (
    run_execution_planning_for_plan,
)


def _write_runner(root: Path, body: str) -> None:
    (root / "run_execution_planning.py").write_text(body, encoding="utf-8")


def _source_files(tmp_path: Path):
    plan = tmp_path / "packing_plan_20260721_120000.json"
    config = tmp_path / "packing_config.yaml"
    plan.write_text(json.dumps({"pallets": []}), encoding="utf-8")
    config.write_text("execution_sequence:\n  enabled: true\n", encoding="utf-8")
    return plan, config


def test_success_returns_all_execution_artifact_paths(tmp_path):
    plan, config = _source_files(tmp_path)
    _write_runner(
        tmp_path,
        """
import json
import sys
from pathlib import Path

source = Path(sys.argv[1])
wcs = Path(sys.argv[sys.argv.index('--wcs-output') + 1])
execution = source.with_name(source.stem + '_execution.json')
wcs_map = wcs.with_name(wcs.stem + '_map.json')
execution.write_text(json.dumps({'pallets': []}), encoding='utf-8')
wcs.write_text(json.dumps([]), encoding='utf-8')
wcs_map.write_text(json.dumps({}), encoding='utf-8')
""",
    )

    outcome = run_execution_planning_for_plan(
        plan,
        config,
        project_root=tmp_path,
        log=lambda _message: None,
    )

    assert outcome.succeeded is True
    assert outcome.report_path == plan.with_name(plan.stem + "_execution.json")
    assert outcome.wcs_path == plan.with_name(plan.stem + "_execution_wcs.json")
    assert outcome.wcs_map_path == plan.with_name(
        plan.stem + "_execution_wcs_map.json"
    )


def test_failure_falls_back_to_original_report_and_no_wcs_artifacts(tmp_path):
    plan, config = _source_files(tmp_path)
    _write_runner(tmp_path, "raise SystemExit(1)\n")

    outcome = run_execution_planning_for_plan(
        plan,
        config,
        project_root=tmp_path,
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

source = Path(sys.argv[1])
wcs = Path(sys.argv[sys.argv.index('--wcs-output') + 1])
execution = source.with_name(source.stem + '_execution.json')
wcs_map = wcs.with_name(wcs.stem + '_map.json')
execution.write_text(json.dumps({'pallets': []}), encoding='utf-8')
wcs.write_text(json.dumps([{'box_unique_id': 'missing'}]), encoding='utf-8')
wcs_map.write_text(json.dumps({}), encoding='utf-8')
""",
    )

    outcome = run_execution_planning_for_plan(
        plan,
        config,
        project_root=tmp_path,
        log=lambda _message: None,
    )

    assert outcome.succeeded is False
    assert outcome.report_path == plan.resolve()
