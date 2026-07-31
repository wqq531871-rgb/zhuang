from packing_ui.live_command import (
    mark_live_pallet_done,
    read_live_pallet_history,
    read_live_session,
    recover_live_session,
    write_live_command,
)


def test_recovers_newest_active_history_when_session_missing(tmp_path):
    history = tmp_path / "history.json"
    session = tmp_path / "session.json"
    write_live_command(
        history,
        [
            {"box_unique_id": "old", "stack_status": "active"},
            {"box_unique_id": "done", "stack_status": "done"},
            {"box_unique_id": "new", "stack_status": "active"},
        ],
    )

    recovered = recover_live_session(session, history)

    assert recovered["box_unique_id"] == "new"
    assert read_live_session(session)["box_unique_id"] == "new"


def test_does_not_recover_completed_history(tmp_path):
    history = tmp_path / "history.json"
    write_live_command(
        history,
        [{"box_unique_id": "p1", "stack_status": "done"}],
    )

    assert recover_live_session(tmp_path / "session.json", history) is None


def test_marks_only_matching_pallet_done_and_clears_matching_session(tmp_path):
    history = tmp_path / "history.json"
    session = tmp_path / "session.json"
    write_live_command(
        history,
        [
            {"box_unique_id": "p1", "stack_status": "active"},
            {"box_unique_id": "p2", "stack_status": "active"},
        ],
    )
    write_live_command(session, {"box_unique_id": "p1"})

    changed = mark_live_pallet_done("p1", session, history)

    assert changed is True
    assert [
        entry["stack_status"] for entry in read_live_pallet_history(history)
    ] == ["done", "active"]
    assert read_live_session(session) is None


def test_finishing_old_pallet_does_not_clear_new_current_session(tmp_path):
    history = tmp_path / "history.json"
    session = tmp_path / "session.json"
    write_live_command(
        history,
        [
            {"box_unique_id": "old", "stack_status": "active"},
            {"box_unique_id": "new", "stack_status": "active"},
        ],
    )
    write_live_command(session, {"box_unique_id": "new"})

    changed = mark_live_pallet_done("old", session, history)

    assert changed is True
    assert read_live_session(session)["box_unique_id"] == "new"
