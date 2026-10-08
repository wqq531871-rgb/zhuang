import importlib.util
from copy import deepcopy

from src.config.constraint_config import ConstraintConfig
from src.main.shape_polisher import ShapePolisher
from src.main import shape_polisher


def test_shape_polisher_is_available():
    """达标盘应有可选的轻量外形整理阶段。"""
    assert importlib.util.find_spec("src.main.shape_polisher") is not None


def test_shape_polish_profiles_scale_search_budget():
    assert shape_polisher.shape_polish_profile("fast") == {
        "level": "fast",
        "seconds": 1.0,
        "restarts": 5,
        "beam_width": 2,
        "candidate_limit": 10,
    }
    assert shape_polisher.shape_polish_profile("standard") == {
        "level": "standard",
        "seconds": 3.0,
        "restarts": 10,
        "beam_width": 3,
        "candidate_limit": 16,
    }
    assert shape_polisher.shape_polish_profile("strong") == {
        "level": "strong",
        "seconds": 8.0,
        "restarts": 20,
        "beam_width": 4,
        "candidate_limit": 24,
    }
    assert shape_polisher.shape_polish_profile("unknown")["level"] == "standard"


def test_shape_polisher_rejects_flatter_layout_that_breaks_gap():
    """外形评分更好也不能覆盖严格的箱间紧凑约束。"""
    pallet = {"length": 100.0, "width": 10.0, "height": 20.0}

    def box(box_id, x, z=0.0):
        return {
            "id": box_id,
            "length": 10.0,
            "width": 10.0,
            "height": 5.0,
            "raw_length": 10.0,
            "raw_width": 10.0,
            "raw_height": 5.0,
            "weight": 1.0,
            "min_pack_multiple": 0.2,
            "position": {"x": x, "y": 0.0, "z": z},
            "pallet_dims": pallet,
        }

    original = [
        box("A", 0.0),
        box("B", 10.0),
        box("C", 0.0, z=5.0),
        box("D", 20.0),
    ]
    flatter_but_loose = [
        box("A", 0.0),
        box("B", 10.0),
        box("C", 20.0),
        box("D", 40.0),
    ]
    plan = {"packed_items": deepcopy(original), "mpm_status": "SUCCESS"}
    polisher = ShapePolisher(
        constraint_config=ConstraintConfig(
            suction_reachability_enabled=False,
            center_of_mass_tolerance=1.0,
        ),
        repack_fn=lambda _items, _dims, _deadline: deepcopy(
            flatter_but_loose
        ),
    )

    diagnostics = polisher.polish_plans([plan])

    assert plan["packed_items"] == original
    assert plan["shape_quality"]["polish_applied"] is False
    assert diagnostics["improved"] == 0
