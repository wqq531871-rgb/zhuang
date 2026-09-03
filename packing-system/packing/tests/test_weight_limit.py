"""托盘整体限重（甲方 2026-09 需求）：取值、校验、上界判定与各层集成测试。"""

import sys
from pathlib import Path

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from src.config.constraint_config import ConstraintConfig
from src.geometry.constraint_validator import validate_pallet_constraints
from src.geometry.weight_limit import (
    DEFAULT_MAX_PALLET_WEIGHT_KG,
    box_weight,
    check_pallet_weight,
    column_weight,
    fits_weight,
    items_total_weight,
    max_possible_pallet_weight,
    overweight_single_boxes,
    pallet_weight_cap,
    weight_cap_for_group,
)
from src.packing.beam_search_packer import BeamSearchPacker
from src.packing.global_column_packer import GlobalColumnPacker
from src.packing.incremental_gate import incremental_pallet_ok
from src.packing.layered_packer import _ffd_columns

PALLET = {'length': 1440.0, 'width': 2240.0, 'height': 720.0}
NO_SUCTION = ConstraintConfig(suction_reachability_enabled=False)


def _box(box_id, weight, length=350, width=265, height=240, mpm=2.0,
         order='SO1'):
    return {
        'id': str(box_id),
        'type': f'T{length}x{width}x{height}',
        'length': float(length),
        'width': float(width),
        'height': float(height),
        'weight': float(weight),
        'min_pack_multiple': float(mpm),
        'pallet_type': 'MH423C',
        'sales_order_no': order,
        'pallet_dims': dict(PALLET),
    }


def _placed(box_id, x, y, z, weight, length=350, width=265, height=240,
            mpm=2.0):
    return {
        'id': str(box_id),
        'position': {'x': float(x), 'y': float(y), 'z': float(z)},
        'raw_length': float(length),
        'raw_width': float(width),
        'raw_height': float(height),
        'length': float(length),
        'width': float(width),
        'height': float(height),
        'weight': float(weight),
        'min_pack_multiple': float(mpm),
        'pallet_type': 'MH423C',
    }


class TestWeightPrimitives:
    def test_missing_weight_field_counts_as_zero(self):
        assert box_weight({}) == 0.0
        assert box_weight({'weight': None}) == 0.0
        assert items_total_weight([{}, {'weight': 2.5}]) == 2.5

    def test_cap_defaults_and_disable_switch(self):
        assert pallet_weight_cap(None) == DEFAULT_MAX_PALLET_WEIGHT_KG
        assert pallet_weight_cap(ConstraintConfig()) == 1000.0
        assert pallet_weight_cap(
            ConstraintConfig(max_pallet_weight_kg=0.0)
        ) is None
        assert pallet_weight_cap(
            ConstraintConfig(max_pallet_weight_kg=-1.0)
        ) is None

    def test_config_from_dict_reads_the_key(self):
        cfg = ConstraintConfig.from_dict({'max_pallet_weight_kg': 750.0})
        assert cfg.max_pallet_weight_kg == 750.0
        assert pallet_weight_cap(cfg) == 750.0

    def test_fits_weight_is_none_safe(self):
        assert fits_weight([_placed(1, 0, 0, 0, 900)], 500.0, None)
        assert not fits_weight([_placed(1, 0, 0, 0, 900)], 500.0, 1000.0)
        assert fits_weight([_placed(1, 0, 0, 0, 900)], 100.0, 1000.0)

    def test_column_weight_sums_boxes(self):
        col = {'boxes': [_box(1, 3.0), _box(2, 4.5)]}
        assert column_weight(col) == 7.5


class TestPalletWeightCheck:
    def test_under_and_at_limit_pass(self):
        items = [_placed(1, 0, 0, 0, 500), _placed(2, 400, 0, 0, 500)]
        assert check_pallet_weight(items, 1000.0) is None

    def test_over_limit_reports_excess(self):
        items = [_placed(1, 0, 0, 0, 600), _placed(2, 400, 0, 0, 600)]
        violation = check_pallet_weight(items, 1000.0)
        assert violation is not None
        assert violation['total_kg'] == 1200.0
        assert violation['excess_kg'] == 200.0
        assert violation['box_count'] == 2

    def test_single_box_over_limit_is_exempt(self):
        """单箱超限＝数据异常，重排无解；拦下会让守恒兜底无处安放该箱。"""
        assert check_pallet_weight([_placed(1, 0, 0, 0, 5000)], 1000.0) is None

    def test_disabled_cap_never_reports(self):
        items = [_placed(i, 0, 0, 0, 900) for i in range(5)]
        assert check_pallet_weight(items, None) is None

    def test_overweight_single_boxes_listing(self):
        boxes = [_box(1, 5.0), _box(2, 1500.0), _box(3, 1200.0)]
        heavy = overweight_single_boxes(boxes, 1000.0)
        assert [b['id'] for b in heavy] == ['2', '3']
        assert overweight_single_boxes(boxes, None) == []


class TestBindingBound:
    """单盘重量上界必须可靠（不得低估），且足够紧以便对轻数据完全短路。"""

    def test_light_group_is_non_binding(self):
        boxes = [_box(i, 0.8) for i in range(600)]
        assert weight_cap_for_group(boxes, PALLET, ConstraintConfig()) is None

    def test_heavy_group_is_binding(self):
        boxes = [_box(i, 60.0) for i in range(200)]
        assert weight_cap_for_group(
            boxes, PALLET, ConstraintConfig()
        ) == 1000.0

    def test_bound_never_underestimates_a_full_pallet(self):
        # 一盘最多放 4×8×3 = 96 只 350×265×240 箱；上界不得低于其重量
        boxes = [_box(i, 20.0) for i in range(400)]
        bound = max_possible_pallet_weight(boxes, PALLET)
        assert bound >= 96 * 20.0 - 1e-6

    def test_bound_is_total_weight_when_everything_fits(self):
        boxes = [_box(i, 3.0) for i in range(4)]
        assert max_possible_pallet_weight(boxes, PALLET) == 12.0

    def test_zero_volume_box_forces_binding(self):
        boxes = [_box(1, 5.0, length=0, width=0, height=0)]
        assert max_possible_pallet_weight(boxes, PALLET) == float('inf')

    def test_disabled_cap_short_circuits(self):
        boxes = [_box(i, 60.0) for i in range(200)]
        cfg = ConstraintConfig(max_pallet_weight_kg=0.0)
        assert weight_cap_for_group(boxes, PALLET, cfg) is None


class TestGateIntegration:
    def _pallet(self, weights):
        items = []
        for i, w in enumerate(weights):
            items.append(_placed(i, (i % 4) * 350.0, (i // 4) * 265.0, 0.0, w))
        return {'packed_items': items, 'pallet_type': 'MH423C'}

    def test_gate_rejects_overweight_pallet(self):
        plan = self._pallet([300.0] * 4)  # 1200kg
        result = validate_pallet_constraints(
            plan, PALLET, constraint_config=NO_SUCTION,
        )
        assert not result['is_valid']
        kinds = {v['type'] for v in result['violations']}
        assert 'pallet_overweight' in kinds

    def test_gate_passes_within_limit(self):
        plan = self._pallet([200.0] * 4)  # 800kg
        result = validate_pallet_constraints(
            plan, PALLET, constraint_config=NO_SUCTION,
        )
        kinds = {v['type'] for v in result['violations']}
        assert 'pallet_overweight' not in kinds

    def test_gate_exempts_single_box_pallet(self):
        plan = self._pallet([5000.0])
        result = validate_pallet_constraints(
            plan, PALLET, constraint_config=NO_SUCTION,
        )
        kinds = {v['type'] for v in result['violations']}
        assert 'pallet_overweight' not in kinds

    def test_gate_switch_off_restores_legacy(self):
        plan = self._pallet([300.0] * 4)
        cfg = ConstraintConfig(
            suction_reachability_enabled=False, max_pallet_weight_kg=0.0,
        )
        result = validate_pallet_constraints(
            plan, PALLET, constraint_config=cfg,
        )
        kinds = {v['type'] for v in result['violations']}
        assert 'pallet_overweight' not in kinds

    def test_boxes_without_weight_field_unaffected(self):
        items = [
            {
                'id': str(i), 'position': {'x': i * 350.0, 'y': 0.0, 'z': 0.0},
                'length': 350.0, 'width': 265.0, 'height': 240.0,
                'raw_length': 350.0, 'raw_width': 265.0, 'raw_height': 240.0,
                'min_pack_multiple': 2.0, 'pallet_type': 'MH423C',
            }
            for i in range(4)
        ]
        result = validate_pallet_constraints(
            {'packed_items': items}, PALLET, constraint_config=NO_SUCTION,
        )
        kinds = {v['type'] for v in result['violations']}
        assert 'pallet_overweight' not in kinds


class TestIncrementalGate:
    def test_incremental_rejects_overweight_addition(self):
        placed = [_placed(1, 0.0, 0.0, 0.0, 900.0)]
        new_box = _placed(2, 350.0, 0.0, 0.0, 200.0)
        assert not incremental_pallet_ok(
            new_box, placed, PALLET, constraint_config=NO_SUCTION,
        )

    def test_incremental_allows_within_limit(self):
        placed = [_placed(1, 0.0, 0.0, 0.0, 500.0)]
        new_box = _placed(2, 350.0, 0.0, 0.0, 200.0)
        assert incremental_pallet_ok(
            new_box, placed, PALLET, constraint_config=NO_SUCTION,
        )

    def test_incremental_off_switch(self):
        cfg = ConstraintConfig(
            suction_reachability_enabled=False, max_pallet_weight_kg=0.0,
        )
        placed = [_placed(1, 0.0, 0.0, 0.0, 900.0)]
        new_box = _placed(2, 350.0, 0.0, 0.0, 200.0)
        assert incremental_pallet_ok(
            new_box, placed, PALLET, constraint_config=cfg,
        )


class TestColumnFormation:
    def test_ffd_columns_respect_weight_cap(self):
        # 3 只 400kg 的 350×265×240 箱：高度允许 3 只成柱，限重只允许 2 只
        boxes = [_box(i, 400.0) for i in range(3)]
        by_height = _ffd_columns(boxes, 720.0)
        assert [len(c) for c in by_height] == [3]
        capped = _ffd_columns(boxes, 720.0, weight_cap=1000.0)
        assert sorted(len(c) for c in capped) == [1, 2]
        for col in capped:
            assert items_total_weight(col) <= 1000.0 + 1e-6

    def test_ffd_columns_unchanged_without_cap(self):
        boxes = [_box(i, 0.8) for i in range(6)]
        assert (
            [len(c) for c in _ffd_columns(boxes, 720.0)]
            == [len(c) for c in _ffd_columns(boxes, 720.0, weight_cap=1000.0)]
        )


class TestBeamPackerWeight:
    """一盘满载 96 只 350×265×240；20kg/只 ⇒ 满盘 1920kg，限重砍到 ≤ 50 只。"""

    def _boxes(self):
        return [_box(i, 20.0) for i in range(96)]

    def test_beam_stops_adding_at_weight_limit(self):
        packer = BeamSearchPacker(
            pallet_dims=PALLET, constraint_config=NO_SUCTION,
        )
        assert packer.max_pallet_weight == 1000.0
        packed, unfitted = packer.pack(
            self._boxes(), target_mpm=None, num_restarts=2, beam_width=2,
            candidate_limit=12,
        )
        assert packed
        assert items_total_weight(packed) <= 1000.0 + 1e-6
        assert unfitted  # 装不下的箱留给下一盘，不丢

    def test_beam_ignores_weight_when_disabled(self):
        cfg = ConstraintConfig(
            suction_reachability_enabled=False, max_pallet_weight_kg=0.0,
        )
        packer = BeamSearchPacker(pallet_dims=PALLET, constraint_config=cfg)
        assert packer.max_pallet_weight is None
        packed, _unfitted = packer.pack(
            self._boxes(), target_mpm=None, num_restarts=2, beam_width=2,
            candidate_limit=12,
        )
        assert items_total_weight(packed) > 1000.0

    def test_beam_conserves_every_box(self):
        packer = BeamSearchPacker(
            pallet_dims=PALLET, constraint_config=NO_SUCTION,
        )
        boxes = self._boxes()
        packed, unfitted = packer.pack(
            boxes, target_mpm=None, num_restarts=2, beam_width=2,
            candidate_limit=12,
        )
        assert (
            sorted(b['id'] for b in packed + unfitted)
            == sorted(b['id'] for b in boxes)
        )


class TestGcpEndToEnd:
    """限重必须在 ILP 里精确入模，而不是造完盘再拒。

    构造：同底面、同指数、重量悬殊的两种箱（轻 5kg / 重 30kg，各 48 只，
    指数均 4）。总指数 384 ⇒ 理论 2 个达标盘。
    - 若按"一种箱凑一盘"（历史行为）：重箱盘 48×30 = 1440kg，超限；
    - 达标且不超限**只能靠混装**：k 只重箱 + (48-k) 只轻箱 = 240+25k ≤ 1000
      ⇒ k ≤ 30。两盘各分一半重箱（8 根重柱）即可 ⇒ 达标率不掉。
    限重进 pattern 枚举（柱重并入柱类型键）才能拿到这个解。
    """

    def _mixed_boxes(self):
        light = [
            _box(f'L{i}', 5.0, mpm=4.0) for i in range(48)
        ]
        heavy = [
            _box(f'H{i}', 30.0, mpm=4.0) for i in range(48)
        ]
        return light + heavy

    def test_ilp_mixes_light_and_heavy_to_keep_both_pallets_achieved(self):
        boxes = self._mixed_boxes()
        gcp = GlobalColumnPacker(constraint_config=NO_SUCTION)
        plans, _runtime, diag = gcp.pack_group('MH423C', 'SO1', boxes, 192.0)
        assert plans
        assert not diag.get('gcp_bailout')

        packed_ids = [
            item['id'] for plan in plans for item in plan['packed_items']
        ]
        assert sorted(packed_ids) == sorted(b['id'] for b in boxes)

        for plan in plans:
            items = plan['packed_items']
            if len(items) > 1:
                assert items_total_weight(items) <= 1000.0 + 1e-6, (
                    plan['pallet_id'], items_total_weight(items)
                )
            gate = validate_pallet_constraints(
                plan, PALLET, constraint_config=NO_SUCTION,
                target_mpm=plan.get('mpm_target'),
            )
            assert gate['is_valid'], gate['violations'][:3]

        success = [p for p in plans if p['mpm_status'] == 'SUCCESS']
        assert len(success) == 2, [
            (p['mpm_status'], p['mpm_total'],
             items_total_weight(p['packed_items'])) for p in plans
        ]
        # 每个达标盘都必须是混装的（纯重箱盘超限、纯轻箱只有 48 只）
        for plan in success:
            weights = {item['weight'] for item in plan['packed_items']}
            assert weights == {5.0, 30.0}

    def test_without_cap_the_same_input_would_go_overweight(self):
        """对照组：关掉限重，同一输入会造出超过 1000kg 的盘。"""
        cfg = ConstraintConfig(
            suction_reachability_enabled=False, max_pallet_weight_kg=0.0,
        )
        gcp = GlobalColumnPacker(constraint_config=cfg)
        plans, _runtime, _diag = gcp.pack_group(
            'MH423C', 'SO1', self._mixed_boxes(), 192.0,
        )
        assert any(
            items_total_weight(p['packed_items']) > 1000.0 for p in plans
        )

    def test_light_group_unaffected_by_the_constraint(self):
        """轻数据：开/关限重的方案逐盘一致（零回归）。"""
        def _run(cfg):
            boxes = [
                _box(i, 0.9, length=350, width=265, height=240, mpm=4.0)
                for i in range(96)
            ]
            gcp = GlobalColumnPacker(constraint_config=cfg)
            plans, _rt, _dg = gcp.pack_group('MH423C', 'SO1', boxes, 192.0)
            return [
                (p['mpm_status'], p['mpm_total'],
                 sorted(i['id'] for i in p['packed_items']))
                for p in plans
            ]

        off = ConstraintConfig(
            suction_reachability_enabled=False, max_pallet_weight_kg=0.0,
        )
        assert _run(NO_SUCTION) == _run(off)
