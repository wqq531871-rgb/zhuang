# -*- coding: utf-8 -*-
"""下传 WCS：多选达标托盘弹窗（数据来自 wcs_success_box 未下传盘）。"""

from __future__ import annotations

from typing import List, Optional, Sequence

from PyQt5 import QtCore, QtWidgets


class WcsPushPalletDialog(QtWidgets.QDialog):
    """选择一个或多个未下传达标托盘；返回勾选顺序的 box_unique_id 列表。"""

    def __init__(
        self,
        parent=None,
        *,
        pallets: Optional[Sequence[dict]] = None,
    ):
        super().__init__(parent)
        self.setWindowTitle("下传 WCS")
        self.setModal(True)
        self.resize(560, 440)
        self._selected_unique_ids: List[str] = []

        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(10)

        title = QtWidgets.QLabel("选择要下传的达标托盘（仅未下传）")
        title.setObjectName("DialogTitle")
        root.addWidget(title)

        hint = QtWidgets.QLabel(
            "列表来自数据库全库未下传记录。可多选；每个托盘整盘下传（含全部箱子）。"
            "默认不勾选，可随时取消。"
        )
        hint.setObjectName("SmallInfo")
        hint.setWordWrap(True)
        root.addWidget(hint)

        src = QtWidgets.QLabel("数据来源：数据库 wcs_success_box（is_send=未下传）")
        src.setObjectName("SmallInfo")
        src.setWordWrap(True)
        root.addWidget(src)

        box = QtWidgets.QFrame()
        box.setObjectName("ParamBox")
        box_layout = QtWidgets.QVBoxLayout(box)
        box_layout.setContentsMargins(10, 10, 10, 10)
        box_layout.setSpacing(8)

        tools = QtWidgets.QHBoxLayout()
        self.btn_select_all = QtWidgets.QPushButton("全选")
        self.btn_clear = QtWidgets.QPushButton("清空")
        self.btn_select_all.clicked.connect(self._select_all)
        self.btn_clear.clicked.connect(self._clear_all)
        tools.addWidget(self.btn_select_all)
        tools.addWidget(self.btn_clear)
        tools.addStretch(1)
        self.lbl_count = QtWidgets.QLabel("已选 0 盘")
        self.lbl_count.setObjectName("SmallInfo")
        tools.addWidget(self.lbl_count)
        box_layout.addLayout(tools)

        self.list_widget = QtWidgets.QListWidget()
        self.list_widget.setSelectionMode(QtWidgets.QAbstractItemView.NoSelection)
        self.list_widget.itemChanged.connect(self._on_item_changed)
        box_layout.addWidget(self.list_widget, 1)
        root.addWidget(box, 1)

        buttons = QtWidgets.QHBoxLayout()
        buttons.addStretch(1)
        self.btn_cancel = QtWidgets.QPushButton("取消")
        self.btn_cancel.clicked.connect(self.reject)
        self.btn_push = QtWidgets.QPushButton("下传所选…")
        self.btn_push.setObjectName("PrimaryButton")
        self.btn_push.setEnabled(False)
        self.btn_push.clicked.connect(self._on_push_clicked)
        buttons.addWidget(self.btn_cancel)
        buttons.addWidget(self.btn_push)
        root.addLayout(buttons)

        self._populate(pallets or [])

    def selected_box_unique_ids(self) -> List[str]:
        return list(self._selected_unique_ids)

    # 兼容旧调用名
    def selected_pallet_ids(self) -> List[str]:
        return self.selected_box_unique_ids()

    def _populate(self, pallets: Sequence[dict]) -> None:
        self.list_widget.blockSignals(True)
        self.list_widget.clear()
        for pallet in pallets:
            uid = str(pallet.get("box_unique_id") or "").strip()
            if not uid:
                continue
            pid = str(pallet.get("pallet_id") or "").strip() or "-"
            order_id = str(pallet.get("order_id") or "").strip() or "-"
            case_type = str(pallet.get("case_type") or "").strip() or "-"
            box_n = int(pallet.get("box_count") or 0)
            short_uid = uid if len(uid) <= 10 else f"{uid[:8]}…"
            text = (
                f"{pid}  ·  订单 {order_id}  ·  {case_type}  ·  "
                f"{box_n} 箱  ·  {short_uid}"
            )
            item = QtWidgets.QListWidgetItem(text)
            item.setFlags(
                item.flags()
                | QtCore.Qt.ItemIsUserCheckable
                | QtCore.Qt.ItemIsEnabled
            )
            item.setCheckState(QtCore.Qt.Unchecked)
            item.setData(QtCore.Qt.UserRole, uid)
            item.setToolTip(f"box_unique_id={uid}")
            self.list_widget.addItem(item)
        self.list_widget.blockSignals(False)
        self._refresh_count()
        if self.list_widget.count() == 0:
            self.btn_select_all.setEnabled(False)
            self.btn_clear.setEnabled(False)
            empty = QtWidgets.QListWidgetItem("当前没有未下传的达标托盘")
            empty.setFlags(QtCore.Qt.NoItemFlags)
            self.list_widget.addItem(empty)

    def _checked_ids_in_order(self) -> List[str]:
        ids: List[str] = []
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            if item is None:
                continue
            if item.checkState() != QtCore.Qt.Checked:
                continue
            uid = str(item.data(QtCore.Qt.UserRole) or "").strip()
            if uid:
                ids.append(uid)
        return ids

    def _refresh_count(self) -> None:
        n = len(self._checked_ids_in_order())
        self.lbl_count.setText(f"已选 {n} 盘")
        self.btn_push.setEnabled(n > 0)

    def _on_item_changed(self, _item: QtWidgets.QListWidgetItem) -> None:
        self._refresh_count()

    def _select_all(self) -> None:
        self.list_widget.blockSignals(True)
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            if item is None or not (item.flags() & QtCore.Qt.ItemIsUserCheckable):
                continue
            item.setCheckState(QtCore.Qt.Checked)
        self.list_widget.blockSignals(False)
        self._refresh_count()

    def _clear_all(self) -> None:
        self.list_widget.blockSignals(True)
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            if item is None or not (item.flags() & QtCore.Qt.ItemIsUserCheckable):
                continue
            item.setCheckState(QtCore.Qt.Unchecked)
        self.list_widget.blockSignals(False)
        self._refresh_count()

    def _on_push_clicked(self) -> None:
        ids = self._checked_ids_in_order()
        if not ids:
            QtWidgets.QMessageBox.information(self, "下传 WCS", "请先勾选至少一个达标托盘。")
            return
        labels = []
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            if item is None or item.checkState() != QtCore.Qt.Checked:
                continue
            labels.append(item.text())
        preview = "\n".join(f"  · {t}" for t in labels[:20])
        if len(labels) > 20:
            preview += f"\n  … 另有 {len(labels) - 20} 盘"
        confirm = QtWidgets.QMessageBox.question(
            self,
            "确认下传",
            f"确认将以下 {len(ids)} 个达标托盘整盘下传到 WCS？\n\n{preview}",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
            QtWidgets.QMessageBox.No,
        )
        if confirm != QtWidgets.QMessageBox.Yes:
            return
        self._selected_unique_ids = ids
        self.accept()
