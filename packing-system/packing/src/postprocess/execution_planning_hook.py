"""装箱完成后调用根目录 run_execution_planning.py（受 execution_sequence.enabled 控制）。"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Callable, Optional


def packing_system_root_from_here() -> Path:
    # packing/src/postprocess -> packing-system
    return Path(__file__).resolve().parents[3]


def run_execution_planning_for_plan(
    plan_path: Path,
    config_path: Path,
    *,
    project_root: Optional[Path] = None,
    log: Callable[[str], None] = print,
) -> bool:
    """对已生成的 packing_plan JSON 跑执行顺序规划。

    Returns:
        True 表示脚本退出码为 0（含 config 关闭而跳过）；False 表示失败。
    """
    plan_path = Path(plan_path).resolve()
    config_path = Path(config_path).resolve()
    root = Path(project_root).resolve() if project_root else packing_system_root_from_here()
    script = root / "run_execution_planning.py"
    if not script.exists():
        log(f"[执行规划] 找不到脚本：{script}")
        return False
    if not plan_path.exists():
        log(f"[执行规划] 找不到装箱报告：{plan_path}")
        return False
    if not config_path.exists():
        log(f"[执行规划] 找不到配置：{config_path}")
        return False

    wcs_output = plan_path.with_name(plan_path.stem + "_execution_wcs.json")
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
        return False

    for stream in (completed.stdout, completed.stderr):
        for line in (stream or "").splitlines():
            text = line.rstrip()
            if text:
                log(text)

    if completed.returncode != 0:
        log(f"[执行规划] 失败，退出码：{completed.returncode}")
        return False
    log("[执行规划] 完成。")
    return True
