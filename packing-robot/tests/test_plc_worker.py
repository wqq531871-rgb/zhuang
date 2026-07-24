from packing_ui.plc_worker import PlcSendWorker


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
    def __init__(self):
        self.normal = []
        self.alarms = []
        self.disconnected = False

    def connect(self):
        return None

    def disconnect(self):
        self.disconnected = True

    def send_normal(self, command):
        self.normal.append(command)

    def send_alarm(self, expected_seq):
        self.alarms.append(expected_seq)


def worker(rows, protocol):
    values = iter(rows)
    return PlcSendWorker(
        config=object(),
        box_unique_id="a" * 32,
        sequences=(7,),
        row_loader=lambda _uid, _seq: next(values),
        client_factory=lambda: object(),
        protocol_factory=lambda *_args, **_kwargs: protocol,
        sleep=lambda _seconds: None,
    )


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


def test_worker_rejects_illegal_state_without_plc_write():
    protocol = FakeProtocol()
    target = worker([{**ROW, "state": 9}], protocol)
    errors = []
    target.failed.connect(errors.append)

    target.run()

    assert errors == ["seq=7 的 state=9 非法，只允许空值、0、1、2"]
    assert protocol.alarms == []
    assert protocol.normal == []
