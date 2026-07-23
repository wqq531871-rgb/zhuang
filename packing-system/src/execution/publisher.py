"""Transactional publication of execution-order output bundles."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from uuid import uuid4

from .sequence_planner import ExecutionSequenceConfig, plan_execution_report
from .wcs_export import report_to_execution_plan_result


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


def _report_has_success(report: Dict) -> bool:
    return any(
        str(p.get("mpm_status") or "").strip().upper() == "SUCCESS"
        for p in (report.get("pallets") or [])
    )


def _resolve_bundle_dir(original_plan_path: Path, report: Dict) -> Path:
    """执行产物目录：优先 packing-workspace/output/{success|fail}。"""
    original = Path(original_plan_path).resolve()
    has_success = _report_has_success(report)
    bucket_name = "success" if has_success else "fail"

    parent = original.parent
    if parent.name in ("success", "fail"):
        return parent
    if parent.name == "output":
        bucket = parent / bucket_name
        bucket.mkdir(parents=True, exist_ok=True)
        return bucket

    for candidate in [original, *original.parents]:
        if candidate.name == "packing-workspace":
            bucket = candidate / "output" / bucket_name
            bucket.mkdir(parents=True, exist_ok=True)
            return bucket

    return parent


def publish_execution_bundle(
    report: Dict,
    original_plan_path: Path,
    config: ExecutionSequenceConfig,
    *,
    config_path: Optional[Path] = None,
) -> ExecutionBundlePaths:
    """Plan and publish execution, WCS cases, and the robot-side plan map."""

    original_plan_path = Path(original_plan_path)
    out_dir = _resolve_bundle_dir(original_plan_path, report)
    stem = original_plan_path.stem
    execution_path = out_dir / f"{stem}_execution.json"
    wcs_path = out_dir / f"{stem}_execution_wcs.json"
    map_path = wcs_path.with_name(wcs_path.stem + "_map.json")
    execution_report = plan_execution_report(report, config=config)
    wcs_result = report_to_execution_plan_result(report, config=config)
    publish_json_files(
        [
            (execution_path, execution_report),
            (map_path, wcs_result.plan_by_unique_id),
            (wcs_path, wcs_result.cases),
        ],
        release_path=wcs_path,
    )
    # 达标盘按箱写入 MySQL；失败不影响已落盘的执行文件
    try:
        from src.service.success_box_db import persist_success_boxes

        persist_success_boxes(
            execution_report,
            wcs_result,
            config_path=config_path,
        )
    except Exception as exc:  # noqa: BLE001 — 入库失败不回滚文件
        print("[WCS-DB] wcs_success_box 后置写入异常：%s" % exc)
    return ExecutionBundlePaths(
        execution=execution_path,
        wcs_cases=wcs_path,
        wcs_map=map_path,
    )
