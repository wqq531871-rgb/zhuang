"""Unit tests for PLC command construction (no MySQL)."""

from src.service.plc_queue_db import build_plc_command_from_box_row


def test_build_plc_command_from_box_row():
    cmd = build_plc_command_from_box_row(
        {
            "box_unique_id": "abc",
            "seq": 3,
            "raw_length": 390.0,
            "raw_width": 335.0,
            "raw_height": 240.0,
            "pos_x": 10.0,
            "pos_y": 20.0,
            "pos_z": 0.0,
            "state": 2,
            "product_code": "9001",
            "stack_height_before": 0,
        }
    )
    assert cmd["dbw0_length"] == 390
    assert cmd["dbw2_width"] == 335
    assert cmd["dbw4_height"] == 240
    assert cmd["dbw6_pos_x"] == 10
    assert cmd["dbw8_pos_y"] == 20
    assert cmd["dbw10_top_z"] == 240
    assert cmd["dbw12_state"] == 2
    assert cmd["dbw16_seq"] == 3
    assert cmd["box_unique_id"] == "abc"


def test_stub_send_rejects_out_of_order(monkeypatch):
    from src.service import plc_queue_db as mod

    class FakeRepo:
        def get_by_id(self, queue_id):
            return {
                "id": queue_id,
                "box_unique_id": "uid1",
                "seq": 2,
                "status": "pending",
                "state": 1,
                "command": {},
            }

        def next_required_seq(self, box_unique_id):
            assert box_unique_id == "uid1"
            return 1

        def mark_sent_stub(self, queue_id, note=""):
            raise AssertionError("不应发送乱序箱")

    monkeypatch.setattr(mod, "load_database_config_from_yaml", lambda *a, **k: object())
    monkeypatch.setattr(mod, "WcsPlcQueueRepository", lambda cfg: FakeRepo())
    result = mod.stub_send_plc_command(99)
    assert result["ok"] is False
    assert result["reason"] == "out_of_order"
    assert result["required_seq"] == 1
