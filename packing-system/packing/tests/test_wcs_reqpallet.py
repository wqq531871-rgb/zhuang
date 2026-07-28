from __future__ import annotations

import sys
from pathlib import Path

import pytest


PACKING_ROOT = Path(__file__).resolve().parents[1]
if str(PACKING_ROOT) not in sys.path:
    sys.path.insert(0, str(PACKING_ROOT))


def _arrival():
    return {
        "robot_id": "5",
        "station_id": "N12X010",
        "pallet_code": "KDDM24170157",
        "case_type": "",
    }


def _wcs_case():
    return {
        "box_index": 7,
        "box_unique_id": "d33ba85e0c414af19ba853da1d995779",
        "case_group": "0",
        "case_type": "MH423C",
        "layers": [
            {
                "cartons": [
                    {
                        "length": 420.0,
                        "width": 310.0,
                        "height": 280.0,
                        "product_code": 30081842,
                        "layer_id": 1,
                        "seq": 1,
                    }
                ]
            },
            {
                "cartons": [
                    {
                        "length": 500.0,
                        "width": 320.0,
                        "height": 300.0,
                        "product_code": 30078992,
                        "layer_id": 2,
                        "seq": 2,
                    }
                ]
            },
        ],
    }


def test_build_reqpallet_payload_uses_46_identity_and_documented_cartons():
    from src.service.wcs_service import build_reqpallet_payload

    payload = build_reqpallet_payload(_arrival(), _wcs_case())

    assert payload == {
        "robot_id": "5",
        "station_id": "N12X010",
        "pallet_code": "KDDM24170157",
        "case_type": "MH423C",
        "empty_flag": False,
        "case_data": [
            {
                "box_index": 7,
                "box_unique_id": "d33ba85e0c414af19ba853da1d995779",
                "case_group": "0",
                "height": 0,
                "layers": [
                    {
                        "cartons": [
                            {
                                "seq": 1,
                                "length": 420.0,
                                "width": 310.0,
                                "height": 280.0,
                                "product_code": "30081842",
                            }
                        ]
                    },
                    {
                        "cartons": [
                            {
                                "seq": 2,
                                "length": 500.0,
                                "width": 320.0,
                                "height": 300.0,
                                "product_code": "30078992",
                            }
                        ]
                    },
                ],
            },
        ],
    }


def test_build_reqpallet_payload_rejects_missing_physical_pallet_or_cases():
    from src.service.wcs_service import build_reqpallet_payload

    missing_pallet = _arrival()
    missing_pallet["pallet_code"] = ""
    with pytest.raises(ValueError, match="pallet_code"):
        build_reqpallet_payload(missing_pallet, _wcs_case())

    empty_case = _wcs_case()
    empty_case["layers"] = []
    with pytest.raises(ValueError, match="case_data"):
        build_reqpallet_payload(_arrival(), empty_case)


def test_push_reqpallet_posts_exact_payload_and_checks_business_code(monkeypatch):
    from src.service import wcs_service

    calls = []

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"code": 0, "msg": "ok", "data": {}}

    def fake_post(url, *, json, timeout, verify):
        calls.append((url, json, timeout, verify))
        return Response()

    monkeypatch.setattr(wcs_service.requests, "post", fake_post)
    payload = {"pallet_code": "KDDM24170157", "empty_flag": False}

    result = wcs_service.push_reqpallet(
        "http://10.222.10.1:8092",
        payload,
        "api/wcs/reqpallet",
        timeout=12,
    )

    assert result == {"code": 0, "msg": "ok", "data": {}}
    assert calls == [
        (
            "http://10.222.10.1:8092/api/wcs/reqpallet",
            payload,
            12,
            False,
        )
    ]


def test_push_reqpallet_rejects_nonzero_wcs_code(monkeypatch):
    from src.service import wcs_service

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"code": 7, "msg": "rejected", "data": {}}

    monkeypatch.setattr(
        wcs_service.requests,
        "post",
        lambda *args, **kwargs: Response(),
    )

    with pytest.raises(RuntimeError, match="code=7"):
        wcs_service.push_reqpallet(
            "http://example.test",
            {"pallet_code": "P1"},
            "/api/wcs/reqpallet",
        )


def test_config_exposes_documented_reqpallet_url():
    from src.service.wcs_service import load_data_source_config

    config_path = PACKING_ROOT.parent / "config" / "packing_config.yaml"
    config = load_data_source_config(config_path)

    assert config.reqpallet_url() == (
        "http://10.222.10.1:8092/api/wcs/reqpallet"
    )
