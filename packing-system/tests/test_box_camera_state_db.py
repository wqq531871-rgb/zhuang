"""Unit tests for camera LWH → state 0/1/2 (no MySQL)."""

from src.service.box_camera_state_db import (
    STATE_MISMATCH,
    STATE_NO_ROTATE,
    STATE_ROTATE_90,
    camera_dims_complete,
    judge_state_from_dims,
)


def test_judge_aligned_same_type_no_rotate():
    assert (
        judge_state_from_dims(400, 300, 200, 400, 300, 200, tol_mm=5) == STATE_NO_ROTATE
    )


def test_judge_swapped_same_type_rotate():
    assert (
        judge_state_from_dims(300, 400, 200, 400, 300, 200, tol_mm=5) == STATE_ROTATE_90
    )


def test_judge_height_mismatch_is_zero():
    assert judge_state_from_dims(400, 300, 250, 400, 300, 200, tol_mm=5) == STATE_MISMATCH


def test_judge_plane_mismatch_is_zero():
    assert judge_state_from_dims(500, 300, 200, 400, 300, 200, tol_mm=5) == STATE_MISMATCH


def test_judge_within_tolerance():
    assert (
        judge_state_from_dims(402, 298, 201, 400, 300, 200, tol_mm=5) == STATE_NO_ROTATE
    )


def test_camera_dims_complete():
    assert camera_dims_complete(1, 2, 3) is True
    assert camera_dims_complete(0, 2, 3) is False
    assert camera_dims_complete(None, 2, 3) is False


def test_apply_rejects_incomplete_without_db(monkeypatch):
    from src.service import box_camera_state_db as mod

    result = mod.apply_camera_dims_and_judge(
        "uid", 1, 0, 10, 10, db_config=object()
    )
    assert result["ok"] is False
    assert result["reason"] == "camera_dims_incomplete"


def test_auto_judge_pending_calls_apply(monkeypatch):
    from src.service import box_camera_state_db as mod

    class FakeRepo:
        def list_camera_ready_unjudged(self, limit=50):
            return [
                {
                    "box_unique_id": "uid1",
                    "seq": 1,
                    "camera_length": 100,
                    "camera_width": 80,
                    "camera_height": 50,
                    "raw_length": 100,
                    "raw_width": 80,
                    "raw_height": 50,
                }
            ]

    calls = []

    def fake_apply(uid, seq, l, w, h, **kwargs):
        calls.append((uid, seq, l, w, h))
        return {"ok": True, "state": 1, "reason": "judged"}

    monkeypatch.setattr(mod, "load_database_config_from_yaml", lambda *a, **k: object())
    monkeypatch.setattr(mod, "WcsCameraStateRepository", lambda cfg: FakeRepo())
    monkeypatch.setattr(mod, "apply_camera_dims_and_judge", fake_apply)

    result = mod.auto_judge_pending_camera_rows()
    assert result["judged"] == 1
    assert calls == [("uid1", 1, 100.0, 80.0, 50.0)]
