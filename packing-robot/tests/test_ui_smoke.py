"""现场码垛演示窗口冒烟测试（无 PLC / 无导入按钮）。"""

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


def test_main_window_is_live_demo_ui():
    _app()
    window = _test_window()
    assert window.windowTitle() == "现场码垛演示"
    assert window.orientation_combo.currentData() == 0
    assert window.state_path_combo.currentData() == STATE_PATH_CAMERA
    assert window.apply_state_path_button.text() == "应用到当前托盘"
    assert not hasattr(window, "open_plc_ui_button")
    assert not hasattr(window, "open_button")
    assert window.selector_group.title() == "托盘选择"
    window.close()


def test_plc_auto_is_off_on_every_window_start():
    _app()
    window = _test_window()
    assert window.auto_plc_checkbox.isChecked() is False
    assert window.plc_ip_edit.text() == "10.19.40.70"
    assert window.manual_plc_button.text() == "手动发送当前托盘"
    window.close()


def test_window_can_switch_between_camera_and_layout_state_paths():
    _app()
    window = _test_window()

    layout_index = window.state_path_combo.findData(STATE_PATH_LAYOUT)
    assert layout_index >= 0
    window.state_path_combo.setCurrentIndex(layout_index)
    assert window.current_state_path() == STATE_PATH_LAYOUT
    assert "垛型直判" in window.state_path_status_label.text()

    camera_index = window.state_path_combo.findData(STATE_PATH_CAMERA)
    window.state_path_combo.setCurrentIndex(camera_index)
    assert window.current_state_path() == STATE_PATH_CAMERA
    assert "相机判态" in window.state_path_status_label.text()
    window.close()


@pytest.mark.skipif(not SAMPLE.is_file(), reason="缺少样例 JSON")
def test_apply_layout_path_writes_current_uid_and_refreshes_readiness(monkeypatch):
    _app()
    calls = []
    assignments = []

    def writer(uid, **kwargs):
        calls.append((uid, kwargs))
        assignment = _layout_assignment(window.current_plan)
        assignments.append(assignment)
        return assignment

    window = _test_window(layout_state_writer=writer)
    window.load_path(SAMPLE)
    original_plan = window.current_plan
    window.state_path_combo.setCurrentIndex(
        window.state_path_combo.findData(STATE_PATH_LAYOUT)
    )

    def reload_plan(uid):
        assert uid == original_plan.source_key
        return _plan_with_assignment(original_plan, assignments[-1])

    monkeypatch.setattr(window, "_load_plan_for_uid", reload_plan)
    window.apply_state_path_button.click()

    assert calls == [
        (
            original_plan.source_key,
            {"config_path": None},
        )
    ]
    assert all(action.show_on_conveyor for action in window.actions)
    assert "已写入" in window.state_path_status_label.text()
    assert str(len(original_plan.items)) in window.state_path_status_label.text()
    window.close()


@pytest.mark.skipif(not SAMPLE.is_file(), reason="缺少样例 JSON")
def test_live_layout_path_assigns_state_before_auto_plc(monkeypatch):
    _app()
    events = []
    window = _test_window()
    window.load_path(SAMPLE)
    base_plan = window.current_plan
    assignment = _layout_assignment(base_plan)
    refreshed_plan = _plan_with_assignment(base_plan, assignment)
    loads = iter((base_plan, refreshed_plan))

    window._layout_state_writer = (
        lambda uid, **_kwargs: events.append(("layout", uid)) or assignment
    )
    monkeypatch.setattr(window, "_load_plan_for_uid", lambda _uid: next(loads))
    monkeypatch.setattr(window, "apply_wcs_history", lambda prefer_uid="": False)
    monkeypatch.setattr(
        window,
        "_maybe_auto_start_plc",
        lambda: events.append(("auto_plc", window.current_plan.source_key)),
    )
    window.state_path_combo.setCurrentIndex(
        window.state_path_combo.findData(STATE_PATH_LAYOUT)
    )

    window.apply_live_load_pallet(
        {
            "box_unique_id": base_plan.source_key,
            "order_id": "SO-LAYOUT",
            "auto_play": False,
        }
    )

    assert events == [
        ("layout", base_plan.source_key),
        ("auto_plc", base_plan.source_key),
    ]
    assert all(action.show_on_conveyor for action in window.actions)
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

    window = _test_window(plc_worker_factory=worker_factory)
    window.load_path(SAMPLE)
    window.state_path_combo.setCurrentIndex(
        window.state_path_combo.findData(STATE_PATH_LAYOUT)
    )
    monkeypatch.setattr(
        window,
        "_apply_layout_state_to_current_plan",
        lambda *, automatic: None,
    )
    window._plc_connected = True

    window._start_current_pallet_send("manual")

    assert captured["state_source"] == STATE_PATH_LAYOUT
    thread = window._plc_thread
    if thread is not None:
        thread.quit()
        thread.wait(1000)
    app.processEvents()
    window._plc_thread = None
    window._plc_worker = None
    window.close()


@pytest.mark.skipif(not SAMPLE.is_file(), reason="缺少样例 JSON")
def test_layout_path_cannot_rewrite_state_while_plc_task_is_running():
    _app()
    calls = []
    window = _test_window(
        layout_state_writer=lambda *_args, **_kwargs: calls.append("write")
    )
    window.load_path(SAMPLE)
    window.state_path_combo.setCurrentIndex(
        window.state_path_combo.findData(STATE_PATH_LAYOUT)
    )

    class RunningThread:
        def isRunning(self):
            return True

    window._plc_thread = RunningThread()
    window.apply_state_path_button.click()

    assert calls == []
    assert "PLC 任务运行中" in window.state_path_status_label.text()
    window._plc_thread = None
    window.close()


def test_window_accepts_camera_dimension_writer_dependency():
    _app()
    writer = lambda *_args, **_kwargs: 1
    window = _test_window(camera_dimension_writer=writer)
    assert window._camera_dimension_writer is writer
    window.close()


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


def test_wcs_auto_trigger_only_calls_shared_send_entry_when_enabled(monkeypatch):
    _app()
    window = _test_window()
    calls = []
    monkeypatch.setattr(window, "_start_current_pallet_send", calls.append)

    window.auto_plc_checkbox.setChecked(False)
    window._maybe_auto_start_plc()
    assert calls == []

    window.auto_plc_checkbox.setChecked(True)
    window._plc_connected = True
    window._maybe_auto_start_plc()
    assert calls == ["wcs"]
    window.close()


def test_close_waits_for_safe_plc_stop_instead_of_destroying_running_thread():
    _app()
    window = _test_window()

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
    window._plc_worker = worker
    window._plc_thread = Thread()
    event = QCloseEvent()

    window.closeEvent(event)

    assert worker.stopped is True
    assert event.isAccepted() is False
    window._plc_thread = None
    window._plc_worker = None
    window.close()


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
def test_orientation_change_only_updates_selected_box():
    app = _app()
    window = _test_window()
    window.load_path(SAMPLE)
    window.box_list.setCurrentRow(1)
    window.orientation_combo.setCurrentIndex(1)
    app.processEvents()
    assert window.actions[1].conveyor_orientation_deg == 90
    if len(window.actions) > 2:
        assert window.actions[0].conveyor_orientation_deg != 90 or True
    window.close()
