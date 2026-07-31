from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest


PACKING_ROOT = Path(__file__).resolve().parents[1]
if str(PACKING_ROOT) not in sys.path:
    sys.path.insert(0, str(PACKING_ROOT))


def test_find_wcs_case_in_archives_recovers_deleted_database_case(tmp_path):
    from src.service.wcs_case_archive import find_wcs_case_in_archives

    output = tmp_path / "output" / "success"
    output.mkdir(parents=True)
    wanted = {
        "box_unique_id": "d33ba85e0c414af19ba853da1d995779",
        "case_type": "MH423C",
        "layers": [
            {
                "cartons": [
                    {
                        "length": 420.0,
                        "width": 310.0,
                        "height": 280.0,
                        "product_code": "30081842",
                        "layer_id": 1,
                        "seq": 1,
                    }
                ]
            }
        ],
    }
    archive = output / "packing_plan_20260727_150923_execution_wcs.json"
    archive.write_text(
        json.dumps(
            [
                {
                    "box_unique_id": "some-other-pallet",
                    "case_type": "MH423C",
                    "layers": [],
                },
                wanted,
            ]
        ),
        encoding="utf-8",
    )

    case, source = find_wcs_case_in_archives(
        "d33ba85e0c414af19ba853da1d995779",
        workspace=tmp_path,
    )

    assert case == wanted
    assert source == archive


def test_find_wcs_case_in_archives_reports_uid_when_no_archive_matches(tmp_path):
    from src.service.wcs_case_archive import find_wcs_case_in_archives

    with pytest.raises(ValueError, match="missing-uid"):
        find_wcs_case_in_archives("missing-uid", workspace=tmp_path)
