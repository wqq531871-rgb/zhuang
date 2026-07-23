"""Run independent execution planning and select its complete output bundle."""

from __future__ import annotations

import json
import os
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


def default_workspace_output_dir(project_root: Optional[Path] = None) -> Path:
    """``packing-workspace/output``（可用 ``PACKING_WORKSPACE`` 覆盖工作区根）。"""
    env = os.environ.get("PACKING_WORKSPACE", "").strip()
    if env:
        return Path(env).expanduser().resolve() / "output"
    root = Path(project_root).resolve() if project_root else packing_system_root_from_here()
    # packing-system → 同级 packing-workspace/output
    return (root.parent / "packing-workspace" / "output").resolve()


def plan_has_success_pallets(plan_path: Path) -> bool:
    """源装箱报告是否含达标盘（决定 success / fail 目录）。"""
    try:
        report = json.loads(Path(plan_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return False
    for pallet in report.get("pallets") or []:
        if str(pallet.get("mpm_status") or "").strip().upper() == "SUCCESS":
            return True
    return False


def resolve_execution_bucket_dir(
    plan_path: Path,
    *,
    output_dir: Optional[Path] = None,
    project_root: Optional[Path] = None,
    has_success: Optional[bool] = None,
) -> Path:
    """执行产物目录：有达标盘 → output/success，否则 → output/fail。"""
    if has_success is None:
        has_success = plan_has_success_pallets(plan_path)
    out_root = (
        Path(output_dir).resolve()
        if output_dir is not None
        else default_workspace_output_dir(project_root)
    )
    bucket = out_root / ("success" if has_success else "fail")
    bucket.mkdir(parents=True, exist_ok=True)
    return bucket


def _execution_paths_in_dir(plan_path: Path, bucket_dir: Path) -> Tuple[Path, Path, Path]:
    stem = Path(plan_path).stem
    report = bucket_dir / f"{stem}_execution.json"
    wcs = bucket_dir / f"{stem}_execution_wcs.json"
    wcs_map = wcs.with_name(wcs.stem + "_map.json")
    return report, wcs, wcs_map


def _execution_paths(plan_path: Path) -> Tuple[Path, Path, Path]:
    """同目录旁路命名（兼容旧测试 / 未指定 output 时的默认）。"""
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
    output_dir: Optional[Path] = None,
    log: Callable[[str], None] = print,
) -> ExecutionPlanningOutcome:
    """Run planning once; write bundle under output/success|fail; fallback to source."""

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

    has_success = plan_has_success_pallets(plan_path)
    bucket = resolve_execution_bucket_dir(
        plan_path,
        output_dir=output_dir,
        project_root=root,
        has_success=has_success,
    )
    execution_paths = _execution_paths_in_dir(plan_path, bucket)
    before = tuple(_snapshot(path) for path in execution_paths)
    execution_report, wcs_output, wcs_map_output = execution_paths
    bucket_label = "success" if has_success else "fail"
    log(f"[执行规划] 产物目录：{bucket}（{bucket_label}）")

    cmd = [
        sys.executable,
        str(script),
        str(plan_path),
        "--config",
        str(config_path),
        "--output",
        str(execution_report),
        "--wcs-output",
        str(wcs_output),
        "--wcs-map-output",
        str(wcs_map_output),
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
        _persist_original_plan_to_db(plan_path, config_path, log)
        return fallback

    for stream in (completed.stdout, completed.stderr):
        for line in (stream or "").splitlines():
            text = line.rstrip()
            if text:
                log(text)

    if completed.returncode != 0:
        log(f"[执行规划] 失败，退出码：{completed.returncode}；使用原方案。")
        _persist_original_plan_to_db(plan_path, config_path, log)
        return fallback
    if not _complete_fresh_bundle(execution_paths, before):
        log("[执行规划] 未生成完整且有效的执行文件；使用原方案。")
        _persist_original_plan_to_db(plan_path, config_path, log)
        return fallback

    log(f"[执行规划] 完成；统一使用：{execution_report}")
    return ExecutionPlanningOutcome(
        True,
        execution_report,
        wcs_output,
        wcs_map_output,
    )


def _persist_original_plan_to_db(
    plan_path: Path,
    config_path: Path,
    log: Callable[[str], None],
) -> None:
    """执行规划失败时，把原装箱结果写入 wcs_success_box，保证仍可下传。"""
    try:
        # UI 以 packing/ 为 src 根；实现位于 packing-system/src
        from src.service.success_box_db import persist_success_boxes_from_plan_file
    except ImportError:
        try:
            system_root = packing_system_root_from_here()
            root_s = str(system_root)
            if root_s not in sys.path:
                sys.path.insert(0, root_s)
            from src.service.success_box_db import (  # type: ignore
                persist_success_boxes_from_plan_file,
            )
        except Exception as exc:  # noqa: BLE001
            log(f"[WCS-DB] 回退入库不可用：{exc}")
            return
    try:
        n = persist_success_boxes_from_plan_file(
            plan_path, config_path=config_path
        )
        log(
            f"[WCS-DB] 执行规划失败，已用原方案入库（影响行数 {n}）：{plan_path.name}"
        )
    except Exception as exc:  # noqa: BLE001
        log(f"[WCS-DB] 原方案入库失败（不影响可视化）：{exc}")
