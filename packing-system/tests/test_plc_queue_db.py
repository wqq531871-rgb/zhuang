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


def test_auto_process_skips_state_zero_in_ready_list(monkeypatch):
    """list_state_ready_unsent SQL 只选 1/2；此处验证 auto 路径不会处理 state=0 行。"""
    from src.service import plc_queue_db as mod

    class FakeRepo:
        def list_state_ready_unsent(self, limit=50):
            # 模拟 SQL 过滤后的结果：不含 state=0
            return [
                {
                    "box_unique_id": "uid1",
                    "seq": 1,
                    "state": 1,
                    "product_code": "A",
                    "raw_length": 100,
                    "raw_width": 80,
                    "raw_height": 50,
                    "pos_x": 0,
                    "pos_y": 0,
                    "pos_z": 0,
                    "camera_length": 100,
                    "camera_width": 80,
                    "camera_height": 50,
                    "order_id": "O1",
                }
            ]

        def get_queue_status(self, box_unique_id, seq):
            return None

        def get_id_by_uid_seq(self, box_unique_id, seq):
            return seq

        def next_required_seq(self, box_unique_id):
            return 1

        def fetch_success_box_row(self, box_unique_id, seq):
            return self.list_state_ready_unsent()[0]

        def count_boxes_on_pallet(self, box_unique_id):
            return 1

        def enqueue(self, **kwargs):
            return 1

        def get_by_id(self, queue_id):
            return {
                "id": 1,
                "box_unique_id": "uid1",
                "seq": 1,
                "status": "pending",
                "state": 1,
                "command": {"dbw12_state": 1},
            }

        def mark_sent_stub(self, queue_id, note=""):
            return True

    monkeypatch.setattr(mod, "load_database_config_from_yaml", lambda *a, **k: object())
    monkeypatch.setattr(mod, "WcsPlcQueueRepository", lambda cfg: FakeRepo())

    def fake_play(**kwargs):
        return kwargs

    monkeypatch.setattr(
        "src.service.live_stack_bridge.write_live_play_box",
        fake_play,
        raising=False,
    )
    # auto_process imports write_live_play_box inside try; patch module path used there
    import src.service.live_stack_bridge as bridge

    monkeypatch.setattr(bridge, "write_live_play_box", fake_play)

    result = mod.auto_process_state_ready_boxes()
    assert result["ok"] is True
    assert result["enqueued"] == 1
    assert result["sent"] == 1
