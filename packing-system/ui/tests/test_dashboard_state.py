from dashboard_state import (
    apply_download_interval,
    normalize_download_interval,
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
