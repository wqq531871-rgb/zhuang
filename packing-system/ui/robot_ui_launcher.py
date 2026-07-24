"""Launch packing-robot (PySide6) as a separate process from the PyQt5 dashboard."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable, Optional, Sequence


def default_robot_directory() -> Path:
    """Resolve packing-robot next to packing-system, or PACKING_ROBOT_DIR."""
    env = (os.environ.get("PACKING_ROBOT_DIR") or "").strip()
    if env:
        return Path(env).expanduser().resolve()
    # ui/ -> packing-system/ -> zhuang/
    repo_root = Path(__file__).resolve().parent.parent.parent
    return repo_root / "packing-robot"


def _sanitize_qt_env(env: dict) -> dict:
    """Strip PyQt5 plugin paths so child PySide6 process can load Qt6 DLLs."""
    drop_keys = {
        "QT_PLUGIN_PATH",
        "QT_QPA_PLATFORM_PLUGIN_PATH",
        "QT_QPA_PLATFORM",
        "DYLD_LIBRARY_PATH",
    }
    for key in list(env):
        if key in drop_keys or key.startswith("QT_"):
            # keep only our explicit QT_API below
            if key != "QT_API":
                env.pop(key, None)
    # Avoid inheriting a PATH that prefers PyQt5/Qt5 bin over PySide6
    path = env.get("PATH") or ""
    parts = [
        p
        for p in path.split(os.pathsep)
        if p
        and "PyQt5" not in p.replace("\\", "/")
        and "/Qt5/" not in p.replace("\\", "/")
    ]
    env["PATH"] = os.pathsep.join(parts)
    env["QT_API"] = "pyside6"
    return env


def check_robot_dependencies(python_executable: str | Path = sys.executable) -> None:
    """Raise RuntimeError if PySide6 / QtCore cannot import."""
    code = (
        "import sys\n"
        "try:\n"
        "    from PySide6.QtCore import Qt\n"
        "except Exception as exc:\n"
        "    print(exc)\n"
        "    sys.exit(2)\n"
        "sys.exit(0)\n"
    )
    try:
        completed = subprocess.run(
            [str(python_executable), "-c", code],
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
            env=_sanitize_qt_env(os.environ.copy()),
        )
    except OSError as exc:
        raise RuntimeError(f"无法检测 Python 依赖：{exc}") from exc
    if completed.returncode == 2:
        detail = (completed.stdout or completed.stderr or "").strip()
        raise RuntimeError(
            "当前 Python 的 PySide6 无法加载（常见：版本过新或与 Anaconda 冲突）。\n"
            f"解释器：{python_executable}\n"
            f"错误：{detail or 'QtCore DLL load failed'}\n"
            "请执行：python -m pip install \"PySide6==6.7.3\""
        )
    if completed.returncode != 0:
        raise RuntimeError(
            "当前 Python 缺少可用的 PySide6，三维码垛无法启动。\n"
            f"解释器：{python_executable}\n"
            "请执行：python -m pip install \"PySide6==6.7.3\""
        )


def launch_robot_ui(
    *,
    directory: Optional[str | Path] = None,
    python_executable: str | Path = sys.executable,
    popen_factory: Callable[..., Any] = subprocess.Popen,
    plan_path: Optional[str | Path] = None,
    command_file: Optional[str | Path] = None,
    config_path: Optional[str | Path] = None,
    extra_args: Optional[Sequence[str]] = None,
    check_deps: bool = True,
) -> Any:
    directory = Path(directory) if directory is not None else default_robot_directory()
    script = directory / "main.py"
    if not script.is_file():
        raise FileNotFoundError(f"机器人仿真程序不存在：{script}")
    if check_deps:
        check_robot_dependencies(python_executable)
    env = _sanitize_qt_env(os.environ.copy())
    cmd = [str(Path(python_executable)), str(script)]
    # plan_path 已废弃（三维从 DB 加载），保留参数仅为兼容调用方
    del plan_path
    if command_file:
        cmd.extend(["--command-file", str(command_file)])
    if config_path:
        cmd.extend(["--config", str(config_path)])
    if extra_args:
        cmd.extend(list(extra_args))
    return popen_factory(
        cmd,
        cwd=str(directory),
        env=env,
    )
