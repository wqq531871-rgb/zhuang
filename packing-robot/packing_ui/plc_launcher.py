"""Launch the standalone PLC communication window as a separate process."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Any, Callable, Optional


def default_robot_directory() -> Path:
    return Path(__file__).resolve().parents[1]


def launch_plc_ui(
    *,
    directory: Optional[str | Path] = None,
    python_executable: str | Path = sys.executable,
    popen_factory: Callable[..., Any] = subprocess.Popen,
    config_path: Optional[str | Path] = None,
) -> Any:
    directory = Path(directory) if directory is not None else default_robot_directory()
    script = directory / "main.py"
    if not script.is_file():
        raise FileNotFoundError(f"PLC 通讯程序不存在：{script}")
    cmd = [str(Path(python_executable)), str(script), "--plc-window", "--auto-connect"]
    if config_path:
        cmd.extend(["--config", str(config_path)])
    return popen_factory(
        cmd,
        cwd=str(directory),
    )
