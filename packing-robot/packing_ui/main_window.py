"""现场码垛三维演示：按接口3 box_unique_id 从 MySQL 加载，不导入外部 JSON。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from PySide6.QtCore import QSignalBlocker, QTimer, Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QLabel,
    QListWidget,
    QMainWindow,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from .data import PackedItem, PalletPlan, build_action, load_plan_file, target_orientation
from .integration import CameraBoxData
from .layout_state import STATE_PATH_LAYOUT
from .live_command import (
    default_command_path,
    default_history_path,
    default_session_path,
    ensure_history_seeded,
    read_live_command,
    read_live_session,
)
from .plan_from_db import load_plan_from_db
from .playback import PlaybackController, PlaybackPanel


class PackingMainWindow(QMainWindow):
    def __init__(
        self,
        *,
        command_file: str | None = None,
        config_path: str | None = None,
        autoload: bool = True,
        enable_3d: bool = True,
        **_ignored,
    ) -> None:
        super().__init__()
        self.setWindowTitle("现场码垛演示")
        self.resize(1680, 960)
        self.all_plans: list[PalletPlan] = []
        self.filtered_plans: list[PalletPlan] = []
        self.current_plan: PalletPlan | None = None
        self.actions: list = []
        self._orientation_by_item: dict[tuple[str, str], int] = {}
        self._camera_by_item: dict[tuple[str, str], CameraBoxData] = {}
        self._command_file = Path(command_file) if command_file else default_command_path()
        self._session_file = default_session_path()
        self._history_file = default_history_path()
        self._config_path = Path(config_path) if config_path else None
        self._last_command_id = ""
        self._wcs_history: list[dict[str, Any]] = []
        self._live_pallet_uid = ""
        self._enable_3d = enable_3d
        self.scene = None
        self._state_sync_thread = None  # 兼容旧测试

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
        self.statusBar().showMessage("等待 WCS 选定托盘（接口3）…")

        self._command_timer = QTimer(self)
        self._command_timer.setInterval(500)
        self._command_timer.timeout.connect(self._poll_live_command)
        self._command_timer.start()

        if not autoload:
            return
        try:
            if not self.apply_wcs_history():
                session = read_live_session(self._session_file)
                uid = str((session or {}).get("box_unique_id") or "").strip()
                if uid:
                    self.apply_live_load_pallet(
                        {
                            "box_unique_id": uid,
                            "order_id": (session or {}).get("order_id"),
                            "auto_play": False,
                        }
                    )
        except Exception as exc:  # noqa: BLE001
            self.statusBar().showMessage(f"加载现场托盘失败：{exc}")

    def _build_left_panel(self) -> QWidget:
        panel = QWidget()
        panel.setObjectName("leftPanel")
        panel.setMinimumWidth(330)
        panel.setMaximumWidth(430)
        outer = QVBoxLayout(panel)
        outer.setContentsMargins(12, 10, 12, 10)

        self.pallet_combo = QComboBox()
        self.order_label = QLabel("—")
        self.type_label = QLabel("—")
        self.orientation_combo = QComboBox()
        self.orientation_combo.addItem("0°", 0)
        self.orientation_combo.addItem("90°", 90)
        self.conveyor_z_spin = QDoubleSpinBox()
        self.conveyor_z_spin.setRange(-5000, 5000)
        self.conveyor_z_spin.setDecimals(1)
        self.conveyor_z_spin.setSuffix(" mm")

        form = QFormLayout()
        form.setVerticalSpacing(10)
        form.addRow("托盘", self.pallet_combo)
        form.addRow("托盘id", self.order_label)
        form.addRow("托盘类型", self.type_label)
        form.addRow("所选箱传送带姿态", self.orientation_combo)
        form.addRow("传送带平面 Z", self.conveyor_z_spin)
        self.selector_group = QGroupBox("托盘选择")
        self.selector_group.setLayout(form)
        outer.addWidget(self.selector_group)

        outer.addWidget(QLabel("箱子顺序"))
        self.box_list = QListWidget()
        self.box_list.setObjectName("boxList")
        outer.addWidget(self.box_list, 1)

        self.pallet_combo.currentIndexChanged.connect(self._select_current_plan)
        self.orientation_combo.currentIndexChanged.connect(
            self._change_selected_orientation
        )
        self.conveyor_z_spin.valueChanged.connect(self._rebuild_actions)
        self.box_list.currentRowChanged.connect(self._on_box_selected)
        return panel

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
        self.details = QLabel("等待选定托盘")
        self.details.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.details.setWordWrap(True)
        self.details.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        layout = QVBoxLayout(group)
        layout.addWidget(self.details)
        layout.addStretch(1)
        hint = QLabel(
            "鼠标操作\n左键：旋转视角\n滚轮：缩放\n中键：平移\n\n"
            "PLC 通讯请在控序界面点「连接 PLC」打开独立窗口。"
        )
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

    def _load_plan_for_uid(self, box_unique_id: str) -> PalletPlan:
        return load_plan_from_db(box_unique_id, config_path=self._config_path)

    def load_path(self, path: str | Path) -> None:
        """测试/调试：仍可从 JSON 灌入方案；正式界面不提供导入按钮。"""
        self._wcs_history = []
        try:
            self.all_plans = load_plan_file(path)
        except ValueError as exc:
            from PySide6.QtWidgets import QMessageBox

            QMessageBox.critical(self, "文件错误", str(exc))
            return
        self.filtered_plans = list(self.all_plans)
        blocker = QSignalBlocker(self.pallet_combo)
        self.pallet_combo.clear()
        for plan in self.all_plans:
            self.pallet_combo.addItem(plan.source_key, plan)
        del blocker
        if self.pallet_combo.count() > 0:
            self.pallet_combo.setCurrentIndex(0)
            self._select_current_plan()
        self.statusBar().showMessage(
            f"[调试] 已加载 JSON：{Path(path).name}，{len(self.all_plans)} 盘"
        )

    def apply_wcs_history(self, prefer_uid: str = "") -> bool:
        history = ensure_history_seeded(self._history_file, self._session_file)
        if not history:
            return False
        plans: list[PalletPlan] = []
        kept_history: list[dict[str, Any]] = []
        for entry in history:
            uid = str(entry.get("box_unique_id") or "").strip()
            if not uid:
                continue
            try:
                plan = self._load_plan_for_uid(uid)
            except Exception:
                continue
            plans.append(plan)
            kept_history.append(entry)
        if not plans:
            return False
        self.all_plans = plans
        self._fill_wcs_history_combo(kept_history, prefer_uid=prefer_uid)
        return self.current_plan is not None or self.pallet_combo.count() > 0

    def _fill_wcs_history_combo(
        self, history: list[dict[str, Any]], prefer_uid: str = ""
    ) -> None:
        self._wcs_history = list(history)
        plans_by_uid = {plan.source_key: plan for plan in self.all_plans}
        blocker = QSignalBlocker(self.pallet_combo)
        self.pallet_combo.clear()
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
                entry.get("order_id") or plan.sales_order_no or ""
            ).strip()
            # 下拉显示订单号，不显示自生成的 box_unique_id
            label = order if order and order != uid else (uid[:8] + "…" if uid else "—")
            idx = self.pallet_combo.count()
            self.pallet_combo.addItem(f"{label} · {tag}", plan)
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

    def _select_current_plan(self, _index: int | None = None) -> None:
        value = self.pallet_combo.currentData()
        self.current_plan = value if isinstance(value, PalletPlan) else None
        if self.current_plan is None:
            self.order_label.setText("—")
            self.type_label.setText("—")
            if self.scene is not None:
                self.scene.set_plan(None)
            self._rebuild_actions(selected_index=0)
            return
        self.order_label.setText(self.current_plan.sales_order_no or "—")
        self.type_label.setText(self.current_plan.pallet_type or "—")
        self._live_pallet_uid = self.current_plan.source_key
        for item in self.current_plan.items:
            key = self._orientation_key(item.id)
            if key not in self._orientation_by_item:
                deg = int(item.original.get("target_orientation_deg") or 0)
                if deg not in (0, 90):
                    deg = target_orientation(item)
                self._orientation_by_item[key] = deg
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
            self.details.setText("等待选定托盘")
            return
        if selected_index is None:
            selected_index = max(0, self.box_list.currentRow())
        conveyor_z = self.conveyor_z_spin.value()
        # 三维仅展示：有 DB state 即可上传送带（不强制相机尺寸）
        self.actions = [
            build_action(
                item,
                self._orientation_for_item(item.id),
                conveyor_z,
                camera_data=self._camera_for_item(item.id),
                state_source=STATE_PATH_LAYOUT,
            )
            for item in self.current_plan.items
        ]
        self.box_list.blockSignals(True)
        self.box_list.clear()
        by_id = {item.id: item for item in self.current_plan.items}
        for row, action in enumerate(self.actions, start=1):
            item = by_id[action.item_id]
            rot_txt = {
                0: "异型",
                1: "不转",
                2: "转",
            }.get(int(action.rotation_state), "?")
            ready_txt = "已就绪" if action.show_on_conveyor else "待判态"
            self.box_list.addItem(
                f"{row}. seq={action.sequence}  {item.raw_length:g}×{item.raw_width:g}×"
                f"{item.raw_height:g}  目标{action.target_orientation_deg}° / "
                f"{rot_txt} / {ready_txt}"
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
        if self.scene is not None:
            self.scene.show_frame(index, phase, fraction)
        self.box_list.blockSignals(True)
        self.box_list.setCurrentRow(index)
        self.box_list.scrollToItem(self.box_list.item(index))
        self.box_list.blockSignals(False)
        self._sync_orientation_combo(index)
        maximum_z = max(
            (item.z + item.height for item in self.current_plan.items), default=0.0
        )
        self.details.setText(
            f"托盘 uid：{self.current_plan.source_key}\n"
            f"托盘编号：{self.current_plan.pallet_id}\n"
            f"类型：{self.current_plan.pallet_type}\n"
            f"订单：{self.current_plan.sales_order_no}\n"
            f"箱子数量：{len(self.current_plan.items)}\n"
            f"最高表面：{maximum_z:g} mm\n\n"
            f"当前：{index + 1}/{len(self.actions)}\n"
            f"动画阶段：{phase}  {fraction * 100:.0f}%\n"
            f"箱子：{action.item_id}（seq={action.sequence}）\n"
            f"放置 XYZ：({action.box_place[0]:g}, {action.box_place[1]:g}, {action.box_place[2]:g}) mm\n"
            f"目标姿态：{action.target_orientation_deg}°\n"
            f"预览旋转：{action.rotation_state}"
            f"（{'旋转90°' if action.rotation_state == 2 else '不旋转'}）"
        )

    def closeEvent(self, event) -> None:  # noqa: N802
        self.playback_controller.pause()
        if hasattr(self, "_command_timer"):
            self._command_timer.stop()
        super().closeEvent(event)

    def _poll_live_command(self) -> None:
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
        except Exception as exc:  # noqa: BLE001
            self.statusBar().showMessage(f"现场码垛指令失败：{exc}")

    def select_plan_by_unique_id(self, box_unique_id: str) -> bool:
        uid = str(box_unique_id or "").strip()
        if not uid:
            return False
        for i in range(self.pallet_combo.count()):
            data = self.pallet_combo.itemData(i)
            if isinstance(data, PalletPlan) and data.source_key == uid:
                self.pallet_combo.setCurrentIndex(i)
                return True
        return False

    def apply_live_load_pallet(self, cmd: dict[str, Any]) -> None:
        prefer_uid = str(cmd.get("box_unique_id") or "").strip()
        if not prefer_uid:
            raise ValueError("指令缺少 box_unique_id")
        try:
            plan = self._load_plan_for_uid(prefer_uid)
        except Exception as exc:
            raise ValueError(f"库中找不到托盘 {prefer_uid}：{exc}") from exc
        by_key = {p.source_key: p for p in self.all_plans}
        by_key[plan.source_key] = plan
        self.all_plans = list(by_key.values())

        if not self.apply_wcs_history(prefer_uid=prefer_uid):
            blocker = QSignalBlocker(self.pallet_combo)
            self.pallet_combo.clear()
            self.pallet_combo.addItem(f"{prefer_uid} · 进行中", plan)
            del blocker
            self.pallet_combo.setCurrentIndex(0)
            self._select_current_plan()
        elif not self.select_plan_by_unique_id(prefer_uid):
            blocker = QSignalBlocker(self.pallet_combo)
            self.pallet_combo.insertItem(0, f"{prefer_uid} · 进行中", plan)
            del blocker
            self.pallet_combo.setCurrentIndex(0)
            self._select_current_plan()

        if self.current_plan is None:
            raise ValueError("尚未加载托盘方案")
        self._live_pallet_uid = prefer_uid
        order = str(cmd.get("order_id") or self.current_plan.sales_order_no or "")
        n = len(self.current_plan.items)
        self.setWindowTitle(f"现场码垛演示 — 订单 {order or '—'}（共 {n} 箱）")
        self.playback_controller.reset()
        self.box_list.setCurrentRow(0)
        self.statusBar().showMessage(
            f"已从数据库加载托盘：订单 {order or '—'}，共 {n} 箱（uid={prefer_uid[:8]}…）"
        )
        if bool(cmd.get("auto_play")):
            self.playback_controller.play()
        self.raise_()
        self.activateWindow()

    def apply_live_play_box(self, cmd: dict[str, Any]) -> None:
        uid = str(cmd.get("box_unique_id") or "").strip()
        if uid and (
            self.current_plan is None or self.current_plan.source_key != uid
        ):
            self.apply_live_load_pallet(
                {
                    "box_unique_id": uid,
                    "order_id": cmd.get("order_id"),
                    "auto_play": False,
                }
            )
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

        item = self.current_plan.items[index]
        original = dict(item.original or {})
        for key in ("camera_length", "camera_width", "camera_height"):
            if cmd.get(key) is not None:
                try:
                    original[key] = float(cmd.get(key))
                except (TypeError, ValueError):
                    pass
        if cmd.get("state") is not None:
            try:
                original["state"] = int(cmd.get("state"))
            except (TypeError, ValueError):
                pass
        updated = PackedItem(
            id=item.id,
            box_type=item.box_type,
            length=item.length,
            width=item.width,
            height=item.height,
            raw_length=item.raw_length,
            raw_width=item.raw_width,
            raw_height=item.raw_height,
            x=item.x,
            y=item.y,
            z=item.z,
            box_corner=item.box_corner,
            cup_corner=item.cup_corner,
            suction_orientation=item.suction_orientation,
            cup_x_size=item.cup_x_size,
            cup_y_size=item.cup_y_size,
            suction_x_min=item.suction_x_min,
            suction_x_max=item.suction_x_max,
            suction_y_min=item.suction_y_min,
            suction_y_max=item.suction_y_max,
            sequence=item.sequence,
            sequence_source=item.sequence_source,
            original=original,
        )
        items = list(self.current_plan.items)
        items[index] = updated
        self.current_plan = PalletPlan(
            source_key=self.current_plan.source_key,
            pallet_id=self.current_plan.pallet_id,
            pallet_type=self.current_plan.pallet_type,
            sales_order_no=self.current_plan.sales_order_no,
            mpm_status=self.current_plan.mpm_status,
            sequence_status=self.current_plan.sequence_status,
            robot_verified=self.current_plan.robot_verified,
            pallet_length=self.current_plan.pallet_length,
            pallet_width=self.current_plan.pallet_width,
            pallet_height=self.current_plan.pallet_height,
            items=tuple(items),
            original=self.current_plan.original,
        )

        state = original.get("state")
        try:
            state_i = int(state) if state is not None else None
        except (TypeError, ValueError):
            state_i = None
        target = target_orientation(updated)
        if state_i == 1:
            cam_deg = target
        elif state_i == 2:
            cam_deg = 90 if int(target) == 0 else 0
        else:
            cam_deg = cmd.get("camera_orientation_deg")
            if cam_deg is None:
                cam_deg = target
            cam_deg = int(cam_deg)
            if cam_deg not in (0, 90):
                cam_deg = 0

        key = self._orientation_key(item_id)
        self._camera_by_item[key] = CameraBoxData(
            box_id=item_id,
            orientation_deg=int(cam_deg),
        )
        self._orientation_by_item[key] = int(cam_deg)
        self._rebuild_actions(selected_index=index)
        self.box_list.setCurrentRow(index)

        auto_play = bool(cmd.get("auto_play", True)) and state_i in (1, 2)
        if auto_play:
            self.playback_controller.play_one_step(index)
            msg = f"现场码垛：正在码放第 {seq or index + 1} 箱（{item_id}）"
        elif state_i == 0:
            self.playback_controller.seek_step(index)
            msg = f"异型箱 seq={seq}：已显示在传送带，不自动装载"
        else:
            self.playback_controller.seek_step(index)
            msg = f"现场码垛：第 {seq or index + 1} 箱数据未完整，传送带不生成"
        self.statusBar().showMessage(msg)
        self.raise_()
        self.activateWindow()


def run(
    *,
    plan_path: str | None = None,  # 兼容旧参数，已忽略
    command_file: str | None = None,
    config_path: str | None = None,
) -> int:
    del plan_path
    app = QApplication.instance() or QApplication([])
    window = PackingMainWindow(command_file=command_file, config_path=config_path)
    window.show()
    return app.exec()
