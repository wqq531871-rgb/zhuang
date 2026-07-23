import os
from pathlib import Path
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_API", "pyside6")

from PySide6.QtWidgets import QApplication

from packing_ui.main_window import PackingMainWindow
from packing_ui.state_repository import DatabaseStateError, MySqlConfig, ProductState
from packing_ui.state_sync import StateSyncWorker


ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "wcs_plan_map_20260719_204522.json"
_TEST_APP = None


def _app():
    global _TEST_APP
    _TEST_APP = QApplication.instance() or QApplication([])
    return _TEST_APP


class _NoOpProductStateRepository:
    def __init__(self, _config):
        pass

    def update_states(self, updates):
        return len(tuple(updates))


def _test_window(**kwargs):
    kwargs.setdefault("autoload", False)
    kwargs.setdefault("enable_3d", False)
    kwargs.setdefault("state_config_loader", lambda: MySqlConfig())
    kwargs.setdefault(
        "state_worker_factory",
        lambda config, updates: StateSyncWorker(
            config,
            updates,
            repository_factory=_NoOpProductStateRepository,
        ),
    )
    return PackingMainWindow(**kwargs)


def _wait_for_state_sync(app, window):
    deadline = time.monotonic() + 2.0
    while window._state_sync_thread is not None and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.005)
    assert window._state_sync_thread is None


def test_main_window_matches_reference_selector_defaults():
    _app()
    window = _test_window()

    assert window.windowTitle() == "机器人装箱三维仿真系统"
    assert window.status_combo.currentData() == "SUCCESS"
    assert window.orientation_combo.currentData() == 0
    assert window.type_combo.count() == 0
    assert window.playback_panel.phase_label.text() == "READY"
    assert window.open_plc_ui_button.text() == "打开 PLC 通讯界面"
    assert window.plc_ui_status_label.text() == "未启动"
    assert window.database_state_label.text() == "未同步"
    assert "box_unique_id" in window.plc_handoff_note.text()
    assert not hasattr(window, "plc_ip_edit")
    assert not hasattr(window, "plc_connect_button")
    assert window.plc_group.parentWidget().objectName() == "rightPanel"
    window.close()


def test_loading_sample_links_type_pallet_sequence_and_playback():
    app = _app()
    window = _test_window()

    window.load_path(SAMPLE)
    app.processEvents()

    assert len(window.filtered_plans) == 6
    assert window.current_plan is not None
    assert window.box_list.count() == len(window.current_plan.items)
    assert window.playback_controller.step_count == len(window.current_plan.items)
    assert window.details.text().startswith("托盘：")
    assert window.type_combo.currentText() == "MH423C"
    window.close()


def test_orientation_change_only_updates_selected_box_and_syncs_on_selection():
    app = _app()
    window = _test_window()
    window.load_path(SAMPLE)

    window.box_list.setCurrentRow(1)
    window.orientation_combo.setCurrentIndex(1)
    app.processEvents()

    assert window.orientation_combo.currentData() == 90
    assert window.box_list.currentRow() == 1
    assert window.actions[0].conveyor_orientation_deg == 0
    assert window.actions[1].conveyor_orientation_deg == 90
    assert all(
        action.conveyor_orientation_deg == 0 for action in window.actions[2:]
    )
    assert {action.rotation_deg for action in window.actions} <= {0, 90}
    assert window.playback_controller.step_count == len(window.actions)

    window.box_list.setCurrentRow(0)
    app.processEvents()
    assert window.orientation_combo.currentData() == 0

    window.box_list.setCurrentRow(1)
    app.processEvents()
    assert window.orientation_combo.currentData() == 90
    window.close()


def test_camera_payload_binds_by_box_id_and_updates_plc_status():
    app = _app()
    window = _test_window()
    window.load_path(SAMPLE)
    item_id = window.actions[0].item_id

    count = window.receive_camera_data(
        {
            "box_id": item_id,
            "x": 420,
            "y": -1100,
            "z": 5,
            "orientation_deg": 90,
            "confidence": 0.97,
        }
    )
    _wait_for_state_sync(app, window)

    assert count == 1
    assert window.actions[0].camera_data is not None
    assert window.actions[0].plc_ready is True
    assert window.camera_status_label.text() == "已接收"
    assert window.camera_box_label.text() == item_id
    assert window.plc_state_label.text() in {"1（不旋转）", "2（旋转90°）"}
    assert f"吸附点：{window.actions[0].pickup_point}" in window.details.text()
    window.close()


def test_invalid_camera_payload_does_not_replace_previous_valid_data():
    app = _app()
    window = _test_window()
    window.load_path(SAMPLE)
    item_id = window.actions[0].item_id
    window.receive_camera_data({"box_id": item_id, "orientation_deg": 0})
    _wait_for_state_sync(app, window)

    with pytest.raises(ValueError, match="0 或 90"):
        window.receive_camera_data({"box_id": item_id, "orientation_deg": 45})

    assert window.actions[0].camera_data.orientation_deg == 0
    window.close()


def test_unknown_camera_box_is_rejected():
    _app()
    window = _test_window()
    window.load_path(SAMPLE)

    with pytest.raises(ValueError, match="不属于当前托盘"):
        window.receive_camera_data(
            {"box_id": "UNKNOWN-CAMERA-BOX", "orientation_deg": 0}
        )
    window.close()


def test_export_payload_contains_plc_commands_in_action_order():
    app = _app()
    window = _test_window()
    window.load_path(SAMPLE)
    first = window.actions[0]
    window.receive_camera_data(
        {"box_id": first.item_id, "orientation_deg": first.target_orientation_deg}
    )
    _wait_for_state_sync(app, window)

    payload = window.build_export_payload()
    command = payload["plc_commands"][0]

    assert [command["box_id"] for command in payload["plc_commands"]] == [
        action.item_id for action in window.actions
    ]
    assert command == {
        "box_id": first.item_id,
        "seq": first.sequence,
        "ready": True,
        "rotation_state": 1,
        "pickup_point": "A",
        "pickup_point_code": 1,
        "pickup_z": first.pick_z,
        "placement_x": first.box_place[0],
        "placement_y": first.box_place[1],
        "placement_z": first.box_place[2],
        "target_orientation_deg": first.target_orientation_deg,
    }
    assert payload["plc_commands"][1]["ready"] is False
    window.close()


def test_open_plc_ui_button_launches_old_ui_once_while_process_is_running():
    app = _app()
    launches = []

    class RunningProcess:
        def poll(self):
            return None

    def launcher():
        launches.append(True)
        return RunningProcess()

    window = _test_window(plc_launcher=launcher)

    window.open_plc_ui_button.click()
    window.open_plc_ui_button.click()
    app.processEvents()

    assert launches == [True]
    assert window.plc_ui_status_label.text() == "运行中"
    assert "旧 PLC 通讯界面已经在运行" in window.statusBar().currentMessage()
    window.close()


def test_camera_judgement_syncs_item_id_and_state_by_product_code():
    app = _app()
    captured = []

    class Repo:
        def __init__(self, config):
            assert config.database == "zhuangdb"

        def update_states(self, updates):
            captured.extend(updates)
            return len(tuple(updates))

    def worker_factory(config, updates):
        return StateSyncWorker(config, updates, repository_factory=Repo)

    window = PackingMainWindow(
        autoload=False,
        enable_3d=False,
        state_config_loader=lambda: MySqlConfig(),
        state_worker_factory=worker_factory,
    )
    window.load_path(SAMPLE)
    first = window.actions[0]
    camera_orientation = 90 - first.target_orientation_deg

    window.receive_camera_data(
        {"box_id": first.item_id, "orientation_deg": camera_orientation}
    )
    _wait_for_state_sync(app, window)

    assert captured == [ProductState(first.item_id, 2)]
    assert window.database_state_label.text() == "已同步 1 箱"
    assert window.open_plc_ui_button.isEnabled() is True
    window.close()


def test_database_sync_failure_is_visible_and_transaction_is_not_hidden():
    app = _app()

    class Repo:
        def __init__(self, _config):
            pass

        def update_states(self, _updates):
            raise DatabaseStateError("product_code=BOX-X 没有找到数据库记录")

    window = PackingMainWindow(
        autoload=False,
        enable_3d=False,
        state_config_loader=lambda: MySqlConfig(),
        state_worker_factory=lambda config, updates: StateSyncWorker(
            config,
            updates,
            repository_factory=Repo,
        ),
    )
    window.load_path(SAMPLE)
    first = window.actions[0]

    window.receive_camera_data(
        {"box_id": first.item_id, "orientation_deg": first.target_orientation_deg}
    )
    _wait_for_state_sync(app, window)

    assert window.database_state_label.text() == "同步失败"
    assert "没有找到数据库记录" in window.statusBar().currentMessage()
    window.close()
