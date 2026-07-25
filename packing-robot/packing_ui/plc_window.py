"""Standalone PLC communication window (camera accept / skip paths)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QCloseEvent, QFont
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from .data import PalletPlan
from .layout_state import STATE_PATH_CAMERA, STATE_PATH_LAYOUT
from .plc_controller import PlcController, PlcLockError
from .plc_protocol import S7Config


class PlcControlWindow(QMainWindow):
    def __init__(
        self,
        *,
        config_path: str | Path | None = None,
        autoload: bool = True,
        auto_connect: bool = False,
        plc_client_factory: Any = None,
        plc_worker_factory: Any = None,
        camera_dimension_writer: Any = None,
        layout_state_writer: Any = None,
        controller: PlcController | None = None,
        **_ignored,
    ) -> None:
        super().__init__()
        self.setWindowTitle("PLC 通讯")
        self.resize(520, 720)

        self.controller = controller or PlcController(
            parent=self,
            config_path=config_path,
            plc_client_factory=plc_client_factory,
            plc_worker_factory=plc_worker_factory,
            camera_dimension_writer=camera_dimension_writer,
            layout_state_writer=layout_state_writer,
        )
        self._build_ui()
        self._wire_controller()
        self._apply_style()
        self.statusBar().showMessage("从数据库加载托盘后连接 PLC")

        if autoload:
            try:
                plan = self.controller.try_load_session_plan()
                if plan is not None:
                    self._refresh_plan_labels(plan)
            except Exception as exc:  # noqa: BLE001
                self._append_log(f"加载现场托盘失败：{exc}")

        if auto_connect:
            # 等窗口显示后再连，避免阻塞启动
            QTimer.singleShot(0, self._connect_plc)

    def _build_ui(self) -> None:
        root = QWidget()
        layout = QVBoxLayout(root)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(10)

        pallet_group = QGroupBox("当前托盘")
        pallet_form = QFormLayout(pallet_group)
        self.uid_label = QLabel("—")
        self.order_label = QLabel("—")
        self.type_label = QLabel("—")
        self.box_count_label = QLabel("—")
        self.reload_button = QPushButton("从会话刷新托盘")
        pallet_form.addRow("box_unique_id", self.uid_label)
        pallet_form.addRow("订单", self.order_label)
        pallet_form.addRow("托盘类型", self.type_label)
        pallet_form.addRow("箱数", self.box_count_label)
        pallet_form.addRow("", self.reload_button)
        layout.addWidget(pallet_group)

        path_group = QGroupBox("相机路径")
        path_form = QFormLayout(path_group)
        self.state_path_combo = QComboBox()
        self.state_path_combo.addItem("不接收相机", STATE_PATH_LAYOUT)
        self.state_path_combo.addItem("接收相机", STATE_PATH_CAMERA)
        self.apply_state_path_button = QPushButton("应用到当前托盘")
        self.state_path_status_label = QLabel(
            "当前：不接收相机；跳过相机写库，启动前按垛型写 state"
        )
        self.state_path_status_label.setWordWrap(True)
        path_form.addRow("路径", self.state_path_combo)
        path_form.addRow("", self.apply_state_path_button)
        path_form.addRow("状态", self.state_path_status_label)
        layout.addWidget(path_group)

        plc_group = QGroupBox("PLC 通讯")
        plc_layout = QVBoxLayout(plc_group)
        form = QFormLayout()
        self.plc_ip_edit = QLineEdit("10.19.40.70")
        self.plc_rack_spin = QSpinBox()
        self.plc_rack_spin.setRange(0, 10)
        self.plc_slot_spin = QSpinBox()
        self.plc_slot_spin.setRange(0, 10)
        self.plc_slot_spin.setValue(1)
        self.plc_db_spin = QSpinBox()
        self.plc_db_spin.setRange(1, 9999)
        self.plc_db_spin.setValue(19)
        form.addRow("IP", self.plc_ip_edit)
        form.addRow("Rack", self.plc_rack_spin)
        form.addRow("Slot", self.plc_slot_spin)
        form.addRow("DB", self.plc_db_spin)
        plc_layout.addLayout(form)

        self.auto_plc_checkbox = QCheckBox("连接后自动等待下发")
        self.auto_plc_checkbox.setChecked(True)
        self.auto_plc_checkbox.setToolTip(
            "勾选后：连接成功或刷新托盘后自动进入「等 PLC 信号再下发」，无需点手动发送"
        )
        plc_layout.addWidget(self.auto_plc_checkbox)

        buttons = QHBoxLayout()
        self.connect_plc_button = QPushButton("连接 PLC")
        self.manual_plc_button = QPushButton("手动发送当前托盘")
        self.manual_plc_button.setToolTip(
            "一般无需点击；未勾选自动等待时可手动进入等信号下发"
        )
        self.stop_plc_button = QPushButton("停止")
        self.stop_plc_button.setEnabled(False)
        buttons.addWidget(self.connect_plc_button)
        buttons.addWidget(self.manual_plc_button)
        buttons.addWidget(self.stop_plc_button)
        plc_layout.addLayout(buttons)

        self.plc_connection_label = QLabel("未连接")
        self.plc_task_label = QLabel("托盘：—　数据库 seq：—　PLC seq：—")
        self.plc_words_label = QLabel(
            "FP：—　FP_OVER：—　KONGXIAN：—　DH_OVER：—"
        )
        self.plc_log = QPlainTextEdit()
        self.plc_log.setReadOnly(True)
        self.plc_log.setMaximumBlockCount(500)
        self.plc_log.setMinimumHeight(200)
        plc_layout.addWidget(self.plc_connection_label)
        plc_layout.addWidget(self.plc_task_label)
        plc_layout.addWidget(self.plc_words_label)
        plc_layout.addWidget(self.plc_log, 1)
        layout.addWidget(plc_group, 1)

        self.setCentralWidget(root)

        self.reload_button.clicked.connect(self._reload_session_plan)
        self.state_path_combo.currentIndexChanged.connect(self._on_state_path_changed)
        self.apply_state_path_button.clicked.connect(self._apply_selected_state_path)
        self.connect_plc_button.clicked.connect(self._connect_plc)
        self.manual_plc_button.clicked.connect(
            lambda: self.controller.start_pallet_send(
                self._plc_config(), source="manual"
            )
        )
        self.stop_plc_button.clicked.connect(self.controller.stop_send)

    def _wire_controller(self) -> None:
        ctrl = self.controller
        ctrl.log.connect(self._append_log)
        ctrl.connection_changed.connect(self._on_connection_changed)
        ctrl.task_changed.connect(self.plc_task_label.setText)
        ctrl.words_changed.connect(self.plc_words_label.setText)
        ctrl.sending_changed.connect(self._on_sending_changed)
        ctrl.plan_changed.connect(self._refresh_plan_labels)
        ctrl.path_status_changed.connect(self.state_path_status_label.setText)
        ctrl.set_state_source(self.state_path_combo.currentData())

    def _apply_style(self) -> None:
        self.setFont(QFont("Microsoft YaHei UI", 10))
        self.setStyleSheet(
            """
            QMainWindow, QWidget { background:#151515; color:#eeeeee; }
            QGroupBox {
                border:1px solid #787878; border-radius:6px;
                margin-top:10px; padding-top:8px;
            }
            QGroupBox::title { subcontrol-origin:margin; left:10px; padding:0 4px; }
            QLineEdit, QSpinBox, QComboBox {
                background:#303030; border:1px solid #454545;
                border-radius:5px; padding:5px 8px; min-height:22px;
            }
            QPlainTextEdit {
                background:#2b2b2b; border:1px solid #363636; border-radius:5px;
            }
            QPushButton {
                background:#343434; border:1px solid #505050;
                border-radius:4px; padding:7px 12px;
            }
            QPushButton:hover { background:#46545c; }
            QStatusBar { background:#111820; color:#9fb4c2; }
            """
        )

    def current_state_path(self) -> str:
        return self.controller.current_state_path()

    def _plc_config(self) -> S7Config:
        return S7Config(
            ip=self.plc_ip_edit.text().strip(),
            rack=self.plc_rack_spin.value(),
            slot=self.plc_slot_spin.value(),
            db_number=self.plc_db_spin.value(),
        )

    def _append_log(self, message: str) -> None:
        self.plc_log.appendPlainText(str(message))
        self.statusBar().showMessage(str(message))

    def _refresh_plan_labels(self, plan: Any) -> None:
        if not isinstance(plan, PalletPlan):
            self.uid_label.setText("—")
            self.order_label.setText("—")
            self.type_label.setText("—")
            self.box_count_label.setText("—")
            return
        self.uid_label.setText(plan.source_key or "—")
        self.order_label.setText(plan.sales_order_no or "—")
        self.type_label.setText(plan.pallet_type or "—")
        self.box_count_label.setText(str(len(plan.items)))
        self.setWindowTitle(
            f"PLC 通讯 — {plan.sales_order_no or plan.source_key or '托盘'}"
        )

    def _reload_session_plan(self) -> None:
        try:
            plan = self.controller.try_load_session_plan()
            if plan is None:
                QMessageBox.information(
                    self, "PLC 通讯", "会话中还没有选定托盘（接口3）。"
                )
                return
            self._refresh_plan_labels(plan)
            self._append_log(f"已加载托盘 {plan.source_key}")
            self._try_enter_wait_send(source="reload")
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "加载失败", str(exc))

    def _try_enter_wait_send(self, *, source: str) -> None:
        """连接成功或托盘就绪后进入等 PLC 信号的下发循环。"""
        if not self.auto_plc_checkbox.isChecked():
            self._append_log("未勾选「连接后自动等待下发」，请手动点「手动发送当前托盘」")
            return
        if not self.controller.plc_connected:
            self._append_log("已勾选自动等待，请先连接 PLC")
            return
        if self.controller.current_plan is None or not self.controller.current_plan.items:
            # 连接瞬间会话可能还没灌进 current_plan，再读一次
            try:
                plan = self.controller.try_load_session_plan()
                if plan is not None:
                    self._refresh_plan_labels(plan)
                    self._append_log(f"自动加载托盘 {plan.source_key}")
            except Exception as exc:  # noqa: BLE001
                self._append_log(f"自动加载托盘失败：{exc}")
        if self.controller.current_plan is None or not self.controller.current_plan.items:
            self._append_log(
                "已连接，但还没有托盘数据：请先 WCS 4.3 选托盘，或点「从会话刷新托盘」"
            )
            return
        if self.controller.is_sending:
            self._append_log("已有下发任务在运行，不再重复启动")
            return
        self._append_log(
            "进入等 PLC 信号下发"
            + ("（连接后）" if source == "connect" else "（刷新托盘后）")
        )
        self.controller.start_pallet_send(self._plc_config(), source="auto")

    def _on_state_path_changed(self, _index: int) -> None:
        path = self.state_path_combo.currentData()
        self.controller.set_state_source(path)
        if path == STATE_PATH_LAYOUT:
            self.state_path_status_label.setText(
                "当前：不接收相机；跳过相机写库，启动前按垛型写 state"
            )
        else:
            self.state_path_status_label.setText(
                "当前：接收相机；写相机尺寸后等待数据库 state"
            )

    def _apply_selected_state_path(self, _checked: bool = False) -> None:
        del _checked
        if self.controller.is_sending:
            message = "PLC 任务运行中，禁止改写当前托盘 state"
            self.state_path_status_label.setText(message)
            self._append_log(message)
            return
        if self.current_state_path() == STATE_PATH_CAMERA:
            message = "已切换接收相机；未改写或清空当前托盘 state"
            self.state_path_status_label.setText(message)
            self._append_log(message)
            return
        try:
            self.controller.apply_layout_state(automatic=False)
        except Exception as exc:  # noqa: BLE001
            message = f"不接收相机（垛型直判）失败：{exc}"
            self.state_path_status_label.setText(message)
            self._append_log(message)

    def _connect_plc(self) -> None:
        if self.controller.plc_connected:
            self.controller.stop_send()
            self.controller.disconnect_plc()
            self.connect_plc_button.setText("连接 PLC")
            return
        try:
            self.controller.connect_plc(self._plc_config())
            self.connect_plc_button.setText("断开 PLC")
            self._try_enter_wait_send(source="connect")
        except PlcLockError as exc:
            QMessageBox.warning(self, "无法连接 PLC", str(exc))
            self._append_log(str(exc))
        except Exception as exc:  # noqa: BLE001
            from .plc_protocol import _format_plc_exc

            self._append_log(f"PLC 连接失败：{_format_plc_exc(exc)}")

    def _on_connection_changed(self, connected: bool, status: str) -> None:
        self.plc_connection_label.setText(status)
        self.connect_plc_button.setText("断开 PLC" if connected else "连接 PLC")

    def _on_sending_changed(self, sending: bool) -> None:
        self.stop_plc_button.setEnabled(sending)
        self.manual_plc_button.setEnabled(not sending)

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        self.controller.stop_send()
        if not self.controller.wait_send_finished(3000):
            self._append_log("PLC 正在安全结束当前握手，请稍后再次关闭")
            event.ignore()
            return
        self.controller.shutdown()
        super().closeEvent(event)


def run(
    *,
    command_file: str | None = None,
    config_path: str | None = None,
    auto_connect: bool = False,
) -> int:
    del command_file  # PLC 窗从会话/DB 读托盘，不轮询三维指令
    app = QApplication.instance() or QApplication([])
    window = PlcControlWindow(
        config_path=config_path,
        auto_connect=auto_connect,
    )
    window.show()
    return app.exec()
