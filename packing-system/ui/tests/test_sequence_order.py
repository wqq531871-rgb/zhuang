from sequence_order import (
    EXECUTION_MODE_LABEL,
    ordered_packed_items,
    sequence_mode_key,
)


def test_playback_uses_seq_and_ignores_legacy_sequence_fields():
    items = [
        {
            "id": "A",
            "seq": 2,
            "robot_packing_sequence": 1,
            "original_packing_sequence": 1,
        },
        {
            "id": "B",
            "seq": 1,
            "robot_packing_sequence": 2,
            "original_packing_sequence": 2,
        },
    ]

    ordered = ordered_packed_items({"packed_items": items})

    assert [item["id"] for item in ordered] == ["B", "A"]
    assert [item["id"] for item in items] == ["A", "B"]


def test_playback_preserves_array_order_when_seq_is_missing_or_invalid():
    items = [
        {"id": "A"},
        {"id": "B", "seq": "invalid"},
    ]

    ordered = ordered_packed_items({"packed_items": items})

    assert [item["id"] for item in ordered] == ["A", "B"]


def test_all_legacy_mode_names_map_to_the_single_execution_mode():
    assert sequence_mode_key(EXECUTION_MODE_LABEL) == "execution"
    assert sequence_mode_key("robot") == "execution"
    assert sequence_mode_key("original") == "execution"
