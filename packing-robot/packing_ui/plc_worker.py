"""Qt background worker for serialized live-state PLC sending."""

from __future__ import annotations

import time
from typing import Any, Callable, Iterable

from PySide6.QtCore import QObject, Signal, Slot

from .layout_state import (
    STATE_PATH_CAMERA,
    normalize_state_path,
)
from .plc_protocol import S7Client, S7Config, build_command, create_snap7_client


class PlcSendWorker(QObject):
    status = Signal(str)
    plc_status = Signal(object)
    box_finished = Signal(int)
    alarm = Signal(int)
    failed = Signal(str)
    finished = Signal()

    def __init__(
        self,
        *,
        config: S7Config,
        box_unique_id: str,
        sequences: Iterable[int],
        row_loader: Callable[[str, int], dict[str, Any] | None],
        camera_writer: Callable[[str, int, int, int, int], int],
        state_source: str = STATE_PATH_CAMERA,
        client_factory: Callable[[], Any] = create_snap7_client,
        protocol_factory: Callable[..., Any] = S7Client,
        sleep: Callable[[float], None] = time.sleep,
        state_poll_interval: float = 0.5,
    ) -> None:
        super().__init__()
        self.config = config
        self.box_unique_id = str(box_unique_id)
        self.sequences = tuple(int(value) for value in sequences)
        self._row_loader = row_loader
        self._camera_writer = camera_writer
        self.state_source = normalize_state_path(state_source)
        self._client_factory = client_factory
        self._protocol_factory = protocol_factory
        self._sleep = sleep
        self._state_poll_interval = state_poll_interval
        self._stop_requested = False

    @Slot()
    def request_stop(self) -> None:
        self._stop_requested = True

    @Slot()
    def run(self) -> None:
        protocol = None
        try:
            protocol = self._protocol_factory(
                self._client_factory(),
                self.config,
                sleep=self._sleep,
            )
            protocol.connect()
            for seq in self.sequences:
                if self._stop_requested:
                    self.status.emit("已停止")
                    return

                inbound = protocol.wait_request(seq)
                self.plc_status.emit(inbound)
                if self.state_source == STATE_PATH_CAMERA:
                    dimensions = (
                        int(inbound.camera_length),
                        int(inbound.camera_width),
                        int(inbound.camera_height),
                    )
                    if any(value <= 0 for value in dimensions):
                        raise ValueError(
                            f"seq={seq} 的 PLC 相机尺寸无效："
                            f"DBW6={dimensions[0]}，"
                            f"DBW8={dimensions[1]}，"
                            f"DBW10={dimensions[2]}"
                        )
                    written = int(
                        self._camera_writer(
                            self.box_unique_id,
                            seq,
                            *dimensions,
                        )
                    )
                    if written <= 0:
                        raise ValueError(
                            f"数据库中找不到 box_unique_id={self.box_unique_id} "
                            f"seq={seq}"
                        )
                    self.status.emit(
                        f"seq={seq} 相机尺寸已写库 "
                        f"{dimensions[0]}×{dimensions[1]}×{dimensions[2]}，"
                        "等待数据库 state"
                    )
                else:
                    self.status.emit(
                        f"seq={seq} 使用垛型直判，"
                        "跳过相机尺寸并读取数据库 state"
                    )

                while not self._stop_requested:
                    row = self._row_loader(self.box_unique_id, seq)
                    if row is None:
                        raise ValueError(
                            f"数据库中找不到 box_unique_id={self.box_unique_id} "
                            f"seq={seq}"
                        )
                    state = row.get("state")
                    if state is None or state == "":
                        self.status.emit(f"seq={seq} 等待数据库 state")
                        self._sleep(self._state_poll_interval)
                        continue
                    try:
                        state_i = int(state)
                    except (TypeError, ValueError) as exc:
                        raise ValueError(
                            f"seq={seq} 的 state={state!r} 非法，只允许空值、0、1、2"
                        ) from exc
                    if state_i == 0:
                        self.status.emit(f"seq={seq} state=0，仅发送报警")
                        plc_state = protocol.send_alarm(seq)
                        self.plc_status.emit(plc_state)
                        self.alarm.emit(seq)
                        return
                    if state_i not in (1, 2):
                        raise ValueError(
                            f"seq={seq} 的 state={state_i} 非法，只允许空值、0、1、2"
                        )
                    command_row = dict(row)
                    command_row["state"] = state_i
                    command = build_command(command_row)
                    self.status.emit(f"seq={seq} 正在下发")
                    plc_state = protocol.send_normal(command)
                    self.plc_status.emit(plc_state)
                    self.box_finished.emit(seq)
                    break
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc))
        finally:
            if protocol is not None:
                try:
                    protocol.disconnect()
                except Exception:
                    pass
            self.finished.emit()
