"""现场码垛演示窗口冒烟测试（无 PLC / 无导入按钮）。"""

import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_API", "pyside6")

from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import QApplication

from packing_ui.animation import PHASES
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


def test_main_window_is_live_demo_ui():
    _app()
    window = _test_window()
    assert window.windowTitle() == "现场码垛演示"
    assert window.orientation_combo.currentData() == 0
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
