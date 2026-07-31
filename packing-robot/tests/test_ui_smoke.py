"""现场码垛三维演示 + PLC 独立窗口冒烟测试。"""

import os
from dataclasses import replace
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_API", "pyside6")

from PySide6.QtCore import QObject, Signal, Slot
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import QApplication

from packing_ui.animation import PHASES
from packing_ui.layout_state import (
    STATE_PATH_CAMERA,
    STATE_PATH_LAYOUT,
    LayoutStateAssignment,
    LayoutStateDecision,
    state_from_layout_dims,
)
from packing_ui.main_window import PackingMainWindow
from packing_ui.plc_controller import PlcController, PlcLockError
from packing_ui.plc_protocol import S7Config
from packing_ui.plc_window import PlcControlWindow


ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "wcs_plan_map_20260719_204522.json"
_TEST_APP = None


def _app():
    global _TEST_APP
    _TEST_APP = QApplication.instance() or QApplication([])
    return _TEST_APP


def _test_window(**kwargs):
    kwargs.setdefault("autoload", False)
    kwargs.setdefault("enable_3d", False)
    return PackingMainWindow(**kwargs)


def _test_plc_window(**kwargs):
    kwargs.setdefault("autoload", False)
    return PlcControlWindow(**kwargs)


def _layout_assignment(plan):
    decisions = tuple(
        LayoutStateDecision(
            seq=int(item.sequence),
            x_size=float(item.raw_length),
            y_size=float(item.raw_width),
            previous_state=(item.original or {}).get("state"),
            state=state_from_layout_dims(item.raw_length, item.raw_width),
        )
        for item in plan.items
    )
    return LayoutStateAssignment(
        box_unique_id=plan.source_key,
        box_count=len(decisions),
        changed_count=len(decisions),
        decisions=decisions,
    )


def _plan_with_assignment(plan, assignment):
    states = {decision.seq: decision.state for decision in assignment.decisions}
    items = tuple(
        replace(
            item,
            original={
                **dict(item.original or {}),
                "state": states[int(item.sequence)],
            },
        )
        for item in plan.items
    )
    return replace(plan, items=items)


def test_main_window_is_live_demo_ui_without_plc_panel():
    _app()
    window = _test_window()
    assert window.windowTitle() == "现场码垛演示"
    assert window.orientation_combo.currentData() == 0
    assert not hasattr(window, "state_path_combo")
    assert not hasattr(window, "auto_plc_checkbox")
    assert not hasattr(window, "plc_ip_edit")
    assert not hasattr(window, "connect_plc_button")
    assert not hasattr(window, "open_button")
    assert window.selector_group.title() == "托盘选择"
    from PySide6.QtWidgets import QLabel

    hint_texts = [w.text() for w in window.findChildren(QLabel) if w.text()]
    assert any("连接 PLC" in text for text in hint_texts)
    window.close()


def test_plc_window_defaults_and_camera_path_labels():
    _app()
    window = _test_plc_window()
    assert window.windowTitle() == "PLC 通讯"
    assert window.auto_plc_checkbox.isChecked() is True
    assert window.plc_ip_edit.text() == "10.19.40.70"
    assert window.manual_plc_button.text() == "手动发送当前托盘"
    assert window.state_path_combo.currentData() == STATE_PATH_LAYOUT
    assert window.state_path_combo.itemText(0) == "不接收相机"
    assert window.state_path_combo.itemText(1) == "接收相机"
    assert window.apply_state_path_button.text() == "应用到当前托盘"
    window.close()


def test_auto_connect_schedules_connect_on_startup(monkeypatch):
    app = _app()
    calls = []
    monkeypatch.setattr(
        PlcControlWindow,
        "_connect_plc",
        lambda self: calls.append("connect"),
    )
    window = _test_plc_window(auto_connect=True)
    app.processEvents()
    assert calls == ["connect"]
    window.close()


def test_connect_enters_wait_send_when_auto_enabled(monkeypatch):
    _app()
    window = _test_plc_window()
    calls = []
    monkeypatch.setattr(
        window.controller,
        "connect_plc",
        lambda _cfg: setattr(window.controller, "_plc_connected", True),
    )
    monkeypatch.setattr(
        window.controller,
        "start_pallet_send",
        lambda config, *, source="manual": calls.append(source),
    )
    from packing_ui.data import load_plan_file

    if SAMPLE.is_file():
        window.controller.current_plan = load_plan_file(SAMPLE)[0]
    else:
        window.controller.current_plan = type(
            "P", (), {"source_key": "u1", "items": (1,)}
        )()

    window._connect_plc()
    assert calls == ["auto"]
    window.controller._plc_connected = False
    window.close()


def test_plc_window_can_switch_between_camera_paths():
    _app()
    window = _test_plc_window()

    layout_index = window.state_path_combo.findData(STATE_PATH_LAYOUT)
    assert layout_index >= 0
    window.state_path_combo.setCurrentIndex(layout_index)
    assert window.current_state_path() == STATE_PATH_LAYOUT
    assert "不接收相机" in window.state_path_status_label.text()

    camera_index = window.state_path_combo.findData(STATE_PATH_CAMERA)
    window.state_path_combo.setCurrentIndex(camera_index)
    assert window.current_state_path() == STATE_PATH_CAMERA
    assert "接收相机" in window.state_path_status_label.text()
    window.close()


@pytest.mark.skipif(not SAMPLE.is_file(), reason="缺少样例 JSON")
def test_plc_apply_layout_path_writes_state(monkeypatch):
    _app()
    calls = []
    assignments = []
    window = _test_plc_window()

    # Load plan into controller via load_path-like assignment
    from packing_ui.data import load_plan_file

    plan = load_plan_file(SAMPLE)[0]
    window.controller.current_plan = plan
    window._refresh_plan_labels(plan)

    def writer(uid, **kwargs):
        calls.append((uid, kwargs))
        assignment = _layout_assignment(window.controller.current_plan)
        assignments.append(assignment)
        return assignment

    window.controller._layout_state_writer = writer

    def reload_plan(uid, **_kwargs):
        assert uid == plan.source_key
        return _plan_with_assignment(plan, assignments[-1])

    monkeypatch.setattr(window.controller, "_plan_loader", reload_plan)
    window.state_path_combo.setCurrentIndex(
        window.state_path_combo.findData(STATE_PATH_LAYOUT)
    )
    window.apply_state_path_button.click()

    assert calls == [(plan.source_key, {"config_path": None})]
    assert "已写入" in window.state_path_status_label.text()
    window.close()


@pytest.mark.skipif(not SAMPLE.is_file(), reason="缺少样例 JSON")
def test_selected_layout_path_is_forwarded_to_plc_worker(monkeypatch):
    app = _app()
    captured = {}

    class FakeWorker(QObject):
        status = Signal(str)
        plc_status = Signal(object)
        box_finished = Signal(int)
        alarm = Signal(int)
        failed = Signal(str)
        finished = Signal()

        @Slot()
        def run(self):
            self.finished.emit()

        @Slot()
        def request_stop(self):
            return None

    def worker_factory(**kwargs):
        captured.update(kwargs)
        return FakeWorker()

    window = _test_plc_window(plc_worker_factory=worker_factory)
    from packing_ui.data import load_plan_file

    plan = load_plan_file(SAMPLE)[0]
    window.controller.current_plan = plan
    window.state_path_combo.setCurrentIndex(
        window.state_path_combo.findData(STATE_PATH_LAYOUT)
    )
    monkeypatch.setattr(
        window.controller,
        "apply_layout_state",
        lambda *, automatic: None,
    )
    window.controller._plc_connected = True

    window.controller.start_pallet_send(
        S7Config(ip="10.19.40.70", rack=0, slot=1, db_number=19),
        source="manual",
    )

    assert captured["state_source"] == STATE_PATH_LAYOUT
    thread = window.controller._plc_thread
    if thread is not None:
        thread.quit()
        thread.wait(1000)
    app.processEvents()
    window.controller._plc_thread = None
    window.controller._plc_worker = None
    window.close()


@pytest.mark.skipif(not SAMPLE.is_file(), reason="缺少样例 JSON")
def test_layout_path_cannot_rewrite_state_while_plc_task_is_running():
    _app()
    calls = []
    window = _test_plc_window(
        layout_state_writer=lambda *_args, **_kwargs: calls.append("write")
    )
    from packing_ui.data import load_plan_file

    plan = load_plan_file(SAMPLE)[0]
    window.controller.current_plan = plan
    window.state_path_combo.setCurrentIndex(
        window.state_path_combo.findData(STATE_PATH_LAYOUT)
    )

    class RunningThread:
        def isRunning(self):
            return True

    window.controller._plc_thread = RunningThread()
    window.apply_state_path_button.click()

    assert calls == []
    assert "PLC 任务运行中" in window.state_path_status_label.text()
    window.controller._plc_thread = None
    window.close()


def test_plc_window_accepts_camera_dimension_writer_dependency():
    _app()
    writer = lambda *_args, **_kwargs: 1
    window = _test_plc_window(camera_dimension_writer=writer)
    assert window.controller._camera_dimension_writer is writer
    window.close()


def test_auto_wait_respects_checkbox(monkeypatch):
    _app()
    window = _test_plc_window()
    calls = []
    monkeypatch.setattr(
        window.controller,
        "start_pallet_send",
        lambda config, *, source="manual": calls.append(source),
    )
    window.controller._plc_connected = True
    window.controller.current_plan = type(
        "P", (), {"source_key": "u1", "items": (1,)}
    )()

    window.auto_plc_checkbox.setChecked(False)
    window._try_enter_wait_send(source="connect")
    assert calls == []

    window.auto_plc_checkbox.setChecked(True)
    window._try_enter_wait_send(source="connect")
    assert calls == ["auto"]
    window.close()


def test_close_waits_for_safe_plc_stop_instead_of_destroying_running_thread():
    _app()
    window = _test_plc_window()

    class Worker:
        stopped = False

        def request_stop(self):
            self.stopped = True

    class Thread:
        def isRunning(self):
            return True

        def wait(self, _milliseconds):
            return False

    worker = Worker()
    window.controller._plc_worker = worker
    window.controller._plc_thread = Thread()
    event = QCloseEvent()

    window.closeEvent(event)

    assert worker.stopped is True
    assert event.isAccepted() is False
    window.controller._plc_thread = None
    window.controller._plc_worker = None
    window.close()


def test_plc_lock_rejects_second_connection(tmp_path, monkeypatch):
    _app()
    lock = tmp_path / "plc_s7.lock"
    lock.write_text(str(os.getpid()), encoding="utf-8")

    # Simulate another "alive" PID that is not us
    other_pid = os.getpid() + 99999
    lock.write_text(str(other_pid), encoding="utf-8")
    monkeypatch.setattr(
        "packing_ui.plc_controller._pid_alive",
        lambda pid: pid == other_pid,
    )

    ctrl = PlcController(lock_path=lock, parent=None)
    with pytest.raises(PlcLockError):
        ctrl.connect_plc(S7Config(ip="127.0.0.1", rack=0, slot=1, db_number=19))


@pytest.mark.skipif(not SAMPLE.is_file(), reason="缺少样例 JSON")
def test_debug_load_path_fills_boxes_and_playback():
    app = _app()
    window = _test_window()
    window.load_path(SAMPLE)
    app.processEvents()
    assert window.current_plan is not None
    assert window.box_list.count() == len(window.current_plan.items)
    assert window.playback_controller.step_count == len(window.current_plan.items)
    assert "托盘 uid" in window.details.text() or "托盘编号" in window.details.text()
    window.close()


@pytest.mark.skipif(not SAMPLE.is_file(), reason="缺少样例 JSON")
def test_selected_pallet_displays_full_box_unique_id():
    _app()
    window = _test_window()

    window.load_path(SAMPLE)

    assert window.order_label.text() == "ea1ed40cb35f4842bad04e45ac5a95b1"
    window.close()


@pytest.mark.skipif(not SAMPLE.is_file(), reason="缺少样例 JSON")
def test_orientation_change_only_updates_selected_box():
    app = _app()
    window = _test_window()
    window.load_path(SAMPLE)
    window.box_list.setCurrentRow(1)
    window.orientation_combo.setCurrentIndex(1)
    app.processEvents()
    assert window.actions[1].conveyor_orientation_deg == 90
    window.close()


@pytest.mark.skipif(not SAMPLE.is_file(), reason="缺少样例 JSON")
def test_replay_current_box_button_replays_only_selected_box():
    _app()
    window = _test_window()
    window.load_path(SAMPLE)
    window.box_list.setCurrentRow(1)
    controller = window.playback_controller
    selected_index = controller.current_step_index
    controller.phase_index = 3
    controller.fraction = 0.5

    assert window.playback_panel.replay_button.text() == "重复当前箱"
    window.playback_panel.replay_button.click()

    assert controller.current_step_index == selected_index
    assert controller.phase == "READY"
    assert controller.fraction == 0.0
    assert controller.is_playing is True

    controller.advance(float(len(PHASES)))

    assert controller.current_step_index == selected_index
    assert controller.phase == PHASES[-1]
    assert controller.fraction == 1.0
    assert controller.is_playing is False
    window.close()


@pytest.mark.skipif(not SAMPLE.is_file(), reason="缺少样例 JSON")
def test_live_load_pallet_does_not_auto_start_plc(monkeypatch):
    _app()
    window = _test_window()
    window.load_path(SAMPLE)
    base_plan = window.current_plan
    monkeypatch.setattr(window, "_load_plan_for_uid", lambda _uid: base_plan)
    monkeypatch.setattr(window, "apply_wcs_history", lambda prefer_uid="": False)

    window.apply_live_load_pallet(
        {
            "box_unique_id": base_plan.source_key,
            "order_id": "SO-LIVE",
            "auto_play": False,
        }
    )

    assert window.current_plan is not None
    assert window.current_plan.source_key == base_plan.source_key
    assert not hasattr(window, "_maybe_auto_start_plc")
    window.close()
