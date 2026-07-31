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
    # 同一 uid 再来：更新并移到末尾。其它托盘只有在 PLC 最后 seq
    # 完成握手后才能结束，选中新托盘本身不是完成信号。
    kept: List[Dict[str, Any]] = []
    for old in items:
        old_uid = str(old.get("box_unique_id") or "").strip()
        if old_uid == uid:
            continue
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
    session = {
        "box_unique_id": uid,
        "order_id": str(order_id or ""),
        "robot_id": str(robot_id or ""),
        "plan_path": None,
        "source": source,
        "last_arrived_seq": None,
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
        "plan_path": None,
        "auto_play": False,
        "refresh_history": True,
    }
    _atomic_write(command_path(workspace), cmd)
    print(
        f"[现场会话] 已选定托盘 uid={uid} order={order_id or '-'} "
        f"（三维从 DB 加载）历史={len(history)} 盘"
    )
    return {**session, "history_count": len(history)}


def record_box_arrive(
    *,
    box_unique_id: str,
    seq: int,
    order_id: str = "",
    robot_id: str = "",
    product_code: str = "",
    workspace: Optional[Path] = None,
) -> Dict[str, Any]:
    """接口4：登记一箱到达（不写 state、不碰 PLC）。"""
    uid = str(box_unique_id or "").strip()
    seq_i = int(seq)
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    path = session_path(workspace)
    prev = read_json(path) or {}
    # 若会话托盘不一致，以本次到达为准（避免未先走接口3时面板空白）
    session = {
        "box_unique_id": uid or str(prev.get("box_unique_id") or ""),
        "order_id": str(order_id or prev.get("order_id") or ""),
        "robot_id": str(robot_id or prev.get("robot_id") or ""),
        "plan_path": prev.get("plan_path"),
        "source": "boxarrive",
        "last_arrived_seq": seq_i,
        "last_arrived_product_code": str(product_code or ""),
        "updated_at": now,
    }
    if not session["box_unique_id"]:
        session["box_unique_id"] = uid
    _atomic_write(path, session)
    print(
        f"[现场会话] 箱子到达 uid={session['box_unique_id']} "
        f"seq={seq_i} product={product_code or '-'}"
    )
    return dict(session)


def write_live_play_box(
    *,
    box_unique_id: str,
    seq: int,
    state: int,
    order_id: str = "",
    item_id: str = "",
    product_code: str = "",
    camera_length: Optional[float] = None,
    camera_width: Optional[float] = None,
    camera_height: Optional[float] = None,
    auto_play: bool = True,
    workspace: Optional[Path] = None,
) -> Dict[str, Any]:
    """通知三维：当前箱数据就绪；auto_play=True 时播装载一步。"""
    uid = str(box_unique_id or "").strip()
    cmd = {
        "id": datetime.now().strftime("%Y%m%d_%H%M%S_%f"),
        "action": "play_box",
        "box_unique_id": uid,
        "order_id": str(order_id or ""),
        "seq": int(seq),
        "item_id": str(item_id or ""),
        "product_code": str(product_code or ""),
        "state": int(state),
        "camera_length": camera_length,
        "camera_width": camera_width,
        "camera_height": camera_height,
        "auto_play": bool(auto_play) and int(state) in (1, 2),
        "show_conveyor": True,
    }
    path = _atomic_write(command_path(workspace), cmd)
    print(
        f"[现场指令] play_box uid={uid} seq={seq} state={state} "
        f"auto_play={cmd['auto_play']} → {path.name}"
    )
    return cmd


def clear_current_session_after_replan(
    workspace: Optional[Path] = None,
) -> None:
    """兼容旧调用：重新计算不改变现场未完成托盘状态。"""
    session = read_json(session_path(workspace)) or {}
    uid = str(session.get("box_unique_id") or "").strip()
    if uid:
        print(f"[现场会话] 新计算结果已入库，保留未完成托盘 uid={uid}")
    else:
        print("[现场会话] 新计算结果已入库，当前没有未完成托盘")
