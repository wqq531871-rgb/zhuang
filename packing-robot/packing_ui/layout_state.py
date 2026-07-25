"""State-path selection and pallet-layout state persistence."""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import pymysql
from pymysql.cursors import DictCursor


STATE_PATH_CAMERA = "camera"
STATE_PATH_LAYOUT = "layout"
SUPPORTED_STATE_PATHS = frozenset((STATE_PATH_CAMERA, STATE_PATH_LAYOUT))


SELECT_PALLET_ROWS = """
SELECT id, seq, raw_length, raw_width, state
FROM wcs_success_box
WHERE box_unique_id = %s
ORDER BY seq ASC
FOR UPDATE
""".strip()

UPDATE_LAYOUT_STATE = """
UPDATE wcs_success_box
SET state = %s
WHERE id = %s
""".strip()


class LayoutStateError(RuntimeError):
    """The selected state path or pallet layout could not be applied safely."""


@dataclass(frozen=True)
class LayoutStateDecision:
    seq: int
    x_size: float
    y_size: float
    previous_state: int | None
    state: int


@dataclass(frozen=True)
class LayoutStateAssignment:
    box_unique_id: str
    box_count: int
    changed_count: int
    decisions: tuple[LayoutStateDecision, ...]


def normalize_state_path(value: object) -> str:
    path = str(value or "").strip().lower()
    if path not in SUPPORTED_STATE_PATHS:
        raise LayoutStateError(
            f"不支持的判态路径 {value!r}，只允许 camera 或 layout"
        )
    return path


def state_from_layout_dims(x_size: object, y_size: object) -> int:
    try:
        x_value = float(x_size)
        y_value = float(y_size)
    except (TypeError, ValueError) as exc:
        raise LayoutStateError("箱子 X/Y 尺寸必须是有效数值") from exc
    if not math.isfinite(x_value) or not math.isfinite(y_value):
        raise LayoutStateError("箱子 X/Y 尺寸必须是有限数值")
    if x_value <= 0 or y_value <= 0:
        raise LayoutStateError("箱子 X/Y 尺寸必须大于 0")
    return 1 if y_value >= x_value else 2


def _previous_state(value: object) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise LayoutStateError(f"数据库中存在非法 state={value!r}") from exc


def _connection_kwargs(config: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "host": config["host"],
        "port": int(config["port"]),
        "user": config["user"],
        "password": config["password"],
        "database": config["database"],
        "charset": config.get("charset", "utf8mb4"),
        "cursorclass": DictCursor,
        "autocommit": False,
    }


def assign_pallet_layout_states(
    box_unique_id: str,
    *,
    config_path: Path | None = None,
    settings: Mapping[str, Any] | None = None,
    connect_factory: Any = pymysql.connect,
) -> LayoutStateAssignment:
    """Atomically set every current-pallet state from its planned X/Y footprint."""
    uid = str(box_unique_id or "").strip()
    if not uid:
        raise LayoutStateError("缺少当前托盘 box_unique_id")

    if settings is not None:
        config = dict(settings)
    else:
        from .plan_from_db import load_mysql_settings

        config = load_mysql_settings(config_path)
    connection = None
    cursor = None
    try:
        connection = connect_factory(**_connection_kwargs(config))
        cursor = connection.cursor()
        cursor.execute(SELECT_PALLET_ROWS, (uid,))
        rows = list(cursor.fetchall() or [])
        if not rows:
            raise LayoutStateError(f"当前托盘 {uid} 没有箱子记录")

        sequences = [int(row.get("seq") or 0) for row in rows]
        if sequences != list(range(1, len(rows) + 1)):
            raise LayoutStateError(
                f"当前托盘 {uid} 的 seq 必须从 1 开始连续，实际为 {sequences}"
            )

        decisions: list[LayoutStateDecision] = []
        changed_count = 0
        for row in rows:
            seq = int(row["seq"])
            x_size = float(row["raw_length"])
            y_size = float(row["raw_width"])
            state = state_from_layout_dims(x_size, y_size)
            previous = _previous_state(row.get("state"))
            decisions.append(
                LayoutStateDecision(
                    seq=seq,
                    x_size=x_size,
                    y_size=y_size,
                    previous_state=previous,
                    state=state,
                )
            )
            if previous == state:
                continue
            cursor.execute(UPDATE_LAYOUT_STATE, (state, int(row["id"])))
            if int(cursor.rowcount) != 1:
                raise LayoutStateError(
                    f"当前托盘 {uid} seq={seq} 的 state 更新行数异常："
                    f"{cursor.rowcount}"
                )
            changed_count += 1

        connection.commit()
        return LayoutStateAssignment(
            box_unique_id=uid,
            box_count=len(decisions),
            changed_count=changed_count,
            decisions=tuple(decisions),
        )
    except LayoutStateError:
        if connection is not None:
            try:
                connection.rollback()
            except Exception:
                pass
        raise
    except Exception as exc:
        if connection is not None:
            try:
                connection.rollback()
            except Exception:
                pass
        message = str(exc)
        password = str(config.get("password") or "")
        if password:
            message = message.replace(password, "***")
        raise LayoutStateError(f"垛型 state 写入失败：{message}") from exc
    finally:
        if cursor is not None:
            try:
                cursor.close()
            except Exception:
                pass
        if connection is not None:
            try:
                connection.close()
            except Exception:
                pass
