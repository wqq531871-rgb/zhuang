"""Transactional publication of execution-order output bundles."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from uuid import uuid4

from .sequence_planner import ExecutionSequenceConfig, plan_execution_report
from .wcs_export import execution_report_to_plan_result


@dataclass(frozen=True)
class ExecutionBundlePaths:
    """Paths produced for one packing report."""

    execution: Path
    wcs_cases: Path
    wcs_map: Path


def publish_json_files(
    entries: List[Tuple[Path, object]],
    release_path: Optional[Path] = None,
) -> None:
    """Validate temp JSON files, then atomically publish the release file last."""

    if not entries:
        return
    targets = [Path(path) for path, _value in entries]
    resolved = [path.resolve() for path in targets]
    if len(set(resolved)) != len(resolved):
        raise ValueError("JSON output paths must be unique")
    release_resolved = Path(release_path).resolve() if release_path else None
    if release_resolved is not None and release_resolved not in resolved:
        raise ValueError("release_path must be one of the JSON output paths")

    prepared = []
    states = []
    try:
        for target, value in entries:
            target = Path(target)
            target.parent.mkdir(parents=True, exist_ok=True)
            temp = target.with_name(
                ".%s.tmp-%s" % (target.name, uuid4().hex)
            )
            prepared.append((temp, target))
            payload = json.dumps(value, ensure_ascii=False, indent=2) + "\n"
            temp.write_text(payload, encoding="utf-8")
            json.loads(temp.read_text(encoding="utf-8"))

        prepared.sort(
            key=lambda pair: (
                1
                if release_resolved is not None
                and pair[1].resolve() == release_resolved
                else 0
            )
        )
        for temp, target in prepared:
            backup = target.with_name(
                ".%s.backup-%s" % (target.name, uuid4().hex)
            )
            state = {
                "target": target,
                "backup": backup,
                "backed_up": False,
                "published": False,
            }
            states.append(state)
            if target.exists():
                target.replace(backup)
                state["backed_up"] = True
            temp.replace(target)
            state["published"] = True
    except Exception as publish_error:
        rollback_errors = []
        for state in reversed(states):
            target = state["target"]
            backup = state["backup"]
            try:
                if state["published"] and target.exists():
                    target.unlink()
                if state["backed_up"] and backup.exists():
                    if target.exists():
                        target.unlink()
                    backup.replace(target)
            except OSError as rollback_error:
                rollback_errors.append(str(rollback_error))
        if rollback_errors:
            raise OSError(
                "JSON publish failed and rollback was incomplete: %s"
                % "; ".join(rollback_errors)
            ) from publish_error
        raise
    else:
        for state in states:
            backup = state["backup"]
            if state["backed_up"] and backup.exists():
                backup.unlink()
    finally:
        for temp, _target in prepared:
            try:
                temp.unlink()
            except FileNotFoundError:
                pass


def publish_execution_bundle(
    report: Dict,
    original_plan_path: Path,
    config: ExecutionSequenceConfig,
) -> ExecutionBundlePaths:
    """Plan and publish execution, WCS cases, and the robot-side plan map."""

    original_plan_path = Path(original_plan_path)
    execution_path = original_plan_path.with_name(
        original_plan_path.stem + "_execution.json"
    )
    wcs_path = original_plan_path.with_name(
        original_plan_path.stem + "_execution_wcs.json"
    )
    map_path = wcs_path.with_name(wcs_path.stem + "_map.json")
    execution_report = plan_execution_report(report, config=config)
    wcs_result = execution_report_to_plan_result(execution_report)
    publish_json_files(
        [
            (execution_path, execution_report),
            (map_path, wcs_result.plan_by_unique_id),
            (wcs_path, wcs_result.cases),
        ],
        release_path=wcs_path,
    )
    return ExecutionBundlePaths(
        execution=execution_path,
        wcs_cases=wcs_path,
        wcs_map=map_path,
    )
