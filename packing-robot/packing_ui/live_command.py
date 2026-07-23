"""现场码垛指令文件：仪表盘写入，机器人仿真轮询执行。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


DEFAULT_COMMAND_NAME = "live_stack_command.json"


def default_command_path() -> Path:
    """packing-workspace/runtime/live_stack_command.json（相对 monorepo）。"""
    # packing-robot/packing_ui -> packing-robot -> zhuang
    repo = Path(__file__).resolve().parents[2].parent
    runtime = repo / "packing-workspace" / "runtime"
    runtime.mkdir(parents=True, exist_ok=True)
    return runtime / DEFAULT_COMMAND_NAME


def write_live_command(path: Path, payload: dict[str, Any]) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)
    return path


def read_live_command(path: Path) -> dict[str, Any] | None:
    path = Path(path)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None
