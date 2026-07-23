"""Launch the existing PLC/MySQL desktop application as a separate process."""

from __future__ import annotations

from pathlib import Path
import subprocess
import sys
from typing import Any, Callable


DEFAULT_PLC_UI_DIRECTORY = Path(r"D:\research_code\tongxun")


def launch_plc_ui(
    *,
    directory: str | Path = DEFAULT_PLC_UI_DIRECTORY,
    python_executable: str | Path = sys.executable,
    popen_factory: Callable[..., Any] = subprocess.Popen,
) -> Any:
    directory = Path(directory)
    script = directory / "plc_gui.py"
    if not script.is_file():
        raise FileNotFoundError(f"PLC 通讯程序不存在：{script}")
    return popen_factory(
        [str(Path(python_executable)), str(script)],
        cwd=str(directory),
    )
