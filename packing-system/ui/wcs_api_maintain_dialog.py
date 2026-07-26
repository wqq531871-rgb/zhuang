# -*- coding: utf-8 -*-
"""接口维护弹窗：以 4.7 data.status 为主，4.3～4.6 仅提示默认回复。"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Optional

from PyQt5 import QtWidgets


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
        self.setWindowTitle("接口维护")
        self.setMinimumWidth(520)
        self._build_ui()
        self._load_current_status()

    def _build_ui(self) -> None:
        root = QtWidgets.QVBoxLayout(self)
        root.setSpacing(12)

        tip = QtWidgets.QLabel(
            "说明：\n"
            "• 本地接收端对外回复统一为 {code, msg, data}。\n"
            "• 4.3 / 4.4 / 4.6 当前固定回成功（code=0），一般不用改。\n"
            "• 4.7 的 data.status 可在此手动设置；也会被 PLC 空闲(KONGXIAN=0)"
            " 与 4.6 托盘到达自动改写。\n"
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
