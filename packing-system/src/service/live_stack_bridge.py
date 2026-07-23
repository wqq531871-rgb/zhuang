# -*- coding: utf-8 -*-
"""现场码垛会话：接口3 选定托盘写入历史，三维窗口按历史列表展示。"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


def workspace_root_from_packing_system() -> Path:
    """packing-system/src/service → packing-system → zhuang → packing-workspace."""
    zhuang = Path(__file__).resolve().parents[3]
    return zhuang / "packing-workspace"


def runtime_dir(workspace: Optional[Path] = None) -> Path:
    root = Path(workspace) if workspace else workspace_root_from_packing_system()
    path = root / "runtime"
    path.mkdir(parents=True, exist_ok=True)
    return path


def session_path(workspace: Optional[Path] = None) -> Path:
    return runtime_dir(workspace) / "live_stack_session.json"


def command_path(workspace: Optional[Path] = None) -> Path:
    return runtime_dir(workspace) / "live_stack_command.json"


def history_path(workspace: Optional[Path] = None) -> Path:
    """接口3 历次选定托盘（含已完成），打开三维演示时全部可见。"""
    return runtime_dir(workspace) / "live_stack_pallets.json"


def _atomic_write(path: Path, payload) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)
    return path


def read_json(path: Path) -> Optional[Dict[str, Any]]:
    path = Path(path)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError, TypeError):
        return None
    return data if isinstance(data, dict) else None


def read_json_list(path: Path) -> List[Dict[str, Any]]:
    path = Path(path)
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError, TypeError):
        return []
    if not isinstance(data, list):
        return []
    return [x for x in data if isinstance(x, dict)]


def find_plan_map_for_uid(
    box_unique_id: str, workspace: Optional[Path] = None
) -> Optional[Path]:
    uid = str(box_unique_id or "").strip()
    root = Path(workspace) if workspace else workspace_root_from_packing_system()
    out = root / "output"
    if not out.is_dir():
        return None
    candidates: List[Path] = []
    for pattern in ("**/wcs_plan_map_*.json", "**/*_execution_wcs_map.json"):
        candidates.extend(out.glob(pattern))
    candidates = sorted(
        {p.resolve() for p in candidates if p.is_file()},
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if not uid:
        return candidates[0] if candidates else None
    for path in candidates:
        try:
            data = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError, TypeError):
            continue
        if isinstance(data, dict) and uid in data:
            return path
    return None


def list_selected_pallets(workspace: Optional[Path] = None) -> List[Dict[str, Any]]:
    """接口3 历史托盘，新的在后。"""
    return read_json_list(history_path(workspace))


def _upsert_history(
    entry: Dict[str, Any], workspace: Optional[Path] = None
) -> List[Dict[str, Any]]:
    uid = str(entry.get("box_unique_id") or "").strip()
    items = list_selected_pallets(workspace)
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    # 同一 uid 再来：更新并移到末尾；其余仍是「进行中」的标为已完成（WCS 已换盘）
    kept: List[Dict[str, Any]] = []
    for old in items:
        old_uid = str(old.get("box_unique_id") or "").strip()
        if old_uid == uid:
            continue
        if str(old.get("stack_status") or "") == "active":
            old = dict(old)
            old["stack_status"] = "done"
            old["completed_at"] = now
        kept.append(old)
    entry = dict(entry)
    entry["stack_status"] = "active"
    entry["updated_at"] = now
    if not entry.get("received_at"):
        entry["received_at"] = now
    kept.append(entry)
    _atomic_write(history_path(workspace), kept)
    return kept


def write_selected_pallet_session(
    *,
    box_unique_id: str,
    order_id: str = "",
    robot_id: str = "",
    source: str = "sendcasetask",
    workspace: Optional[Path] = None,
) -> Dict[str, Any]:
    """接口3：WCS 选定托盘 → 写入历史 + 当前会话 + 通知三维加载。"""
    uid = str(box_unique_id or "").strip()
    plan = find_plan_map_for_uid(uid, workspace=workspace)
    session = {
        "box_unique_id": uid,
        "order_id": str(order_id or ""),
        "robot_id": str(robot_id or ""),
        "plan_path": str(plan) if plan else None,
        "source": source,
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    _atomic_write(session_path(workspace), session)
    history_entry = {
        **session,
        "received_at": session["updated_at"],
    }
    history = _upsert_history(history_entry, workspace=workspace)
    cmd = {
        "id": datetime.now().strftime("%Y%m%d_%H%M%S_%f"),
        "action": "load_pallet",
        "box_unique_id": uid,
        "order_id": session["order_id"],
        "plan_path": session["plan_path"],
        "auto_play": False,
        "refresh_history": True,
    }
    _atomic_write(command_path(workspace), cmd)
    print(
        f"[现场会话] 已选定托盘 uid={uid} order={order_id or '-'} "
        f"plan={plan.name if plan else '未找到'} 历史={len(history)} 盘"
    )
    return {**session, "history_count": len(history)}


def clear_current_session_after_replan(
    workspace: Optional[Path] = None,
) -> None:
    """新一轮装箱结果入库后：清空「当前选定托盘」，避免面板一直显示上一盘。

    历史列表保留（三维仍可看过往盘），仅把进行中标为已完成。
    """
    path = session_path(workspace)
    if path.is_file():
        try:
            path.unlink()
        except OSError:
            _atomic_write(path, {})
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    items = list_selected_pallets(workspace)
    if not items:
        print("[现场会话] 新计算结果已入库，当前选定托盘已清空")
        return
    updated = []
    for old in items:
        entry = dict(old)
        if str(entry.get("stack_status") or "") == "active":
            entry["stack_status"] = "done"
            entry["completed_at"] = now
        updated.append(entry)
    _atomic_write(history_path(workspace), updated)
    print(f"[现场会话] 新计算结果已入库，当前选定已清空，历史 {len(updated)} 盘保留")
