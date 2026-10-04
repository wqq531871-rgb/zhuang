import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import yaml
from PyQt5 import QtWidgets

import realtime_dashboard_v3_clean as dashboard


def test_header_offers_index_and_five_fill_rate_targets(tmp_path, monkeypatch):
    monkeypatch.setattr(
        dashboard,
        "_start_local_wcs_receiver",
        lambda _project, _log: None,
    )
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    window = dashboard.IndustrialPackingWorkbenchClean(tmp_path)
    try:
        labels = [
            window.cmb_success_target.itemText(index)
            for index in range(window.cmb_success_target.count())
        ]
        values = [
            window.cmb_success_target.itemData(index)
            for index in range(window.cmb_success_target.count())
        ]
        assert labels == [
            "指数 192",
            "装载率 70%",
            "装载率 75%",
            "装载率 80%",
            "装载率 85%",
            "装载率 90%",
        ]
        assert values == [
            ("index", 192.0),
            ("fill_rate", 0.70),
            ("fill_rate", 0.75),
            ("fill_rate", 0.80),
            ("fill_rate", 0.85),
            ("fill_rate", 0.90),
        ]
        assert window.current_success_target() == {
            "mode": "index",
            "threshold": 192.0,
        }
    finally:
        window.close()
        app.processEvents()


def test_excel_temp_config_records_selected_success_target(tmp_path):
    project = tmp_path / "packing-system"
    project.mkdir()
    data_dir = tmp_path / "packing-workspace" / "data" / "ui_inputs"
    data_dir.mkdir(parents=True)
    excel = data_dir / "input.xlsx"
    excel.write_bytes(b"placeholder")
    base = project / "config" / "packing_config.yaml"
    base.parent.mkdir(parents=True)
    base.write_text("run_mode: normal\n", encoding="utf-8")

    generated = dashboard._write_ui_config(
        project,
        base,
        excel,
        "normal",
        success_target={"mode": "fill_rate", "threshold": 0.85},
    )

    config = yaml.safe_load(generated.read_text(encoding="utf-8"))
    assert config["success_target"] == {
        "mode": "fill_rate",
        "threshold": 0.85,
    }
