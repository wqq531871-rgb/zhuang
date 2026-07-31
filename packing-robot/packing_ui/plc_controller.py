"""Shared PLC connect / send / stop logic for the standalone PLC window."""

from __future__ import annotations

import atexit
import os
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, QThread, Signal

from .data import PalletPlan
from .layout_state import (
    STATE_PATH_LAYOUT,
    LayoutStateAssignment,
    assign_pallet_layout_states,
    normalize_state_path,
)

_DEFAULT_STATE_SOURCE = STATE_PATH_LAYOUT
from .live_command import (
    default_history_path,
    default_session_path,
    mark_live_pallet_done,
    recover_live_session,
)
from .plan_from_db import fetch_plc_row, load_plan_from_db, update_camera_dimensions
from .plc_protocol import S7Client, S7Config, create_snap7_client
from .plc_worker import PlcSendWorker


def default_plc_lock_path() -> Path:
    env = (os.environ.get("PACKING_WORKSPACE") or "").strip()
    if env:
        root = Path(env).expanduser().resolve()
    else:
        root = Path(__file__).resolve().parents[2] / "packing-workspace"
    return root / "runtime" / "plc_s7.lock"


class PlcLockError(RuntimeError):
    """Another process already holds the S7 connection lock."""


class PlcController(QObject):
    """Owns S7 probe + send worker; UI binds to signals / methods."""

    log = Signal(str)
    connection_changed = Signal(bool, str)  # connected, status text
    task_changed = Signal(str)
    words_changed = Signal(str)
    sending_changed = Signal(bool)
    plan_changed = Signal(object)  # PalletPlan | None
    path_status_changed = Signal(str)

    def __init__(
        self,
        *,
        parent: QObject | None = None,
        config_path: str | Path | None = None,
        plc_client_factory: Any = None,
        plc_worker_factory: Any = None,
        camera_dimension_writer: Any = None,
        layout_state_writer: Any = None,
        lock_path: str | Path | None = None,
        row_loader: Any = None,
        plan_loader: Any = None,
        pallet_completion_writer: Any = None,
    ) -> None:
        super().__init__(parent)
        self._config_path = Path(config_path) if config_path else None
        self._plc_client_factory = plc_client_factory or create_snap7_client
        self._plc_worker_factory = plc_worker_factory or PlcSendWorker
        self._camera_dimension_writer = (
            camera_dimension_writer or update_camera_dimensions
        )
        self._layout_state_writer = (
            layout_state_writer or assign_pallet_layout_states
        )
        self._row_loader = row_loader or fetch_plc_row
        self._plan_loader = plan_loader or load_plan_from_db
        self._pallet_completion_writer = (
            pallet_completion_writer or mark_live_pallet_done
        )
        self._lock_path = (
            Path(lock_path) if lock_path else default_plc_lock_path()
        )
        self._lock_held = False
        self._plc_probe = None
        self._plc_connected = False
        self._plc_thread: QThread | None = None
        self._plc_worker = None
        self._s7_config: S7Config | None = None
        self.current_plan: PalletPlan | None = None
        self._state_source = _DEFAULT_STATE_SOURCE
        atexit.register(self._release_lock_silent)

    @property
    def plc_connected(self) -> bool:
        return self._plc_connected

    @property
    def is_sending(self) -> bool:
        return self._plc_thread is not None and self._plc_thread.isRunning()

    def set_state_source(self, value: str) -> None:
        self._state_source = normalize_state_path(value)

    def current_state_path(self) -> str:
        return normalize_state_path(self._state_source)

    def load_plan(self, box_unique_id: str) -> PalletPlan:
        plan = self._plan_loader(
            str(box_unique_id).strip(), config_path=self._config_path
        )
        self.current_plan = plan
        self.plan_changed.emit(plan)
        return plan

    def try_load_session_plan(self) -> PalletPlan | None:
        session = recover_live_session(
            default_session_path(),
            default_history_path(),
        )
        uid = str((session or {}).get("box_unique_id") or "").strip()
        if not uid:
            return None
        return self.load_plan(uid)

    def apply_layout_state(
        self, *, automatic: bool = False
    ) -> LayoutStateAssignment:
        if self.is_sending:
            raise RuntimeError("PLC 任务运行中，禁止改写当前托盘 state")
        if self.current_plan is None or not self.current_plan.items:
            raise ValueError("尚未加载可判态托盘")
        uid = str(self.current_plan.source_key or "").strip()
        if not uid:
            raise ValueError("当前托盘缺少 box_unique_id")

        result = self._layout_state_writer(
            uid,
            config_path=self._config_path,
        )
        refreshed = self.load_plan(uid)
        if refreshed.source_key != uid:
            raise ValueError(
                f"state 已写入，但刷新返回了错误托盘 {refreshed.source_key}"
            )
        prefix = "自动" if automatic else "手动"
        message = (
            f"{prefix}垛型直判已写入 {result.box_count} 箱"
            f"（变化 {result.changed_count} 箱）"
        )
        self.path_status_changed.emit(message)
        self.log.emit(message)
        return result

    def connect_plc(self, config: S7Config) -> None:
        if self._plc_connected:
            self.disconnect_plc()
            return
        if self.is_sending:
            self.stop_send()
            if not self.wait_send_finished(5000):
                raise RuntimeError("上一任务仍在停止中，请稍后再连接")
        self._s7_config = config
        self._acquire_lock()
        try:
            # 先探测连通，再立刻断开：PLC 通常只允许一路 snap7，连接位留给下发线程
            probe = S7Client(self._plc_client_factory(), config)
            probe.connect()
            try:
                probe.disconnect()
            except Exception:
                pass
            self._plc_probe = None
            self._plc_connected = True
            status = f"已连接 {config.ip} / DB{config.db_number}"
            self.connection_changed.emit(True, status)
            self.log.emit("PLC 连接成功（待命；开始下发时占用连接）")
        except Exception:
            self._release_lock()
            raise

    def disconnect_plc(self) -> None:
        if self.is_sending:
            self.stop_send()
            self.wait_send_finished(3000)
        try:
            if self._plc_probe is not None:
                self._plc_probe.disconnect()
        finally:
            self._plc_probe = None
            self._plc_connected = False
            self._release_lock()
            self.connection_changed.emit(False, "未连接")

    def _release_probe_for_worker(self) -> None:
        if self._plc_probe is None:
            return
        try:
            self._plc_probe.disconnect()
        except Exception:
            pass
        self._plc_probe = None

    def start_pallet_send(self, config: S7Config, *, source: str = "manual") -> None:
        if self.is_sending:
            self.log.emit("已有托盘正在下发，拒绝重复启动")
            return
        if not self._plc_connected:
            self.log.emit("PLC 尚未连接")
            return
        if self.current_plan is None or not self.current_plan.items:
            self.log.emit("尚未加载可发送托盘")
            return

        state_source = self.current_state_path()
        if state_source == STATE_PATH_LAYOUT:
            try:
                self.apply_layout_state(automatic=True)
            except Exception as exc:  # noqa: BLE001
                self.log.emit(f"垛型直判失败，未启动 PLC：{exc}")
                return

        uid = str(self.current_plan.source_key)
        sequences = tuple(int(item.sequence) for item in self.current_plan.items)
        final_seq = max(sequences)
        # 确保下发线程独占连接
        self._release_probe_for_worker()
        worker = self._plc_worker_factory(
            config=config,
            box_unique_id=uid,
            sequences=sequences,
            row_loader=lambda box_uid, seq: self._row_loader(
                box_uid, seq, config_path=self._config_path
            ),
            camera_writer=lambda box_uid, seq, length, width, height: (
                self._camera_dimension_writer(
                    box_uid,
                    seq,
                    length,
                    width,
                    height,
                    config_path=self._config_path,
                )
            ),
            state_source=state_source,
            client_factory=self._plc_client_factory,
        )
        thread = QThread(self)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.status.connect(self.log.emit)
        worker.plc_status.connect(self._on_plc_status)
        worker.box_finished.connect(
            lambda seq, started_uid=uid, last_seq=final_seq: (
                self._on_box_finished(started_uid, last_seq, seq)
            )
        )
        worker.alarm.connect(
            lambda seq: self.log.emit(
                f"报警：seq={seq} state=0，仅写入 DBW32=1"
            )
        )
        worker.failed.connect(
            lambda error: self.log.emit(f"PLC任务失败：{error}")
        )
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(self._on_plc_thread_finished)
        thread.finished.connect(thread.deleteLater)
        self._plc_worker = worker
        self._plc_thread = thread
        self.sending_changed.emit(True)
        self.task_changed.emit(
            f"托盘：{uid}　数据库 seq：{sequences[0]}　PLC seq：—"
        )
        self.log.emit(
            f"{'自动' if source == 'auto' else '手动'}启动托盘下发：{uid}"
        )
        thread.start()

    def maybe_auto_start(self, config: S7Config, *, auto_enabled: bool) -> None:
        if not auto_enabled:
            return
        if not self._plc_connected:
            self.log.emit("托盘已加载，等待 PLC 连接")
            return
        self.start_pallet_send(config, source="auto")

    def stop_send(self) -> None:
        if self._plc_worker is None:
            return
        if getattr(self._plc_worker, "_stop_requested", False):
            return
        self._plc_worker.request_stop()
        self.log.emit("正在停止…")

    def wait_send_finished(self, timeout_ms: int = 3000) -> bool:
        thread = self._plc_thread
        if thread is None or not thread.isRunning():
            return True
        return bool(thread.wait(timeout_ms))

    def shutdown(self) -> None:
        self.stop_send()
        self.wait_send_finished(3000)
        if self._plc_connected:
            self.disconnect_plc()
        else:
            self._release_lock()

    def _on_plc_status(self, status: Any) -> None:
        if status is None:
            return
        self.words_changed.emit(
            f"FP：{status.fp}　FP_OVER：{status.fp_over}　"
            f"KONGXIAN：{status.idle}　DH_OVER：{status.dh_over}"
        )
        uid = self.current_plan.source_key if self.current_plan else "—"
        self.task_changed.emit(
            f"托盘：{uid}　数据库 seq：—　PLC seq：{status.request_seq}"
        )
        # DBW12 KONGXIAN==0 → 接口 4.7 data.status=0（就绪）
        try:
            from .device_status import mark_ready_on_kongxian_idle

            mark_ready_on_kongxian_idle(getattr(status, "idle", None))
        except Exception as exc:
            self.log.emit(f"[4.7-状态] 写就绪失败：{exc}")

    def _on_box_finished(
        self,
        box_unique_id: str,
        final_seq: int,
        seq: int,
    ) -> None:
        """处理一箱完整握手；只有最大 seq 才结束当前托盘。"""
        seq_i = int(seq)
        final_seq_i = int(final_seq)
        self.log.emit(f"seq={seq_i} 下发并握手完成")
        if seq_i != final_seq_i:
            return
        try:
            changed = self._pallet_completion_writer(str(box_unique_id))
            if changed is False:
                self.log.emit(
                    f"托盘 {box_unique_id} 最后 seq={seq_i} 已握手，"
                    "但未找到对应 active 历史，状态未改写"
                )
                return
            self.log.emit(
                f"托盘 {box_unique_id} 最后 seq={seq_i} 已握手，已标记 done"
            )
        except Exception as exc:  # noqa: BLE001
            self.log.emit(
                f"托盘 {box_unique_id} 最后 seq={seq_i} 已握手，"
                f"但完成状态保存失败：{exc}"
            )

    def _on_plc_thread_finished(self) -> None:
        self._plc_worker = None
        self._plc_thread = None
        self.sending_changed.emit(False)
        self.log.emit("PLC 托盘任务结束")

    def _acquire_lock(self) -> None:
        path = self._lock_path
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.is_file():
            try:
                old_pid = int(path.read_text(encoding="utf-8").strip() or "0")
            except (OSError, ValueError):
                old_pid = 0
            if old_pid and old_pid != os.getpid() and _pid_alive(old_pid):
                raise PlcLockError(
                    f"另一 PLC 窗口已连接（PID {old_pid}），请先断开后再连"
                )
        path.write_text(str(os.getpid()), encoding="utf-8")
        self._lock_held = True

    def _release_lock(self) -> None:
        if not self._lock_held:
            return
        path = self._lock_path
        try:
            if path.is_file():
                text = path.read_text(encoding="utf-8").strip()
                if text == str(os.getpid()):
                    path.unlink(missing_ok=True)
        except OSError:
            pass
        self._lock_held = False

    def _release_lock_silent(self) -> None:
        try:
            self._release_lock()
        except Exception:
            pass


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    except AttributeError:
        # Windows: os.kill exists; fallback via ctypes not needed on CPython Win
        return True
    return True
