"""Launch packing-robot (PySide6) as a separate process from the PyQt5 dashboard."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable, Optional


def default_robot_directory() -> Path:
    """Resolve packing-robot next to packing-system, or PACKING_ROBOT_DIR."""
    env = (os.environ.get("PACKING_ROBOT_DIR") or "").strip()
    if env:
        return Path(env).expanduser().resolve()
    # ui/ -> packing-system/ -> zhuang/
    repo_root = Path(__file__).resolve().parent.parent.parent
    return repo_root / "packing-robot"


def launch_robot_ui(
    *,
    directory: Optional[str | Path] = None,
    python_executable: str | Path = sys.executable,
    popen_factory: Callable[..., Any] = subprocess.Popen,
) -> Any:
    directory = Path(directory) if directory is not None else default_robot_directory()
    script = directory / "main.py"
    if not script.is_file():
        raise FileNotFoundError(f"机器人仿真程序不存在：{script}")
    env = os.environ.copy()
    env.setdefault("QT_API", "pyside6")
    return popen_factory(
        [str(Path(python_executable)), str(script)],
        cwd=str(directory),
        env=env,
    )
