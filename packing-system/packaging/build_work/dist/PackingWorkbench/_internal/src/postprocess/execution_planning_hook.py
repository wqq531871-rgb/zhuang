"""Run independent execution planning and select its complete output bundle."""

from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional, Tuple


@dataclass(frozen=True)
class ExecutionPlanningOutcome:
    """Effective artifacts after execution planning or original-plan fallback."""

    succeeded: bool
    report_path: Path
    wcs_path: Optional[Path] = None
    wcs_map_path: Optional[Path] = None

    def __bool__(self) -> bool:
        return self.succeeded


def packing_system_root_from_here() -> Path:
    return Path(__file__).resolve().parents[3]


def _execution_paths(plan_path: Path) -> Tuple[Path, Path, Path]:
    report = plan_path.with_name(plan_path.stem + "_execution.json")
    wcs = plan_path.with_name(plan_path.stem + "_execution_wcs.json")
    wcs_map = wcs.with_name(wcs.stem + "_map.json")
    return report, wcs, wcs_map


def _snapshot(path: Path) -> Optional[Tuple[int, int]]:
    try:
        stat = path.stat()
    except OSError:
        return None
    return stat.st_mtime_ns, stat.st_size


def _json_has_shape(path: Path, expected_type: type, key: Optional[str] = None) -> bool:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    if not isinstance(value, expected_type):
        return False
    return key is None or isinstance(value.get(key), list)


def _complete_fresh_bundle(
    paths: Tuple[Path, Path, Path],
    before: Tuple[Optional[Tuple[int, int]], ...],
) -> bool:
    if not all(_snapshot(path) != old for path, old in zip(paths, before)):
        return False
    report, wcs, wcs_map = paths
    valid_shapes = (
        _json_has_shape(report, dict, "pallets")
        and _json_has_shape(wcs, list)
        and _json_has_shape(wcs_map, dict)
    )
    if not valid_shapes:
        return False
    try:
        cases = json.loads(wcs.read_text(encoding="utf-8"))
        plan_map = json.loads(wcs_map.read_text(encoding="utf-8"))
        case_ids = {str(case["box_unique_id"]) for case in cases}
    except (OSError, json.JSONDecodeError, KeyError, TypeError):
        return False
    return case_ids == {str(unique_id) for unique_id in plan_map}


def run_execution_planning_for_plan(
    plan_path: Path,
    config_path: Path,
    *,
    project_root: Optional[Path] = None,
    log: Callable[[str], None] = print,
) -> ExecutionPlanningOutcome:
    """Run planning once; return original report when no complete bundle is made."""

    plan_path = Path(plan_path).resolve()
    config_path = Path(config_path).resolve()
    fallback = ExecutionPlanningOutcome(False, plan_path)
    root = (
        Path(project_root).resolve()
        if project_root
        else packing_system_root_from_here()
    )
    script = root / "run_execution_planning.py"
    if not script.exists():
        log(f"[执行规划] 找不到脚本：{script}")
        return fallback
    if not plan_path.exists():
        log(f"[执行规划] 找不到装箱报告：{plan_path}")
        return fallback
    if not config_path.exists():
        log(f"[执行规划] 找不到配置：{config_path}")
        return fallback

    execution_paths = _execution_paths(plan_path)
    before = tuple(_snapshot(path) for path in execution_paths)
    execution_report, wcs_output, wcs_map_output = execution_paths
    cmd = [
        sys.executable,
        str(script),
        str(plan_path),
        "--config",
        str(config_path),
        "--wcs-output",
        str(wcs_output),
    ]
    log(f"[执行规划] 开始：{' '.join(cmd)}")
    try:
        completed = subprocess.run(
            cmd,
            cwd=str(root),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
    except OSError as exc:
        log(f"[执行规划] 启动失败：{exc}")
        return fallback

    for stream in (completed.stdout, completed.stderr):
        for line in (stream or "").splitlines():
            text = line.rstrip()
            if text:
                log(text)

    if completed.returncode != 0:
        log(f"[执行规划] 失败，退出码：{completed.returncode}；使用原方案。")
        return fallback
    if not _complete_fresh_bundle(execution_paths, before):
        log("[执行规划] 未生成完整且有效的执行文件；使用原方案。")
        return fallback

    log(f"[执行规划] 完成；统一使用：{execution_report}")
    return ExecutionPlanningOutcome(
        True,
        execution_report,
        wcs_output,
        wcs_map_output,
    )
