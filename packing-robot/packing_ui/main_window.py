from __future__ import annotations

from collections import defaultdict
import json
from pathlib import Path
from typing import Any, Callable

from PySide6.QtCore import QSignalBlocker, QThread, QTimer, Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from .data import (
    PalletPlan,
    RobotAction,
    action_to_dict,
    build_action,
    filter_plans,
    load_plan_file,
)
from .integration import CameraBoxData, parse_camera_payload
from .live_command import (
    default_command_path,
    default_history_path,
    default_session_path,
    ensure_history_seeded,
    read_live_command,
    read_live_session,
)
from .playback import PlaybackController, PlaybackPanel
from .plc_launcher import launch_plc_ui
from .state_repository import MySqlConfig, ProductState
from .state_sync import StateSyncWorker, load_shared_mysql_config


class PackingMainWindow(QMainWindow):
    def __init__(
        self,
        autoload: bool = True,
        enable_3d: bool = True,
        plc_launcher: Callable[[], Any] = launch_plc_ui,
        state_config_loader: Callable[[], MySqlConfig] = load_shared_mysql_config,
        state_worker_factory: Callable[
            [MySqlConfig, list[ProductState]], StateSyncWorker
        ] = StateSyncWorker,
        command_file: Path | str | None = None,
        initial_plan: Path | str | None = None,
    ) -> None:
        super().__init__()
        self.setWindowTitle("机器人装箱三维仿真系统")
        self.resize(1680, 960)
        self.all_plans: list[PalletPlan] = []
        self.filtered_plans: list[PalletPlan] = []
        self.current_plan: PalletPlan | None = None
        self.actions: list[RobotAction] = []
        self._orientation_by_item: dict[tuple[str, str], int] = {}
        self._camera_by_item: dict[tuple[str, str], CameraBoxData] = {}
        self._enable_3d = enable_3d
        self._plc_launcher = plc_launcher
        self._plc_ui_process: Any | None = None
        self._state_config_loader = state_config_loader
        self._state_worker_factory = state_worker_factory
        self._state_sync_thread: QThread | None = None
        self._state_sync_worker: StateSyncWorker | None = None
        self._close_after_state_sync = False
        self._command_file = Path(command_file) if command_file else default_command_path()
        self._session_file = default_session_path()
        self._history_file = default_history_path()
        self._last_command_id = ""
        self._loaded_plan_path: Path | None = None
        self._live_pallet_uid = ""
        self._wcs_history: list[dict[str, Any]] = []

        self.playback_controller = PlaybackController(self)
        self.playback_panel = PlaybackPanel(self.playback_controller)
        self.playback_controller.frameChanged.connect(self._on_frame)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        splitter.addWidget(self._build_left_panel())
        splitter.addWidget(self._build_center_panel())
        splitter.addWidget(self._build_right_panel())
        splitter.setSizes([360, 1020, 330])
        self.setCentralWidget(splitter)
        self._apply_style()
        self.statusBar().showMessage("等待现场选定托盘（接口3），或手动导入方案 JSON")

        self._command_timer = QTimer(self)
        self._command_timer.setInterval(500)
        self._command_timer.timeout.connect(self._poll_live_command)
        self._command_timer.start()

        # 优先按接口3历史加载（含已完成托盘）；无历史再回退到会话/样例
        try:
            if self.apply_wcs_history():
                pass
            elif initial_plan:
                self.load_path(initial_plan)
            elif autoload:
                samples = sorted(Path.cwd().glob("wcs_plan_map_*.json"))
                if samples:
                    self.load_path(samples[0])
        except Exception as exc:  # noqa: BLE001
            self.statusBar().showMessage(f"加载现场托盘失败：{exc}")
            if initial_plan:
                self.load_path(initial_plan)
            elif autoload:
                samples = sorted(Path.cwd().glob("wcs_plan_map_*.json"))
                if samples:
                    self.load_path(samples[0])

    def _build_left_panel(self) -> QWidget:
        panel = QWidget()
        panel.setObjectName("leftPanel")
        panel.setMinimumWidth(330)
        panel.setMaximumWidth(430)
        outer = QVBoxLayout(panel)
        outer.setContentsMargins(12, 10, 12, 10)

        self.status_combo = QComboBox()
        self.status_combo.addItem("仅成功", "SUCCESS")
        self.status_combo.addItem("全部", "ALL")
        self.status_combo.addItem("仅失败", "FAILED")
        self.status_combo.addItem("未知", "UNKNOWN")
        self.type_combo = QComboBox()
        self.pallet_combo = QComboBox()
        self.order_label = QLabel("—")
        self.orientation_combo = QComboBox()
        self.orientation_combo.addItem("0°", 0)
        self.orientation_combo.addItem("90°", 90)
        self.conveyor_z_spin = QDoubleSpinBox()
        self.conveyor_z_spin.setRange(-5000, 5000)
        self.conveyor_z_spin.setDecimals(1)
        self.conveyor_z_spin.setSuffix(" mm")

        form = QFormLayout()
        form.setVerticalSpacing(10)
        form.addRow("指标状态", self.status_combo)
        form.addRow("托盘类型", self.type_combo)
        form.addRow("托盘", self.pallet_combo)
        form.addRow("订单编号", self.order_label)
        form.addRow("所选箱传送带姿态", self.orientation_combo)
        form.addRow("传送带平面 Z", self.conveyor_z_spin)
        self.selector_group = QGroupBox("托盘选择")
        self.selector_group.setLayout(form)
        outer.addWidget(self.selector_group)

        camera_form = QFormLayout()
        self.camera_status_label = QLabel("等待相机数据")
        self.camera_box_label = QLabel("—")
        self.camera_orientation_label = QLabel("—")
        self.plc_state_label = QLabel("—")
        self.pickup_point_label = QLabel("—")
        camera_form.addRow("相机状态", self.camera_status_label)
        camera_form.addRow("视觉箱子", self.camera_box_label)
        camera_form.addRow("视觉姿态", self.camera_orientation_label)
        camera_form.addRow("PLC旋转状态", self.plc_state_label)
        camera_form.addRow("吸附点", self.pickup_point_label)
        camera_group = QGroupBox("视觉与 PLC")
        camera_group.setLayout(camera_form)
        outer.addWidget(camera_group)

        button_row = QHBoxLayout()
        self.open_button = QPushButton("导入 JSON")
        self.camera_button = QPushButton("导入相机 JSON")
        self.export_button = QPushButton("导出动作")
        button_row.addWidget(self.open_button)
        button_row.addWidget(self.camera_button)
        button_row.addWidget(self.export_button)
        outer.addLayout(button_row)

        outer.addWidget(QLabel("箱子顺序"))
        self.box_list = QListWidget()
        self.box_list.setObjectName("boxList")
        outer.addWidget(self.box_list, 1)

        self.status_combo.currentIndexChanged.connect(self._rebuild_types)
        self.type_combo.currentTextChanged.connect(self._refresh_pallets)
        self.pallet_combo.currentIndexChanged.connect(self._select_current_plan)
        self.orientation_combo.currentIndexChanged.connect(
            self._change_selected_orientation
        )
        self.conveyor_z_spin.valueChanged.connect(self._rebuild_actions)
        self.box_list.currentRowChanged.connect(self._on_box_selected)
        self.open_button.clicked.connect(self.open_file)
        self.camera_button.clicked.connect(self.open_camera_file)
        self.export_button.clicked.connect(self.export_actions)
        return panel

    def _build_plc_group(self) -> QGroupBox:
        layout = QVBoxLayout()
        self.plc_handoff_note = QLabel(
            "state 由数据库交接。\n"
            "请在旧 PLC 界面手动输入 box_unique_id，"
            "由旧界面读取 state 并发送 PLC。"
        )
        self.plc_handoff_note.setWordWrap(True)
        self.plc_ui_status_label = QLabel("未启动")
        self.database_state_label = QLabel("未同步")
        self.open_plc_ui_button = QPushButton("打开 PLC 通讯界面")
        self.open_plc_ui_button.clicked.connect(self._open_plc_ui)
        layout.addWidget(self.plc_handoff_note)
        layout.addWidget(QLabel("数据库 state 状态"))
        layout.addWidget(self.database_state_label)
        layout.addWidget(self.plc_ui_status_label)
        layout.addWidget(self.open_plc_ui_button)
        self.plc_group = QGroupBox("PLC 通讯入口")
        self.plc_group.setLayout(layout)
        return self.plc_group

    def _build_center_panel(self) -> QWidget:
        center = QWidget()
        layout = QVBoxLayout(center)
        layout.setContentsMargins(0, 0, 0, 0)
        if self._enable_3d:
            from .scene import PackingScene

            self.scene = PackingScene()
            self.scene_widget = self.scene
        else:
            self.scene = None
            self.scene_widget = QLabel("三维场景在无显示测试模式下已关闭")
            self.scene_widget.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.scene_widget.setStyleSheet("background:#0e1922;color:#8ca0ae;")
        self.scene_widget.setMinimumSize(680, 500)
        layout.addWidget(self.scene_widget, 1)
        layout.addWidget(self.playback_panel)
        return center

    def _build_right_panel(self) -> QWidget:
        group = QGroupBox("当前信息")
        group.setObjectName("rightPanel")
        group.setMinimumWidth(300)
        group.setMaximumWidth(430)
        self.details = QLabel("请选择托盘")
        self.details.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.details.setWordWrap(True)
        self.details.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout = QVBoxLayout(group)
        layout.addWidget(self.details)
        layout.addStretch(1)
        layout.addWidget(self._build_plc_group())
        hint = QLabel("鼠标操作\n左键：旋转视角\n滚轮：缩放\n中键：平移")
        hint.setObjectName("hint")
        layout.addWidget(hint)
        return group

    def _apply_style(self) -> None:
        self.setFont(QFont("Microsoft YaHei UI", 10))
        self.setStyleSheet(
            """
            QMainWindow, QWidget { background:#151515; color:#eeeeee; }
            #leftPanel, #rightPanel { background:#202020; }
            QGroupBox { border:1px solid #787878; border-radius:6px; margin-top:10px; padding-top:8px; }
            QGroupBox::title { subcontrol-origin:margin; left:10px; padding:0 4px; }
            QComboBox, QDoubleSpinBox { background:#303030; border:1px solid #454545; border-radius:5px; padding:5px 8px; min-height:22px; }
            QComboBox QAbstractItemView { background:#303030; selection-background-color:#16697a; }
            QListWidget { background:#2b2b2b; border:1px solid #363636; border-radius:5px; }
            QListWidget::item { padding:3px 5px; }
            QListWidget::item:selected { background:#176c7d; }
            QPushButton { background:#343434; border:1px solid #505050; border-radius:4px; padding:7px 12px; }
            QPushButton:hover { background:#46545c; }
            QSlider::groove:horizontal { height:5px; background:#8b8b8b; border-radius:2px; }
            QSlider::handle:horizontal { width:14px; margin:-5px 0; background:#37a9da; border-radius:7px; }
            #hint { color:#8fa2ae; border-left:3px solid #2da8d0; padding:8px; }
            QStatusBar { background:#111820; color:#9fb4c2; }
            QSplitter::handle { background:#343434; }
            """
        )

    def open_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "打开装箱结果", str(Path.cwd()), "JSON 文件 (*.json)"
        )
        if path:
            self.load_path(path)

    def load_path(self, path: str | Path) -> None:
        self._wcs_history = []
        if hasattr(self, "selector_group"):
            self.selector_group.setTitle("托盘选择")
        try:
            self.all_plans = load_plan_file(path)
        except ValueError as exc:
            QMessageBox.critical(self, "文件错误", str(exc))
            return
        self._loaded_plan_path = Path(path).resolve()
        self._rebuild_types()
        total_items = sum(len(plan.items) for plan in self.all_plans)
        self.statusBar().showMessage(
            f"已加载 {len(self.all_plans)} 个托盘方案、{total_items} 个箱子：{Path(path).name}"
        )

    def _merge_plans_from_path(self, path: Path) -> None:
        plans = load_plan_file(path)
        by_key = {plan.source_key: plan for plan in self.all_plans}
        for plan in plans:
            by_key[plan.source_key] = plan
        self.all_plans = list(by_key.values())
        self._loaded_plan_path = path.resolve()

    def open_camera_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "打开相机视觉数据", str(Path.cwd()), "JSON 文件 (*.json)"
        )
        if not path:
            return
        try:
            payload = json.loads(Path(path).read_text(encoding="utf-8-sig"))
            count = self.receive_camera_data(payload)
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            self.camera_status_label.setText("错误")
            QMessageBox.critical(self, "相机数据错误", str(exc))
            return
        self.statusBar().showMessage(f"已接收 {count} 条相机箱子数据：{path}")

    def receive_camera_data(self, payload: object) -> int:
        """Validate and bind camera boxes atomically to the current pallet."""
        if self._state_sync_thread is not None:
            raise ValueError("数据库 state 正在同步，请等待完成后再导入相机数据")
        camera_boxes = parse_camera_payload(payload)
        if self.current_plan is None:
            raise ValueError("请先选择托盘方案")
        valid_ids = {item.id for item in self.current_plan.items}
        unknown = [box.box_id for box in camera_boxes if box.box_id not in valid_ids]
        if unknown:
            raise ValueError(f"相机箱子不属于当前托盘：{', '.join(unknown)}")
        updates = {
            self._orientation_key(box.box_id): box for box in camera_boxes
        }
        self._camera_by_item.update(updates)
        self.camera_status_label.setText("已接收")
        self._rebuild_actions(selected_index=max(0, self.box_list.currentRow()))
        actions_by_id = {action.item_id: action for action in self.actions}
        state_updates = [
            ProductState(box.box_id, actions_by_id[box.box_id].rotation_state)
            for box in camera_boxes
        ]
        self._start_state_sync(state_updates)
        return len(camera_boxes)

    def _rebuild_types(self, _index: int | None = None) -> None:
        if self._wcs_history:
            return
        self.filtered_plans = filter_plans(self.all_plans, self.status_combo.currentData())
        grouped: dict[str, list[PalletPlan]] = defaultdict(list)
        for plan in self.filtered_plans:
            grouped[plan.pallet_type].append(plan)
        self._plans_by_type = {
            key: sorted(value, key=lambda plan: plan.pallet_id)
            for key, value in grouped.items()
        }
        blocker = QSignalBlocker(self.type_combo)
        self.type_combo.clear()
        self.type_combo.addItems(sorted(self._plans_by_type))
        del blocker
        self._refresh_pallets(self.type_combo.currentText())

    def _refresh_pallets(self, pallet_type: str) -> None:
        if self._wcs_history:
            return
        blocker = QSignalBlocker(self.pallet_combo)
        self.pallet_combo.clear()
        for plan in self._plans_by_type.get(pallet_type, []):
            self.pallet_combo.addItem(plan.pallet_id, plan)
        del blocker
        self._select_current_plan()

    def _select_current_plan(self, _index: int | None = None) -> None:
        value = self.pallet_combo.currentData()
        self.current_plan = value if isinstance(value, PalletPlan) else None
        self.order_label.setText(self.current_plan.sales_order_no if self.current_plan else "—")
        if self.scene is not None:
            self.scene.set_plan(self.current_plan)
        self._rebuild_actions(selected_index=0)

    def _orientation_key(self, item_id: str) -> tuple[str, str]:
        if self.current_plan is None:
            return "", item_id
        return self.current_plan.source_key, item_id

    def _orientation_for_item(self, item_id: str) -> int:
        return self._orientation_by_item.get(self._orientation_key(item_id), 0)

    def _camera_for_item(self, item_id: str) -> CameraBoxData | None:
        return self._camera_by_item.get(self._orientation_key(item_id))

    def _sync_orientation_combo(self, index: int) -> None:
        if not 0 <= index < len(self.actions):
            return
        combo_index = self.orientation_combo.findData(
            self.actions[index].conveyor_orientation_deg
        )
        if combo_index < 0:
            return
        blocker = QSignalBlocker(self.orientation_combo)
        self.orientation_combo.setCurrentIndex(combo_index)
        del blocker

    def _on_box_selected(self, index: int) -> None:
        if not 0 <= index < len(self.actions):
            return
        self._sync_orientation_combo(index)
        self.playback_controller.seek_step(index)

    def _change_selected_orientation(self, _index: int) -> None:
        if self.current_plan is None or not self.actions:
            return
        row = self.box_list.currentRow()
        if not 0 <= row < len(self.actions):
            return
        action = self.actions[row]
        self._orientation_by_item[self._orientation_key(action.item_id)] = int(
            self.orientation_combo.currentData()
        )
        self._rebuild_actions(selected_index=row)

    def _rebuild_actions(self, *_args, selected_index: int | None = None) -> None:
        if self.current_plan is None:
            self.actions = []
            self.box_list.clear()
            self.playback_controller.set_actions([])
            self.playback_panel.refresh_range()
            self.details.setText("请选择托盘")
            return
        if selected_index is None:
            selected_index = max(0, self.box_list.currentRow())
        conveyor_z = self.conveyor_z_spin.value()
        self.actions = [
            build_action(
                item,
                self._orientation_for_item(item.id),
                conveyor_z,
                camera_data=self._camera_for_item(item.id),
            )
            for item in self.current_plan.items
        ]
        self.box_list.blockSignals(True)
        self.box_list.clear()
        by_id = {item.id: item for item in self.current_plan.items}
        for row, action in enumerate(self.actions, start=1):
            item = by_id[action.item_id]
            source = (
                f"相机{action.conveyor_orientation_deg}°"
                if action.camera_data is not None
                else f"等待相机/预览{action.conveyor_orientation_deg}°"
            )
            self.box_list.addItem(
                f"{row}. {action.item_id}  {item.raw_length:g}x{item.raw_width:g} / "
                f"{source} → {action.target_orientation_deg}° / "
                f"{'转' if action.rotation_state == 2 else '不转'}({action.rotation_state}) / "
                f"{action.pickup_point}"
            )
        self.box_list.blockSignals(False)
        self.playback_controller.set_actions(self.actions)
        self.playback_panel.refresh_range()
        if self.scene is not None:
            self.scene.set_actions(self.actions)
        if self.actions:
            selected_index = min(selected_index, len(self.actions) - 1)
            self.box_list.blockSignals(True)
            self.box_list.setCurrentRow(selected_index)
            self.box_list.blockSignals(False)
            self.playback_controller.seek_step(selected_index)
            self._sync_orientation_combo(selected_index)
            self._on_frame(selected_index, "READY", 0.0)

    def _on_frame(self, index: int, phase: str, fraction: float) -> None:
        if not self.actions or self.current_plan is None:
            return
        index = max(0, min(index, len(self.actions) - 1))
        action = self.actions[index]
        camera = action.camera_data
        self.camera_box_label.setText(camera.box_id if camera else "—")
        self.camera_orientation_label.setText(
            f"{camera.orientation_deg}°" if camera else "—"
        )
        self.plc_state_label.setText(
            "2（旋转90°）" if action.rotation_state == 2 else "1（不旋转）"
        )
        self.pickup_point_label.setText(
            f"{action.pickup_point}（代码{action.pickup_point_code} / {action.box_corner}）"
        )
        self.orientation_combo.setEnabled(camera is None)
        self._sync_orientation_combo(index)
        self.box_list.blockSignals(True)
        self.box_list.setCurrentRow(index)
        self.box_list.scrollToItem(self.box_list.item(index))
        self.box_list.blockSignals(False)
        if self.scene is not None:
            self.scene.show_frame(index, phase, fraction)
        maximum_z = max(
            (item.z + item.height for item in self.current_plan.items), default=0.0
        )
        self.details.setText(
            f"托盘：{self.current_plan.pallet_id}\n"
            f"类型：{self.current_plan.pallet_type}\n"
            f"订单：{self.current_plan.sales_order_no}\n"
            f"箱子数量：{len(self.current_plan.items)}\n"
            f"最高表面：{maximum_z:g} mm\n"
            f"MPM指标：{self.current_plan.mpm_status}\n"
            f"顺序状态：{self.current_plan.sequence_status}\n\n"
            f"当前：{index + 1}/{len(self.actions)}\n"
            f"动画阶段：{phase}  {fraction * 100:.0f}%\n"
            f"箱子：{action.item_id}\n"
            f"抓取 Z：{action.pick_z:g} mm\n"
            f"相机状态：{'已接收' if camera else '等待数据，禁止PLC执行'}\n"
            f"相机坐标："
            f"{f'({camera.x}, {camera.y}, {camera.z}) mm' if camera else '—'}\n"
            f"相机置信度：{camera.confidence if camera and camera.confidence is not None else '—'}\n"
            f"相机时间：{camera.timestamp if camera and camera.timestamp else '—'}\n"
            f"抓取角点：{action.box_corner} ↔ {action.cup_corner}\n"
            f"吸附点：{action.pickup_point}（代码 {action.pickup_point_code}）\n"
            f"PLC旋转状态：{action.rotation_state}"
            f"（{'旋转90°' if action.rotation_state == 2 else '不旋转'}）\n"
            f"放置角点：{action.place_box_corner} ↔ {action.place_cup_corner}\n"
            f"放置 XYZ：({action.box_place[0]:g}, {action.box_place[1]:g}, {action.box_place[2]:g}) mm\n"
            f"吸盘中心：({action.suction_place[0]:g}, {action.suction_place[1]:g}, {action.suction_place[2]:g}) mm\n"
            f"传送带姿态：{action.conveyor_orientation_deg}°\n"
            f"目标姿态：{action.target_orientation_deg}°\n"
            f"旋转角度：{action.rotation_deg}°"
        )

    def export_actions(self) -> None:
        if self.current_plan is None or not self.actions:
            return
        path, _ = QFileDialog.getSaveFileName(
            self,
            "导出机器人动作",
            str(Path.cwd() / f"robot_actions_{self.current_plan.pallet_id}.json"),
            "JSON 文件 (*.json)",
        )
        if not path:
            return
        payload = self.build_export_payload()
        try:
            Path(path).write_text(
                json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except OSError as exc:
            QMessageBox.critical(self, "导出失败", str(exc))
            return
        self.statusBar().showMessage(f"已导出 {len(self.actions)} 条机器人动作：{path}")

    def build_export_payload(self) -> dict[str, object]:
        if self.current_plan is None:
            raise ValueError("当前没有可导出的托盘方案")
        payload = {
            "pallet_id": self.current_plan.pallet_id,
            "mpm_status": self.current_plan.mpm_status,
            "suction_cup_mm": [600, 800],
            "conveyor_orientation_mode": "per_item",
            "conveyor_orientation_by_item": {
                action.item_id: action.conveyor_orientation_deg
                for action in self.actions
            },
            "actions": [action_to_dict(action) for action in self.actions],
            "plc_commands": [
                {
                    "box_id": action.item_id,
                    "seq": action.sequence,
                    "ready": action.plc_ready,
                    "rotation_state": action.rotation_state,
                    "pickup_point": action.pickup_point,
                    "pickup_point_code": action.pickup_point_code,
                    "pickup_z": action.pick_z,
                    "placement_x": action.box_place[0],
                    "placement_y": action.box_place[1],
                    "placement_z": action.box_place[2],
                    "target_orientation_deg": action.target_orientation_deg,
                }
                for action in self.actions
            ],
        }
        return payload

    def _open_plc_ui(self) -> None:
        if self._state_sync_thread is not None:
            self.statusBar().showMessage("数据库 state 正在同步，请等待完成")
            return
        process = self._plc_ui_process
        if process is not None:
            try:
                if process.poll() is None:
                    self.plc_ui_status_label.setText("运行中")
                    self.statusBar().showMessage("旧 PLC 通讯界面已经在运行")
                    return
            except Exception:
                self._plc_ui_process = None
        try:
            self._plc_ui_process = self._plc_launcher()
        except (OSError, RuntimeError) as exc:
            self.plc_ui_status_label.setText("启动失败")
            QMessageBox.critical(self, "无法打开 PLC 通讯界面", str(exc))
            return
        self.plc_ui_status_label.setText("运行中")
        self.statusBar().showMessage(
            "旧 PLC 通讯界面已打开；请在其中输入 box_unique_id"
        )

    def _start_state_sync(self, updates: list[ProductState]) -> None:
        config = self._state_config_loader()
        worker = self._state_worker_factory(config, updates)
        thread = QThread()
        self._state_sync_thread = thread
        self._state_sync_worker = worker
        self.database_state_label.setText("同步中…")
        self.open_plc_ui_button.setEnabled(False)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.succeeded.connect(self._on_state_sync_succeeded)
        worker.failed.connect(self._on_state_sync_failed)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(lambda: self._cleanup_state_sync(thread))
        thread.finished.connect(thread.deleteLater)
        thread.start()

    def _on_state_sync_succeeded(self, count: int) -> None:
        self.database_state_label.setText(f"已同步 {count} 箱")
        self.statusBar().showMessage(
            f"已按 product_code 更新数据库 state：{count} 箱"
        )

    def _on_state_sync_failed(self, message: str) -> None:
        self.database_state_label.setText("同步失败")
        self.statusBar().showMessage(f"数据库 state 同步失败：{message}")

    def _cleanup_state_sync(self, thread: QThread) -> None:
        if self._state_sync_thread is thread:
            self._state_sync_thread = None
            self._state_sync_worker = None
        self.open_plc_ui_button.setEnabled(True)
        if self._close_after_state_sync:
            self._close_after_state_sync = False
            QTimer.singleShot(0, self.close)

    def closeEvent(self, event) -> None:  # noqa: N802
        self.playback_controller.pause()
        if hasattr(self, "_command_timer"):
            self._command_timer.stop()
        if self._state_sync_thread is not None and self._state_sync_thread.isRunning():
            self._close_after_state_sync = True
            event.ignore()
            return
        super().closeEvent(event)

    def _poll_live_command(self) -> None:
        """读取现场指令：load_pallet=整盘加载；play_box=播一箱。"""
        cmd = read_live_command(self._command_file)
        if not cmd:
            return
        cmd_id = str(cmd.get("id") or "").strip()
        if not cmd_id or cmd_id == self._last_command_id:
            return
        action = str(cmd.get("action") or "").strip()
        if action not in {"load_pallet", "play_box"}:
            return
        self._last_command_id = cmd_id
        try:
            if action == "load_pallet":
                self.apply_live_load_pallet(cmd)
            else:
                self.apply_live_play_box(cmd)
        except Exception as exc:  # noqa: BLE001 — 现场指令失败只提示
            self.statusBar().showMessage(f"现场码垛指令失败：{exc}")

    def apply_wcs_history(self, prefer_uid: str = "") -> bool:
        """按接口3历史填充左侧托盘列表（含已完成）。返回是否加载成功。"""
        history = ensure_history_seeded(self._history_file, self._session_file)
        if not history:
            return False
        loaded_any = False
        for entry in history:
            plan_path = entry.get("plan_path")
            if not plan_path:
                continue
            path = Path(str(plan_path))
            if not path.is_file():
                continue
            try:
                self._merge_plans_from_path(path)
                loaded_any = True
            except ValueError:
                continue
        if not loaded_any:
            return False
        self._fill_wcs_history_combo(history, prefer_uid=prefer_uid)
        return self.current_plan is not None or self.pallet_combo.count() > 0

    def _fill_wcs_history_combo(
        self, history: list[dict[str, Any]], prefer_uid: str = ""
    ) -> None:
        self._wcs_history = list(history)
        if hasattr(self, "selector_group"):
            self.selector_group.setTitle("WCS 请求托盘（接口3）")
        plans_by_uid = {plan.source_key: plan for plan in self.all_plans}
        blocker = QSignalBlocker(self.pallet_combo)
        self.pallet_combo.clear()
        # 新的在前，便于看当前盘
        select_index = 0
        found_prefer = False
        found_active = False
        for entry in reversed(history):
            uid = str(entry.get("box_unique_id") or "").strip()
            plan = plans_by_uid.get(uid)
            if plan is None:
                continue
            status = str(entry.get("stack_status") or "active")
            tag = "进行中" if status == "active" else "已完成"
            order = str(
                entry.get("order_id") or plan.sales_order_no or uid[:8] or "—"
            )
            label = f"{order} · {tag}"
            idx = self.pallet_combo.count()
            self.pallet_combo.addItem(label, plan)
            if prefer_uid and uid == prefer_uid:
                select_index = idx
                found_prefer = True
            elif not found_prefer and not found_active and status == "active":
                select_index = idx
                found_active = True
        del blocker
        if self.pallet_combo.count() <= 0:
            return
        self.pallet_combo.setCurrentIndex(select_index)
        self._select_current_plan()

    def select_plan_by_unique_id(self, box_unique_id: str) -> bool:
        uid = str(box_unique_id or "").strip()
        if not uid:
            return False
        if self._wcs_history:
            for i in range(self.pallet_combo.count()):
                data = self.pallet_combo.itemData(i)
                if isinstance(data, PalletPlan) and data.source_key == uid:
                    self.pallet_combo.setCurrentIndex(i)
                    return True
            return False
        for plan in self.all_plans:
            if plan.source_key == uid:
                type_index = self.type_combo.findText(plan.pallet_type)
                if type_index >= 0:
                    self.type_combo.setCurrentIndex(type_index)
                for i in range(self.pallet_combo.count()):
                    data = self.pallet_combo.itemData(i)
                    if isinstance(data, PalletPlan) and data.source_key == uid:
                        self.pallet_combo.setCurrentIndex(i)
                        return True
        return False

    def apply_live_load_pallet(self, cmd: dict[str, Any]) -> None:
        """现场选定托盘后：刷新接口3历史并切到该盘，可直接播放。"""
        prefer_uid = str(cmd.get("box_unique_id") or "").strip()
        # 指令带来的 plan_path 先并入，再刷历史列表
        plan_path = cmd.get("plan_path")
        if plan_path:
            path = Path(str(plan_path))
            if path.is_file():
                try:
                    self._merge_plans_from_path(path)
                except ValueError as exc:
                    raise ValueError(str(exc)) from exc

        if not self.apply_wcs_history(prefer_uid=prefer_uid):
            # 无历史文件时退回单盘加载
            if plan_path:
                path = Path(str(plan_path))
                if path.is_file():
                    self.load_path(path)
            all_idx = self.status_combo.findData("ALL")
            if all_idx >= 0 and self.status_combo.currentData() != "ALL":
                self.status_combo.setCurrentIndex(all_idx)
            if prefer_uid and not self.select_plan_by_unique_id(prefer_uid):
                raise ValueError(f"方案中找不到托盘：{prefer_uid}")

        if prefer_uid and not self.select_plan_by_unique_id(prefer_uid):
            raise ValueError(f"方案中找不到托盘：{prefer_uid}")
        if self.current_plan is None:
            raise ValueError("尚未加载托盘方案")

        self._live_pallet_uid = prefer_uid or self.current_plan.source_key
        order = str(cmd.get("order_id") or self.current_plan.sales_order_no or "")
        n = len(self.current_plan.items)
        hist_n = len(self._wcs_history) if self._wcs_history else 1
        self.setWindowTitle(
            f"现场码垛演示 — 订单 {order or '—'}（共 {n} 箱）"
        )
        self.playback_controller.reset()
        self.box_list.setCurrentRow(0)
        self.statusBar().showMessage(
            f"已加载现场托盘：订单 {order or '—'}，共 {n} 箱；"
            f"左侧共 {hist_n} 盘（接口3历史，含已完成）。"
        )
        if bool(cmd.get("auto_play")):
            self.playback_controller.play()
        self.raise_()
        self.activateWindow()

    def apply_live_play_box(self, cmd: dict[str, Any]) -> None:
        """加载方案（如需）→ 选托盘 → 设相机姿态 → 播放该 seq 一箱。"""
        plan_path = cmd.get("plan_path")
        if plan_path:
            path = Path(str(plan_path))
            if path.is_file() and (
                self._loaded_plan_path is None
                or path.resolve() != self._loaded_plan_path
            ):
                self.load_path(path)

        uid = str(cmd.get("box_unique_id") or "").strip()
        if uid and not self.select_plan_by_unique_id(uid):
            raise ValueError(f"方案中找不到托盘：{uid}")
        if self.current_plan is None:
            raise ValueError("尚未加载托盘方案")

        seq = int(cmd.get("seq") or 0)
        item_id = str(cmd.get("item_id") or "").strip()
        index = -1
        for i, item in enumerate(self.current_plan.items):
            if seq > 0 and int(item.sequence) == seq:
                index = i
                item_id = item.id
                break
            if item_id and item.id == item_id:
                index = i
                break
        if index < 0:
            raise ValueError(f"找不到箱子 seq={seq} item_id={item_id}")

        cam_deg = cmd.get("camera_orientation_deg")
        if cam_deg is None:
            from .data import target_orientation

            target = target_orientation(self.current_plan.items[index])
            state = int(cmd.get("state") or 1)
            # state=1 不转 → 相机=目标；state=2 转 → 相机取另一角
            cam_deg = target if state == 1 else (90 if int(target) == 0 else 0)
        cam_deg = int(cam_deg)
        if cam_deg not in (0, 90):
            cam_deg = 0

        key = self._orientation_key(item_id)
        self._camera_by_item[key] = CameraBoxData(
            box_id=item_id,
            orientation_deg=cam_deg,
        )
        self._orientation_by_item[key] = cam_deg
        # 现场路径：仪表盘已写 state，这里只做可视化，不同步数据库
        self._rebuild_actions(selected_index=index)
        self.box_list.setCurrentRow(index)
        self.playback_controller.play_one_step(index)
        self.statusBar().showMessage(
            f"现场码垛：正在码放第 {seq or index + 1} 箱（{item_id}）"
        )
        self.raise_()
        self.activateWindow()


def run(
    *,
    plan_path: str | Path | None = None,
    command_file: str | Path | None = None,
) -> int:
    app = QApplication.instance() or QApplication([])
    window = PackingMainWindow(
        autoload=plan_path is None,
        initial_plan=plan_path,
        command_file=command_file,
    )
    window.show()
    return app.exec()
