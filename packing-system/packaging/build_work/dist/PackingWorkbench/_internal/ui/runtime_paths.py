# -*- coding: utf-8 -*-
"""运行时路径与子进程命令构造（开发 / 冻结共用）。"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import List, Sequence


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def app_root_from_project(project_dir: Path) -> Path:
    """冻结时 project_dir 就是 exe 目录；开发时为 packing-system。"""
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return Path(project_dir).resolve()


def backend_command(mode: str, args: Sequence[str]) -> List[str]:
    """构造后端子进程命令。

    mode: packing | wcs | receiver
    """
    mode = str(mode).strip().lower()
    extra = [str(a) for a in args]
    if is_frozen():
        return [sys.executable, "--mode", mode, *extra]
    # 开发态：仍走原脚本路径，由调用方传入脚本绝对路径作为 args[0] 不适用；
    # 这里只负责 frozen；开发态由 UI 自己拼 python + script。
    raise RuntimeError("backend_command() 仅用于冻结态；开发态请直接拼脚本路径")


def packing_entry_exists(project_dir: Path) -> bool:
    if is_frozen():
        return True
    return (Path(project_dir) / "packing" / "run_packing.py").is_file()


def wcs_entry_exists(project_dir: Path) -> bool:
    if is_frozen():
        return True
    return (Path(project_dir) / "packing" / "run_wcs_service.py").is_file()


def receiver_entry_exists(project_dir: Path) -> bool:
    if is_frozen():
        return True
    return (Path(project_dir) / "local_wcs_receiver" / "run_receiver.py").is_file()
