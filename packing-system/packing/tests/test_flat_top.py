"""平顶不缺角（正常订单）：分类器、形状校验、修剪与门禁/GCP 集成测试。"""

import sys
from pathlib import Path

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from src.config.constraint_config import ConstraintConfig
from src.geometry.constraint_validator import validate_pallet_constraints
from src.geometry.flat_top import (
    check_flat_top_full_perimeter,
    flat_top_group_required,
    flat_top_required_target,
    rects_ring_complete,
    trim_items_to_tail,
)
from src.utils.normal_order import (
    NORMAL_ORDER_FLAG,
    annotate_normal_orders,
    boxes_form_regular_family,
)


def _raw_box(box_id, length, width, height, pallet_type='MH423C',
             order='SO1', mpm=4.0):
    return {
        'id': box_id,
        'type': f'T{length}x{width}x{height}',
        'length': float(length),
        'width': float(width),
        'height': float(height),
        'weight': 1.0,
        'min_pack_multiple': float(mpm),
        'pallet_type': pallet_type,
        'sales_order_no': order,
        'pallet_dims': {'length': 1440.0, 'width': 2240.0, 'height': 720.0},
    }


def _placed(box_id, x, y, z, length, width, height, mpm=4.0, normal=True):
    item = {
        'id': box_id,
        'position': {'x': float(x), 'y': float(y), 'z': float(z)},
        'raw_length': float(length),
        'raw_width': float(width),
        'raw_height': float(height),
        'length': float(length) + 2.0,
        'width': float(width) + 2.0,
        'height': float(height),
        'min_pack_multiple': float(mpm),
        'pallet_type': 'MH423C',
    }
    if normal:
        item[NORMAL_ORDER_FLAG] = True
    return item


def _two_by_two_columns(layers=3, normal=True):
    """2 柱 × layers 层 700×265×240 完整棱柱（平顶、外圈铺满，柱间缝 2mm）。"""
    items = []
    box_id = 0
    for cy, y in enumerate((0.0, 267.0)):
        for layer in range(layers):
            box_id += 1
            items.append(_placed(
                box_id, 0.0, y, layer * 240.0, 700, 265, 240, normal=normal,
            ))
    return items


class TestRegularFamilyClassifier:
    def test_integer_multiple_family_is_regular(self):
        boxes = [
            _raw_box(1, 700, 265, 240),
            _raw_box(2, 350, 530, 120),  # 逐轴比 2 / 2 / 2
        ]
        assert boxes_form_regular_family(boxes)

    def test_single_spec_is_regular(self):
        assert boxes_form_regular_family([_raw_box(1, 700, 265, 120)])

    def test_non_multiple_mix_is_irregular(self):
        boxes = [_raw_box(1, 700, 265, 240), _raw_box(2, 430, 280, 430)]
        assert not boxes_form_regular_family(boxes)

    def test_invalid_dimension_is_irregular(self):
        assert not boxes_form_regular_family([_raw_box(1, 0, 265, 240)])
        assert not boxes_form_regular_family([])

    def test_annotate_scopes_by_order_and_pallet_type(self):
        normal = [_raw_box(i, 700, 265, 240, order='A') for i in (1, 2)]
        mixed = [
            _raw_box(3, 700, 265, 240, order='B'),
            _raw_box(4, 430, 280, 430, order='B'),
        ]
        other_type = [_raw_box(5, 700, 265, 240, 'MH110', order='C')]
        count = annotate_normal_orders(normal + mixed + other_type)
        assert count == 1
        assert all(box[NORMAL_ORDER_FLAG] for box in normal)
        assert not any(box[NORMAL_ORDER_FLAG] for box in mixed)
        assert not any(box[NORMAL_ORDER_FLAG] for box in other_type)

    def test_annotate_disabled_marks_everything_false(self):
        boxes = [_raw_box(1, 700, 265, 240)]
        assert annotate_normal_orders(boxes, enabled=False) == 0
        assert boxes[0][NORMAL_ORDER_FLAG] is False


class TestFlatTopShapeCheck:
    def test_full_prism_is_valid(self):
        result = check_flat_top_full_perimeter(_two_by_two_columns())
        assert result['is_valid'], result['violations']

    def test_uneven_top_is_step_violation(self):
        items = _two_by_two_columns()
        items.append(_placed(99, 0.0, 0.0, 720.0, 700, 265, 240))
        result = check_flat_top_full_perimeter(items)
        kinds = {v['type'] for v in result['violations']}
        assert not result['is_valid']
        assert 'flat_top_step' in kinds

    def test_missing_perimeter_box_is_notch(self):
        # 顶层缺一角：底下两层完整、第三层只剩一柱
        items = [it for it in _two_by_two_columns()
                 if not (it['position']['z'] == 480.0
                         and it['position']['y'] == 267.0)]
        result = check_flat_top_full_perimeter(items)
        kinds = {v['type'] for v in result['violations']}
        assert not result['is_valid']
        assert 'perimeter_notch' in kinds

    def test_middle_layer_wall_hole_is_notch(self):
        # 中间层缺外圈箱（上层由另一柱支撑不了——构造为几何校验用例，
        # 只验证形状判定本身，不管支撑）
        items = [it for it in _two_by_two_columns()
                 if not (it['position']['z'] == 240.0
                         and it['position']['y'] == 267.0)]
        result = check_flat_top_full_perimeter(items)
        assert not result['is_valid']

    def test_seam_within_tolerance_ok(self):
        items = _two_by_two_columns()
        assert check_flat_top_full_perimeter(
            items, seam_tolerance_mm=6.0
        )['is_valid']
        # 缝隙容忍压到 1mm 时，2mm 摆放缝会被判缺口
        assert not check_flat_top_full_perimeter(
            items, seam_tolerance_mm=1.0
        )['is_valid']

    def test_rects_ring_complete(self):
        full = [(0, 0, 700, 265), (0, 267, 700, 265)]
        assert rects_ring_complete(full)
        ragged = [(0, 0, 700, 265), (0, 267, 350, 265)]
        assert not rects_ring_complete(ragged)


class TestTrimToTail:
    def test_trim_keeps_achieved_compliant_substack(self):
        items = _two_by_two_columns()  # 24 指数
        items.append(_placed(99, 0.0, 0.0, 720.0, 700, 265, 240))  # 破坏形状
        kept, removed = trim_items_to_tail(items, target=24.0)
        assert [b['id'] for b in removed] == [99]
        assert len(kept) == 6
        assert check_flat_top_full_perimeter(kept)['is_valid']
        assert sum(b['min_pack_multiple'] for b in kept) >= 24.0

    def test_trim_demotes_to_tail_when_no_compliant_substack(self):
        # 两柱不等高：无合规达标子堆 → 拆到 < target
        items = _two_by_two_columns(layers=2)
        items.append(_placed(99, 0.0, 0.0, 480.0, 700, 265, 240))
        kept, removed = trim_items_to_tail(items, target=20.0)
        total = sum(b['min_pack_multiple'] for b in kept)
        assert total < 20.0
        assert kept and removed


class TestValidatorGateIntegration:
    _dims = {'length': 710.0, 'width': 540.0, 'height': 720.0}

    def _validate(self, items, target=None, plan_extra=None, cfg=None):
        plan = {'packed_items': items}
        if plan_extra:
            plan.update(plan_extra)
        return validate_pallet_constraints(
            plan, self._dims,
            require_suction=False,
            center_of_mass_tolerance=1.0,
            constraint_config=cfg,
            target_mpm=target,
        )

    def test_normal_achieved_ugly_pallet_rejected(self):
        items = _two_by_two_columns()
        items.append(_placed(99, 0.0, 0.0, 720.0, 700, 265, 240, mpm=0.5))
        result = self._validate(items, target=24.0)
        kinds = {v['type'] for v in result['violations']}
        assert 'flat_top_perimeter' in kinds

    def test_normal_achieved_compliant_pallet_passes(self):
        result = self._validate(_two_by_two_columns(), target=24.0)
        assert result['is_valid'], result['violations']

    def test_tail_pallet_exempt(self):
        items = _two_by_two_columns()
        items.append(_placed(99, 0.0, 0.0, 720.0, 700, 265, 240, mpm=0.5))
        result = self._validate(items, target=100.0)  # 未达标 → 尾盘豁免
        kinds = {v['type'] for v in result['violations']}
        assert 'flat_top_perimeter' not in kinds

    def test_unmarked_boxes_keep_legacy_behavior(self):
        items = _two_by_two_columns(normal=False)
        items.append(_placed(99, 0.0, 0.0, 720.0, 700, 265, 240, normal=False))
        result = self._validate(items, target=24.0)
        kinds = {v['type'] for v in result['violations']}
        assert 'flat_top_perimeter' not in kinds

    def test_conservation_fallback_exempt(self):
        items = _two_by_two_columns()
        items.append(_placed(99, 0.0, 0.0, 720.0, 700, 265, 240, mpm=0.5))
        result = self._validate(
            items, target=24.0, plan_extra={'conservation_fallback': True},
        )
        kinds = {v['type'] for v in result['violations']}
        assert 'flat_top_perimeter' not in kinds

    def test_config_switch_off_disables_check(self):
        items = _two_by_two_columns()
        items.append(_placed(99, 0.0, 0.0, 720.0, 700, 265, 240, mpm=0.5))
        cfg = ConstraintConfig(
            flat_top_full_perimeter_enabled=False,
            suction_reachability_enabled=False,
            center_of_mass_tolerance=1.0,
        )
        result = self._validate(items, target=24.0, cfg=cfg)
        kinds = {v['type'] for v in result['violations']}
        assert 'flat_top_perimeter' not in kinds

    def test_target_resolved_from_plan_field(self):
        items = _two_by_two_columns()
        items.append(_placed(99, 0.0, 0.0, 720.0, 700, 265, 240, mpm=0.5))
        result = self._validate(
            items, target=None, plan_extra={'mpm_target': 24.0},
        )
        kinds = {v['type'] for v in result['violations']}
        assert 'flat_top_perimeter' in kinds


class TestGroupRequired:
    def test_group_required_follows_flags_and_scope(self):
        boxes = [_raw_box(i, 700, 265, 240) for i in (1, 2)]
        annotate_normal_orders(boxes)
        cfg = ConstraintConfig()
        assert flat_top_group_required(cfg, 'MH423C', boxes)
        assert not flat_top_group_required(cfg, 'MH110', boxes)
        off = ConstraintConfig(flat_top_full_perimeter_enabled=False)
        assert not flat_top_group_required(off, 'MH423C', boxes)

    def test_required_target_needs_achievement(self):
        items = _two_by_two_columns()
        assert flat_top_required_target(items, None, 24.0, None) == 24.0
        assert flat_top_required_target(items, None, 25.0, None) is None


class TestGcpFlatTopEndToEnd:
    def test_normal_order_gcp_success_pallets_are_compliant(self):
        # 48 箱 700×265×240（mpm=4）：16 根满柱（3 箱/柱）恰好 192 指数，
        # 存在 1400×2120 完美平铺 → 期望达标盘平顶不缺角
        boxes = [_raw_box(i, 700, 265, 240) for i in range(1, 49)]
        annotate_normal_orders(boxes)
        from src.packing.global_column_packer import GlobalColumnPacker
        packer = GlobalColumnPacker(constraint_config=ConstraintConfig())
        plans, _runtime, _diag = packer.pack_group(
            'MH423C', 'SO1', boxes, 192.0,
        )
        out_ids = sorted(
            str(item['id'])
            for plan in plans for item in plan['packed_items']
        )
        assert out_ids == sorted(str(box['id']) for box in boxes)
        success = [p for p in plans if p['mpm_status'] == 'SUCCESS']
        assert success, [p['mpm_total'] for p in plans]
        for plan in success:
            shape = check_flat_top_full_perimeter(plan['packed_items'])
            assert shape['is_valid'], shape['violations'][:3]
