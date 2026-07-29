from PySide6.QtCore import QCoreApplication, QObject, Signal, Slot

from packing_ui.live_command import write_live_command
from packing_ui.layout_state import STATE_PATH_CAMERA
import packing_ui.plc_controller as plc_controller_module
from packing_ui.plc_controller import PlcController
from packing_ui.plc_protocol import S7Config


def test_non_final_handshake_does_not_complete_pallet(tmp_path):
    completed = []
    controller = PlcController(
        pallet_completion_writer=completed.append,
        lock_path=tmp_path / "plc.lock",
    )

    controller._on_box_finished("p1", 9, 8)

    assert completed == []


def test_final_sequence_handshake_completes_started_pallet(tmp_path):
    completed = []
    controller = PlcController(
        pallet_completion_writer=completed.append,
        lock_path=tmp_path / "plc.lock",
    )

    controller._on_box_finished("p1", 9, 9)

    assert completed == ["p1"]


def test_sequence_larger_than_final_does_not_complete_pallet(tmp_path):
    completed = []
    controller = PlcController(
        pallet_completion_writer=completed.append,
        lock_path=tmp_path / "plc.lock",
    )

    controller._on_box_finished("p1", 9, 10)

    assert completed == []


def test_worker_final_box_signal_completes_started_pallet(tmp_path):
    app = QCoreApplication.instance() or QCoreApplication([])
    completed = []
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
            return None

        @Slot()
        def request_stop(self):
            self.finished.emit()

    def worker_factory(**_kwargs):
        worker = FakeWorker()
        captured["worker"] = worker
        return worker

    controller = PlcController(
        plc_worker_factory=worker_factory,
        pallet_completion_writer=completed.append,
        lock_path=tmp_path / "plc.lock",
    )
    controller._plc_connected = True
    controller.set_state_source(STATE_PATH_CAMERA)
    controller.current_plan = type(
        "Plan",
        (),
        {
            "source_key": "started-pallet",
            "items": (
                type("Item", (), {"sequence": 3})(),
                type("Item", (), {"sequence": 7})(),
            ),
        },
    )()

    controller.start_pallet_send(S7Config(ip="127.0.0.1"))
    captured["worker"].box_finished.emit(7)
    app.processEvents()

    assert completed == ["started-pallet"]
    controller.stop_send()
    controller.wait_send_finished(1000)
    app.processEvents()


def test_try_load_session_plan_recovers_active_history(tmp_path, monkeypatch):
    session = tmp_path / "session.json"
    history = tmp_path / "history.json"
    write_live_command(
        history,
        [{"box_unique_id": "recover-me", "stack_status": "active"}],
    )
    monkeypatch.setattr(
        plc_controller_module,
        "default_session_path",
        lambda: session,
    )
    monkeypatch.setattr(
        plc_controller_module,
        "default_history_path",
        lambda: history,
    )
    loaded = []
    expected = object()
    controller = PlcController(
        plan_loader=lambda uid, **_kwargs: loaded.append(uid) or expected,
        lock_path=tmp_path / "plc.lock",
    )

    result = controller.try_load_session_plan()

    assert result is expected
    assert loaded == ["recover-me"]
