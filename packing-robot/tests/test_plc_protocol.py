import struct

import pytest

from packing_ui.plc_protocol import (
    ALARM_OFFSET,
    DH_OVER_OFFSET,
    FP_OFFSET,
    PlcSequenceMismatch,
    S7Client,
    S7Config,
    build_command,
    pack_int,
)


ROW = {
    "seq": 7,
    "camera_length": 401.2,
    "camera_width": 301.6,
    "camera_height": 202.5,
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


def status(
    *,
    fp=1,
    seq=7,
    fp_over=0,
    camera_length=401,
    camera_width=302,
    camera_height=203,
    idle=0,
    dh_over=0,
):
    return {
        "fp": fp,
        "request_seq": seq,
        "fp_over": fp_over,
        "camera_length": camera_length,
        "camera_width": camera_width,
        "camera_height": camera_height,
        "idle": idle,
        "dh_over": dh_over,
    }


class FakeSnap7:
    def __init__(self, statuses):
        self.statuses = list(statuses)
        self.index = 0
        self.writes = []
        self.connected = True

    def get_connected(self):
        return self.connected

    def connect(self, *_args):
        self.connected = True

    def disconnect(self):
        self.connected = False

    def db_read(self, _db, start, size):
        current = self.statuses[min(self.index, len(self.statuses) - 1)]
        if start == 0 and size == 14:
            words = [
                current["fp"],
                current["request_seq"],
                current["fp_over"],
                current["camera_length"],
                current["camera_width"],
                current["camera_height"],
                current["idle"],
            ]
            return bytearray(struct.pack(">hhhhhhh", *words))
        if start == DH_OVER_OFFSET and size == 2:
            self.index += 1
            return bytearray(pack_int(current["dh_over"]))
        raise AssertionError((start, size))

    def db_write(self, db, start, data):
        self.writes.append((db, start, bytes(data)))


def config():
    return S7Config(handshake_timeout=1, poll_interval=0.001)


def test_default_plc_endpoint_matches_site_controller():
    value = S7Config()
    assert value.ip == "10.19.40.70"
    assert value.port == 102


def test_wait_request_reads_camera_dimensions_from_send_area():
    raw = FakeSnap7([status()])
    received = S7Client(
        raw, config(), sleep=lambda _seconds: None
    ).wait_request(7)
    assert (
        received.camera_length,
        received.camera_width,
        received.camera_height,
    ) == (401, 302, 203)


def test_command_writes_only_rev_fields_and_preserves_dbw34_int():
    command = build_command(ROW)
    assert command.words() == {
        14: 400,
        16: 300,
        18: 200,
        20: 110,
        22: 100,
        24: 120,
        26: 2,
        28: 12,
        32: 0,
        34: 480,
    }
    assert {6, 8, 10}.isdisjoint(command.words())
    assert 2 not in command.words()


def test_normal_send_rejects_wrong_plc_sequence_without_writes():
    raw = FakeSnap7([status(seq=8)])
    with pytest.raises(
        PlcSequenceMismatch, match="PLC请求 seq=8，当前数据库箱子 seq=7"
    ):
        S7Client(raw, config(), sleep=lambda _seconds: None).send_normal(
            build_command(ROW)
        )
    assert raw.writes == []


def test_normal_send_uses_new_ack_offsets_and_clears_after_fp_over():
    raw = FakeSnap7(
        [
            status(fp=1, fp_over=0, dh_over=0),
            status(fp=1, fp_over=1, dh_over=1),
            status(fp=0, fp_over=0, dh_over=0),
        ]
    )
    client = S7Client(raw, config(), sleep=lambda _seconds: None)
    client.send_normal(build_command(ROW))

    starts = [start for _db, start, _data in raw.writes]
    assert starts[-3:] == [DH_OVER_OFFSET, FP_OFFSET, DH_OVER_OFFSET]
    assert raw.writes[-3][2] == pack_int(1)
    assert raw.writes[-2][2] == pack_int(0)
    assert raw.writes[-1][2] == pack_int(0)


def test_state_zero_writes_only_alarm_word():
    raw = FakeSnap7([status(seq=7)])
    S7Client(raw, config(), sleep=lambda _seconds: None).send_alarm(expected_seq=7)
    assert raw.writes == [(19, ALARM_OFFSET, pack_int(1))]
