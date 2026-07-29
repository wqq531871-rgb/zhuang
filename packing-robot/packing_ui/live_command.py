"""现场码垛指令/会话/历史：仪表盘与接收端写入，机器人仿真轮询。"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any


DEFAULT_COMMAND_NAME = "live_stack_command.json"
DEFAULT_SESSION_NAME = "live_stack_session.json"
DEFAULT_HISTORY_NAME = "live_stack_pallets.json"


def default_runtime_dir() -> Path:
    # packing_ui/ → packing-robot/ → zhuang/
    zhuang = Path(__file__).resolve().parents[2]
    runtime = zhuang / "packing-workspace" / "runtime"
    runtime.mkdir(parents=True, exist_ok=True)
    return runtime


def default_command_path() -> Path:
    return default_runtime_dir() / DEFAULT_COMMAND_NAME


def default_session_path() -> Path:
    return default_runtime_dir() / DEFAULT_SESSION_NAME


def default_history_path() -> Path:
    return default_runtime_dir() / DEFAULT_HISTORY_NAME


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


def read_live_session(path: Path | None = None) -> dict[str, Any] | None:
    return read_live_command(path or default_session_path())


def read_live_pallet_history(path: Path | None = None) -> list[dict[str, Any]]:
    path = Path(path) if path else default_history_path()
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(data, list):
        return []
    return [x for x in data if isinstance(x, dict)]


def recover_live_session(
    session_path: Path | None = None,
    history_path: Path | None = None,
) -> dict[str, Any] | None:
    """读取当前会话；缺失时恢复最近一个仍在进行中的托盘。"""
    current_path = Path(session_path) if session_path else default_session_path()
    session = read_live_session(current_path)
    uid = str((session or {}).get("box_unique_id") or "").strip()
    if uid:
        return session

    for entry in reversed(read_live_pallet_history(history_path)):
        entry_uid = str(entry.get("box_unique_id") or "").strip()
        if entry_uid and str(entry.get("stack_status") or "") == "active":
            recovered = dict(entry)
            write_live_command(current_path, recovered)
            return recovered
    return None


def mark_live_pallet_done(
    box_unique_id: str,
    session_path: Path | None = None,
    history_path: Path | None = None,
) -> bool:
    """把指定活动托盘置为完成；仅清除仍指向该托盘的当前会话。"""
    uid = str(box_unique_id or "").strip()
    if not uid:
        return False

    current_path = Path(session_path) if session_path else default_session_path()
    pallet_history_path = (
        Path(history_path) if history_path else default_history_path()
    )
    history = read_live_pallet_history(pallet_history_path)
    completed_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    found = False
    changed = False
    updated: list[dict[str, Any]] = []
    for old in history:
        entry = dict(old)
        if str(entry.get("box_unique_id") or "").strip() == uid:
            found = True
            if str(entry.get("stack_status") or "") == "active":
                entry["stack_status"] = "done"
                entry["completed_at"] = completed_at
                changed = True
        updated.append(entry)
    if changed:
        write_live_command(pallet_history_path, updated)

    session = read_live_session(current_path)
    session_uid = str((session or {}).get("box_unique_id") or "").strip()
    if found and session_uid == uid:
        try:
            current_path.unlink(missing_ok=True)
        except OSError:
            write_live_command(current_path, {})
    return changed


def ensure_history_seeded(
    history_path: Path | None = None,
    session_path: Path | None = None,
) -> list[dict[str, Any]]:
    """若尚无历史文件，用当前会话托盘初始化（升级兼容）。"""
    hist_path = Path(history_path) if history_path else default_history_path()
    items = read_live_pallet_history(hist_path)
    if items:
        return items
    session = read_live_session(session_path)
    uid = str((session or {}).get("box_unique_id") or "").strip()
    if not session or not uid:
        return []
    entry = {
        **session,
        "stack_status": "active",
        "received_at": session.get("updated_at") or "",
    }
    write_live_command(hist_path, [entry])
    return [entry]
