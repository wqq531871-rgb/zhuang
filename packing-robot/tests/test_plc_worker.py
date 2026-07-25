from types import SimpleNamespace

from packing_ui.plc_worker import PlcSendWorker
from packing_ui.layout_state import STATE_PATH_CAMERA, STATE_PATH_LAYOUT


ROW = {
    "seq": 7,
    "camera_length": 401,
    "camera_width": 302,
    "camera_height": 203,
    "raw_length": 400,
    "raw_width": 300,
    "raw_height": 200,
    "pos_x": 100,
    "pos_y": 110,
    "pos_z": 120,
    "state": 2,
    "box_num": 12,
    "stack_height_before": 480,
}


class FakeProtocol:
    def __init__(
        self,
        *,
        events=None,
        inbound=None,
        request_error=None,
        request_queue=None,
    ):
        self.events = events if events is not None else []
        self.inbound = inbound or SimpleNamespace(
            request_seq=7,
            camera_length=401,
            camera_width=302,
            camera_height=203,
        )
        self.request_error = request_error
        self.request_queue = list(request_queue or [])
        self.normal = []
        self.alarms = []
        self.disconnected = False

    def connect(self):
        return None

    def disconnect(self):
        self.disconnected = True

    def wait_request(self, expected_seq):
        self.events.append(("wait_request", expected_seq))
        if self.request_error is not None:
            raise self.request_error
        if self.request_queue:
            return self.request_queue.pop(0)
        return self.inbound

    def send_normal(self, command):
        self.normal.append(command)

    def send_alarm(self, expected_seq):
        self.alarms.append(expected_seq)


def make_worker(
    *,
    protocol,
    row_loader,
    camera_writer,
    state_source=STATE_PATH_CAMERA,
    sequences=(7,),
):
    return PlcSendWorker(
        config=object(),
        box_unique_id="a" * 32,
        sequences=sequences,
        row_loader=row_loader,
        camera_writer=camera_writer,
        state_source=state_source,
        client_factory=lambda: object(),
        protocol_factory=lambda *_args, **_kwargs: protocol,
        sleep=lambda _seconds: None,
    )


def worker(rows, protocol, camera_writer=lambda *_args: 1):
    values = iter(rows)
    return make_worker(
        protocol=protocol,
        row_loader=lambda _uid, _seq: next(values),
        camera_writer=camera_writer,
    )


def test_worker_writes_camera_dimensions_before_polling_state():
    events = []
    protocol = FakeProtocol(events=events)

    def camera_writer(uid, seq, length, width, height):
        events.append(("camera_write", uid, seq, length, width, height))
        return 1

    def row_loader(uid, seq):
        events.append(("state_read", uid, seq))
        return ROW

    target = make_worker(
        protocol=protocol,
        row_loader=row_loader,
        camera_writer=camera_writer,
    )

    target.run()

    assert events[:3] == [
        ("wait_request", None),
        ("camera_write", "a" * 32, 7, 401, 302, 203),
        ("state_read", "a" * 32, 7),
    ]
    assert [command.sequence for command in protocol.normal] == [7]


def test_layout_path_skips_camera_dimensions_and_reads_state_directly():
    events = []
    protocol = FakeProtocol(
        events=events,
        inbound=SimpleNamespace(
            request_seq=7,
            camera_length=0,
            camera_width=0,
            camera_height=0,
        ),
    )

    def row_loader(uid, seq):
        events.append(("state_read", uid, seq))
        return ROW

    target = make_worker(
        protocol=protocol,
        row_loader=row_loader,
        camera_writer=lambda *_args: events.append(("camera_write",)),
        state_source=STATE_PATH_LAYOUT,
    )
    errors = []
    target.failed.connect(errors.append)

    target.run()

    assert events == [
        ("wait_request", None),
        ("state_read", "a" * 32, 7),
    ]
    assert errors == []
    assert [command.sequence for command in protocol.normal] == [7]


def test_worker_follows_plc_requested_seq_not_preload_order():
    events = []
    row2 = {**ROW, "seq": 2, "state": 1}
    protocol = FakeProtocol(
        events=events,
        request_queue=[
            SimpleNamespace(
                request_seq=2,
                camera_length=0,
                camera_width=0,
                camera_height=0,
            ),
            SimpleNamespace(
                request_seq=1,
                camera_length=0,
                camera_width=0,
                camera_height=0,
            ),
        ],
    )

    def row_loader(_uid, seq):
        events.append(("state_read", seq))
        if seq == 2:
            return row2
        return {**ROW, "seq": 1, "state": 1}

    target = make_worker(
        protocol=protocol,
        row_loader=row_loader,
        camera_writer=lambda *_a: 1,
        state_source=STATE_PATH_LAYOUT,
        sequences=(1, 2),
    )
    completed = []
    target.box_finished.connect(completed.append)
    errors = []
    target.failed.connect(errors.append)

    target.run()

    assert errors == []
    assert events[:4] == [
        ("wait_request", None),
        ("state_read", 2),
        ("wait_request", None),
        ("state_read", 1),
    ]
    assert [c.sequence for c in protocol.normal] == [2, 1]
    assert completed == [2, 1]


def test_worker_waits_for_null_state_then_sends_latest_row():
    protocol = FakeProtocol()
    target = worker([{**ROW, "state": None}, {**ROW, "state": 2}], protocol)
    completed = []
    target.box_finished.connect(completed.append)

    target.run()

    assert [command.sequence for command in protocol.normal] == [7]
    assert protocol.alarms == []
    assert completed == [7]
    assert protocol.disconnected is True


def test_worker_state_zero_only_alarms_and_stops():
    protocol = FakeProtocol()
    target = worker([{**ROW, "state": 0}], protocol)
    alarms = []
    target.alarm.connect(alarms.append)

    target.run()

    assert protocol.alarms == [7]
    assert protocol.normal == []
    assert alarms == [7]


def test_worker_rejects_nonpositive_camera_dimensions_before_db_or_rev_write():
    calls = []
    protocol = FakeProtocol(
        inbound=SimpleNamespace(
            request_seq=7,
            camera_length=0,
            camera_width=302,
            camera_height=203,
        )
    )
    target = make_worker(
        protocol=protocol,
        row_loader=lambda *_args: calls.append("state_read"),
        camera_writer=lambda *_args: calls.append("camera_write"),
    )
    errors = []
    target.failed.connect(errors.append)

    target.run()

    assert errors == [
        "seq=7 的 PLC 相机尺寸无效：DBW6=0，DBW8=302，DBW10=203"
    ]
    assert calls == []
    assert protocol.alarms == []
    assert protocol.normal == []


def test_worker_stops_when_camera_database_row_is_missing():
    calls = []
    protocol = FakeProtocol()
    target = make_worker(
        protocol=protocol,
        row_loader=lambda *_args: calls.append("state_read"),
        camera_writer=lambda *_args: 0,
    )
    errors = []
    target.failed.connect(errors.append)

    target.run()

    assert errors == [
        f"数据库中找不到 box_unique_id={'a' * 32} seq=7"
    ]
    assert calls == []
    assert protocol.alarms == []
    assert protocol.normal == []


def test_worker_fails_when_plc_seq_missing_in_database():
    protocol = FakeProtocol(
        inbound=SimpleNamespace(
            request_seq=99,
            camera_length=0,
            camera_width=0,
            camera_height=0,
        )
    )
    target = make_worker(
        protocol=protocol,
        row_loader=lambda *_args: None,
        camera_writer=lambda *_args: 1,
        state_source=STATE_PATH_LAYOUT,
        sequences=(1, 2),
    )
    errors = []
    target.failed.connect(errors.append)

    target.run()

    assert errors == [
        f"PLC请求 seq=99，托盘 {'a' * 32} 数据库中无此箱"
    ]


def test_worker_rejects_illegal_state_without_plc_write():
    protocol = FakeProtocol()
    target = worker([{**ROW, "state": 9}], protocol)
    errors = []
    target.failed.connect(errors.append)

    target.run()

    assert errors == ["seq=7 的 state=9 非法，只允许空值、0、1、2"]
    assert protocol.alarms == []
    assert protocol.normal == []
