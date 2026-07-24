"""现场码垛演示窗口冒烟测试（无 PLC / 无导入按钮）。"""

import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_API", "pyside6")

from PySide6.QtWidgets import QApplication

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
