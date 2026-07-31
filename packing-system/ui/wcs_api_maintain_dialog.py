# -*- coding: utf-8 -*-
"""接口维护弹窗：维护 4.7 状态，并可手动发送 4.5 码垛完成。"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from PyQt5 import QtCore, QtWidgets


STATUS_READY = 0
STATUS_BUSY = 1
STATUS_ERROR = 99

_STATUS_TIPS = (
    (STATUS_READY, "0 — 准备就绪（MAX VP 运行中 + 无任务）"),
    (STATUS_BUSY, "1 — 执行中（MAX VP 运行中 + 有任务）"),
    (STATUS_ERROR, "99 — 停止/异常（MAX VP 停止）"),
)


def _packing_system_root(project_dir: Optional[Path]) -> Path:
    if project_dir is not None:
        return Path(project_dir).resolve()
    # ui/wcs_api_maintain_dialog.py → packing-system/
    return Path(__file__).resolve().parents[1]


def _ensure_device_status_import(project_dir: Optional[Path]) -> Any:
    """通过 packing/src 的桥接模块加载设备状态实现。"""
    root = _packing_system_root(project_dir)
    packing_root = (root / "packing").resolve()
    packing_s = str(packing_root)
    bridge_file = packing_root / "src" / "service" / "device_status_store.py"
    if not bridge_file.is_file():
        raise FileNotFoundError(f"找不到 device_status_store 桥接：{bridge_file}")

    sys.path[:] = [p for p in sys.path if p != packing_s]
    sys.path.insert(0, packing_s)

    from src.service import device_status_store as store

    return store


class WcsApiMaintainDialog(QtWidgets.QDialog):
    """维护本地接收端对外回复（重点：接口 4.7 的 status）。"""

    def __init__(
        self,
        parent: Optional[QtWidgets.QWidget] = None,
        *,
        project_dir: Optional[Path] = None,
    ) -> None:
        super().__init__(parent)
        self.project_dir = Path(project_dir) if project_dir else None
        self._latest_arrival: Dict[str, Any] = {}
        self._last_case_data_source = ""
        self.setWindowTitle("接口维护")
        self.setMinimumWidth(680)
        self._build_ui()
        self._load_current_status()
        self._refresh_reqpallet_context()

    def _build_ui(self) -> None:
        root = QtWidgets.QVBoxLayout(self)
        root.setSpacing(12)

        tip = QtWidgets.QLabel(
            "说明：\n"
            "• 本地接收端对外回复统一为 {code, msg, data}。\n"
            "• 4.3 / 4.4 / 4.6 当前固定回成功（code=0），一般不用改。\n"
            "• 4.7 的 data.status 可在此手动设置；也会被 PLC 空闲(KONGXIAN=0)"
            " 与 4.6 托盘到达自动改写。\n"
            "• 4.5 手动发送：pallet_code 可填写或从4.6历史中选择；"
            " box_unique_id 只用于查找箱明细，不会发送给4.5。\n"
            "• 点「确认」后立即写入，对方下次轮询 4.7 即可读到新 status。"
        )
        tip.setWordWrap(True)
        tip.setObjectName("SmallInfo")
        root.addWidget(tip)

        # ---- 4.7 ----
        box47 = QtWidgets.QGroupBox("4.7 获取系统信息（GET /api/status）")
        form47 = QtWidgets.QFormLayout(box47)
        self.lbl_current = QtWidgets.QLabel("—")
        form47.addRow("当前 status：", self.lbl_current)

        self.cmb_status = QtWidgets.QComboBox()
        for value, text in _STATUS_TIPS:
            self.cmb_status.addItem(text, value)
        form47.addRow("设置为：", self.cmb_status)

        hint47 = QtWidgets.QLabel(
            "建议：联调时可先设为 0（就绪）让对方开始推任务；"
            "收到 4.6 后会自动变 1；PLC 偏移12(KONGXIAN)=0 时再自动变回 0。"
        )
        hint47.setWordWrap(True)
        hint47.setObjectName("SmallInfo")
        form47.addRow(hint47)
        root.addWidget(box47)

        # ---- 4.5 手动码垛完成 ----
        box45 = QtWidgets.QGroupBox(
            "4.5 手动发送码垛完成（POST /api/wcs/reqpallet）"
        )
        form45 = QtWidgets.QFormLayout(box45)

        self.txt_45_robot_id = QtWidgets.QLineEdit()
        self.txt_45_station_id = QtWidgets.QLineEdit()
        self.cmb_45_pallet_code = QtWidgets.QComboBox()
        self.cmb_45_pallet_code.setEditable(True)
        self.cmb_45_pallet_code.setInsertPolicy(QtWidgets.QComboBox.NoInsert)
        for widget in (
            self.txt_45_robot_id,
            self.txt_45_station_id,
        ):
            widget.setReadOnly(True)
        form45.addRow("robot_id（4.6）：", self.txt_45_robot_id)
        form45.addRow("station_id（4.6）：", self.txt_45_station_id)
        form45.addRow("pallet_code（可填写/选择）：", self.cmb_45_pallet_code)
        self.cmb_45_pallet_code.currentIndexChanged.connect(
            self._on_pallet_choice_changed
        )

        self.txt_45_box_unique_id = QtWidgets.QLineEdit()
        self.txt_45_box_unique_id.setPlaceholderText(
            "默认取当前执行托盘，也可以手动粘贴 box_unique_id"
        )
        form45.addRow(
            "查case_data的 box_unique_id（不发送）：",
            self.txt_45_box_unique_id,
        )

        self.lbl_45_received_at = QtWidgets.QLabel("尚未收到 4.6")
        form45.addRow("最近 4.6 时间：", self.lbl_45_received_at)

        self.lbl_45_summary = QtWidgets.QLabel(
            "发送时将读取整盘箱明细，并固定发送 empty_flag=false。"
        )
        self.lbl_45_summary.setWordWrap(True)
        self.lbl_45_summary.setObjectName("SmallInfo")
        form45.addRow("请求预览：", self.lbl_45_summary)

        actions45 = QtWidgets.QHBoxLayout()
        self.btn_45_refresh = QtWidgets.QPushButton("刷新4.6和当前托盘")
        self.btn_45_send = QtWidgets.QPushButton("发送4.5码垛完成")
        self.btn_45_refresh.clicked.connect(self._refresh_reqpallet_context)
        self.btn_45_send.clicked.connect(self._on_send_reqpallet)
        actions45.addWidget(self.btn_45_refresh)
        actions45.addStretch(1)
        actions45.addWidget(self.btn_45_send)
        form45.addRow(actions45)
        root.addWidget(box45)

        # ---- 4.3 / 4.4 / 4.6 只读提示 ----
        box_other = QtWidgets.QGroupBox("4.3 / 4.4 / 4.6（一般无需修改）")
        other_layout = QtWidgets.QVBoxLayout(box_other)
        other_layout.addWidget(
            QtWidgets.QLabel(
                "4.3 sendcasetask　→　{ code:0, msg:\"success\", data:{…会话} }\n"
                "4.4 boxarrive　　 →　{ code:0, msg:\"success\", data:{} }\n"
                "4.6 palletarrive　→　{ code:0, msg:\"success\", data:{…} }"
            )
        )
        root.addWidget(box_other)

        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel
        )
        buttons.button(QtWidgets.QDialogButtonBox.Ok).setText("确认")
        buttons.button(QtWidgets.QDialogButtonBox.Cancel).setText("取消")
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def _load_current_status(self) -> None:
        status = STATUS_READY
        try:
            store = _ensure_device_status_import(self.project_dir)
            status = int(store.read_device_status(default=STATUS_READY))
        except Exception:
            status = STATUS_READY

        label = {0: "0 就绪", 1: "1 执行中", 99: "99 停止/异常"}.get(
            status, str(status)
        )
        self.lbl_current.setText(label)
        idx = self.cmb_status.findData(status)
        if idx < 0:
            idx = self.cmb_status.findData(STATUS_READY)
        if idx >= 0:
            self.cmb_status.setCurrentIndex(idx)

    def _on_accept(self) -> None:
        value = self.cmb_status.currentData()
        try:
            status = int(value)
        except (TypeError, ValueError):
            QtWidgets.QMessageBox.warning(self, "接口维护", "请选择有效的 status。")
            return
        try:
            store = _ensure_device_status_import(self.project_dir)
            store.write_device_status(status, source="ui_api_maintain")
        except Exception as exc:
            QtWidgets.QMessageBox.critical(
                self, "接口维护", f"写入 status 失败：{exc}"
            )
            return
        QtWidgets.QMessageBox.information(
            self,
            "接口维护",
            f"已更新 4.7 data.status = {status}\n对方下次 GET /api/status 即可读到。",
        )
        self.accept()

    def _refresh_reqpallet_context(self) -> None:
        try:
            _ensure_device_status_import(self.project_dir)
            from src.service.pallet_arrival_store import (
                list_recent_pallet_arrivals,
                read_latest_pallet_arrival,
                workspace_root,
            )

            receiver_logs = (
                _packing_system_root(self.project_dir)
                / "local_wcs_receiver"
                / "logs"
            )
            self._latest_arrival = read_latest_pallet_arrival(
                legacy_log_dir=receiver_logs
            )
            arrival_choices = list_recent_pallet_arrivals(
                legacy_log_dir=receiver_logs
            )
            runtime = workspace_root() / "runtime"
            command_path = runtime / "live_stack_command.json"
            command: Dict[str, Any] = {}
            if command_path.is_file():
                try:
                    loaded = json.loads(
                        command_path.read_text(encoding="utf-8-sig")
                    )
                    if isinstance(loaded, dict):
                        command = loaded
                except (OSError, ValueError, TypeError):
                    command = {}
        except Exception as exc:
            self._latest_arrival = {}
            arrival_choices = []
            command = {}
            self.lbl_45_summary.setText(f"读取4.6/当前托盘失败：{exc}")

        arrival = self._latest_arrival
        self.cmb_45_pallet_code.blockSignals(True)
        self.cmb_45_pallet_code.clear()
        for item in arrival_choices:
            pallet_code = str(item.get("pallet_code") or "").strip()
            if pallet_code:
                self.cmb_45_pallet_code.addItem(pallet_code, dict(item))
        self.cmb_45_pallet_code.setCurrentText(
            str(arrival.get("pallet_code") or "")
        )
        self.cmb_45_pallet_code.blockSignals(False)
        self.txt_45_robot_id.setText(str(arrival.get("robot_id") or ""))
        self.txt_45_station_id.setText(str(arrival.get("station_id") or ""))
        self.lbl_45_received_at.setText(
            str(arrival.get("received_at") or "尚未收到 4.6")
        )
        current_uid = str(command.get("box_unique_id") or "").strip()
        if current_uid:
            self.txt_45_box_unique_id.setText(current_uid)

    def _on_pallet_choice_changed(self, index: int) -> None:
        selected = self.cmb_45_pallet_code.itemData(index)
        if not isinstance(selected, dict):
            return
        self._latest_arrival = dict(selected)
        self.txt_45_robot_id.setText(str(selected.get("robot_id") or ""))
        self.txt_45_station_id.setText(str(selected.get("station_id") or ""))
        self.lbl_45_received_at.setText(
            str(selected.get("received_at") or "未知")
        )

    def _config_path(self) -> Path:
        return _packing_system_root(self.project_dir) / "config" / "packing_config.yaml"

    def _load_wcs_case(self, box_unique_id: str) -> Dict[str, Any]:
        _ensure_device_status_import(self.project_dir)
        from src.service.success_box_db import get_success_box_repo

        try:
            repo = get_success_box_repo(config_path=self._config_path())
            cases = repo.build_wcs_cases_for_unique_ids([box_unique_id])
            if len(cases) != 1:
                raise ValueError(f"未能读取整盘箱明细：{box_unique_id}")
            self._last_case_data_source = "数据库 wcs_success_box"
            return cases[0]
        except Exception:
            from src.service.pallet_arrival_store import workspace_root
            from src.service.wcs_case_archive import find_wcs_case_in_archives

            case, path = find_wcs_case_in_archives(
                box_unique_id,
                workspace=workspace_root(),
            )
            self._last_case_data_source = f"历史文件 {path.name}"
            return case

    def _load_data_source(self):
        _ensure_device_status_import(self.project_dir)
        from src.service.wcs_service import load_data_source_config

        return load_data_source_config(self._config_path())

    def _build_reqpallet_payload(
        self,
        arrival: Dict[str, Any],
        wcs_case: Dict[str, Any],
    ) -> Dict[str, Any]:
        _ensure_device_status_import(self.project_dir)
        from src.service.wcs_service import build_reqpallet_payload

        return build_reqpallet_payload(
            arrival,
            wcs_case,
            empty_flag=False,
        )

    def _send_reqpallet(self, ds, payload: Dict[str, Any]) -> Dict[str, Any]:
        _ensure_device_status_import(self.project_dir)
        from src.service.wcs_service import push_reqpallet

        return push_reqpallet(
            ds.effective_api_base_url,
            payload,
            ds.reqpallet_path,
        )

    def _save_reqpallet_snapshot(
        self,
        payload: Dict[str, Any],
        box_unique_id: str,
    ) -> Path:
        _ensure_device_status_import(self.project_dir)
        from src.service.pallet_arrival_store import workspace_root

        out_dir = workspace_root() / "output" / "success"
        out_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        short_uid = str(box_unique_id)[-8:] or "unknown"
        path = out_dir / f"wcs_reqpallet_45_{stamp}_{short_uid}.json"
        snapshot = {
            "box_unique_id_source": str(box_unique_id),
            "request": payload,
        }
        path.write_text(
            json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return path

    def _confirm_reqpallet(
        self,
        *,
        box_unique_id: str,
        pallet_code: str,
        url: str,
        layer_count: int,
        carton_count: int,
    ) -> bool:
        answer = QtWidgets.QMessageBox.question(
            self,
            "确认发送4.5",
            "请确认以下人工关联：\n\n"
            f"发送 pallet_code：{pallet_code}\n"
            f"查箱明细 UID（不发送）：{box_unique_id}\n"
            f"明细：{layer_count} 层 / {carton_count} 箱\n"
            "empty_flag：false\n"
            f"目标：{url}\n\n"
            "确认向 WCS 发送码垛完成吗？",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
            QtWidgets.QMessageBox.No,
        )
        return answer == QtWidgets.QMessageBox.Yes

    def _on_send_reqpallet(self) -> None:
        uid = self.txt_45_box_unique_id.text().strip()
        arrival = {
            **self._latest_arrival,
            "robot_id": self.txt_45_robot_id.text().strip(),
            "station_id": self.txt_45_station_id.text().strip(),
            "pallet_code": self.cmb_45_pallet_code.currentText().strip(),
        }
        if not uid:
            QtWidgets.QMessageBox.warning(
                self, "发送4.5", "当前没有 box_unique_id，请先输入或刷新。"
            )
            return
        try:
            wcs_case = self._load_wcs_case(uid)
            payload = self._build_reqpallet_payload(arrival, wcs_case)
            ds = self._load_data_source()
            cases = payload.get("case_data") or []
            layers = [
                layer
                for case in cases
                for layer in (case.get("layers") or [])
            ]
            carton_count = sum(
                len(layer.get("cartons") or []) for layer in layers
            )
            summary = (
                f"{len(layers)} 层 / {carton_count} 箱；"
                f"case_type={payload.get('case_type')}; empty_flag=false；"
                f"来源={self._last_case_data_source or '当前箱明细'}"
            )
            self.lbl_45_summary.setText(summary)
            if not self._confirm_reqpallet(
                box_unique_id=uid,
                pallet_code=str(payload.get("pallet_code") or ""),
                url=ds.reqpallet_url(),
                layer_count=len(layers),
                carton_count=carton_count,
            ):
                return
            snapshot_path = self._save_reqpallet_snapshot(payload, uid)
            self.btn_45_send.setEnabled(False)
            QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.WaitCursor)
            try:
                response = self._send_reqpallet(ds, payload)
            finally:
                QtWidgets.QApplication.restoreOverrideCursor()
                self.btn_45_send.setEnabled(True)
        except Exception as exc:
            QtWidgets.QMessageBox.critical(
                self, "发送4.5失败", f"未发送成功：{exc}"
            )
            return

        QtWidgets.QMessageBox.information(
            self,
            "4.5发送成功",
            f"{summary}\n"
            f"WCS返回 code={response.get('code')}, msg={response.get('msg')}\n"
            f"请求快照：{snapshot_path}",
        )
