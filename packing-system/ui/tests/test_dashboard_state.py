import pytest

from dashboard_state import (
    RUN_MODE_OPTIONS,
    apply_download_interval,
    list_success_pallets,
    normalize_download_interval,
    regular_irregular_box_counts,
    run_mode_policy,
    successful_pallet_count,
)


def test_successful_pallet_count_uses_all_status_values_case_insensitively():
    pallets = [
        {"mpm_status": "SUCCESS"},
        {"mpm_status": "success"},
        {"mpm_status": "FAILED"},
        {},
    ]

    assert successful_pallet_count(pallets) == 2


def test_regular_irregular_box_counts_matches_integer_multiple_specs_across_pallets():
    pallets = [
        {
            "packed_items": [
                {"original_length": 100, "original_width": 80, "original_height": 50},
                {"original_length": 100, "original_width": 80, "original_height": 50},
            ]
        },
        {
            "packed_items": [
                {"original_length": 200, "original_width": 160, "original_height": 100},
                {"original_length": 150, "original_width": 120, "original_height": 80},
                {"original_length": 150, "original_width": 120, "original_height": 80},
            ]
        },
    ]

    assert regular_irregular_box_counts(pallets) == (3, 2)


def test_regular_irregular_box_counts_prefers_original_dimensions_over_gap_dimensions():
    pallets = [
        {
            "packed_items": [
                {
                    "length": 102,
                    "width": 82,
                    "height": 50,
                    "original_length": 100,
                    "original_width": 80,
                    "original_height": 50,
                },
                {
                    "length": 202,
                    "width": 162,
                    "height": 100,
                    "original_length": 200,
                    "original_width": 160,
                    "original_height": 100,
                },
            ]
        }
    ]

    assert regular_irregular_box_counts(pallets) == (2, 0)


def test_regular_irregular_box_counts_treats_invalid_and_unmatched_boxes_as_irregular():
    pallets = [
        {
            "packed_items": [
                {"raw_length": 100, "raw_width": 80, "raw_height": 50},
                {"length": 0, "width": 80, "height": 50},
                {"length": "bad", "width": 80, "height": 50},
            ]
        }
    ]

    assert regular_irregular_box_counts(pallets) == (0, 3)


def test_regular_irregular_box_counts_accepts_small_float_rounding_noise():
    pallets = [
        {
            "packed_items": [
                {"length": 100, "width": 80, "height": 50},
                {"length": 200.00000001, "width": 160, "height": 100},
            ]
        }
    ]

    assert regular_irregular_box_counts(pallets) == (2, 0)


def test_list_success_pallets_requires_success_status_and_pallet_id():
    pallets = [
        {"pallet_id": "A-1", "mpm_status": "SUCCESS"},
        {"pallet_id": "A-2", "mpm_status": "success"},
        {"pallet_id": "B-1", "mpm_status": "FAILED"},
        {"pallet_id": "", "mpm_status": "SUCCESS"},
        {"mpm_status": "SUCCESS"},
    ]
    ids = [p["pallet_id"] for p in list_success_pallets(pallets)]
    assert ids == ["A-1", "A-2"]


def test_download_interval_normalizes_valid_values_and_invalid_fallbacks():
    assert normalize_download_interval("360") == 360
    assert normalize_download_interval(1) == 1
    assert normalize_download_interval(86400) == 86400
    assert normalize_download_interval(None) == 200
    assert normalize_download_interval("bad") == 200
    assert normalize_download_interval(0) == 200
    assert normalize_download_interval(86401) == 200


def test_apply_download_interval_preserves_existing_data_source_settings():
    config = {
        "data_source": {
            "mode": "api",
            "api_base_url": "http://example.test",
        }
    }

    interval = apply_download_interval(config, 15)

    assert interval == 15
    assert config["data_source"] == {
        "mode": "api",
        "api_base_url": "http://example.test",
        "download_interval": 15,
    }


def test_run_mode_options_are_presented_in_the_approved_order():
    assert RUN_MODE_OPTIONS == (
        ("接口持续运行", "continuous"),
        ("接口单次运行", "once"),
        ("Excel 单次运行", "excel"),
        ("接口运行至成功", "until-success"),
    )


@pytest.mark.parametrize(
    ("mode", "uses_api", "uses_interval", "uses_excel"),
    [
        ("continuous", True, True, False),
        ("once", True, False, False),
        ("excel", False, False, True),
        ("until-success", True, True, False),
    ],
)
def test_run_mode_policy_controls_related_inputs(
    mode, uses_api, uses_interval, uses_excel
):
    policy = run_mode_policy(mode)
    assert policy.uses_api is uses_api
    assert policy.uses_interval is uses_interval
    assert policy.uses_excel is uses_excel


def test_run_mode_policy_rejects_unknown_mode():
    with pytest.raises(ValueError, match="未知运行方式"):
        run_mode_policy("unknown")
