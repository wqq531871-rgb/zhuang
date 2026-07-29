from src.service.live_stack_bridge import (
    clear_current_session_after_replan,
    list_selected_pallets,
    read_json,
    session_path,
    write_selected_pallet_session,
)


def test_selecting_new_pallet_does_not_finish_previous_active_pallet(tmp_path):
    write_selected_pallet_session(box_unique_id="old", workspace=tmp_path)
    write_selected_pallet_session(box_unique_id="new", workspace=tmp_path)

    history = list_selected_pallets(tmp_path)

    assert [
        (entry["box_unique_id"], entry["stack_status"]) for entry in history
    ] == [
        ("old", "active"),
        ("new", "active"),
    ]


def test_replan_keeps_unfinished_session_and_history(tmp_path):
    write_selected_pallet_session(box_unique_id="p1", workspace=tmp_path)
    before_session = read_json(session_path(tmp_path))

    clear_current_session_after_replan(tmp_path)

    assert read_json(session_path(tmp_path)) == before_session
    assert list_selected_pallets(tmp_path)[0]["stack_status"] == "active"
