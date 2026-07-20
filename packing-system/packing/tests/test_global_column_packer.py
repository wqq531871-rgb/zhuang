"""全局列式装箱器(GCP)测试：达标、守恒、门禁、自适应判定、契约。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
try:
    sys.stdout.reconfigure(encoding='utf-8')
except (AttributeError, ValueError):
    pass

from src.config import ConstraintConfig
from src.geometry.constraint_validator import validate_pallet_constraints
from src.packing.global_column_packer import GlobalColumnPacker

PALLET = {'length': 1440.0, 'width': 2240.0, 'height': 720.0}


def _mk(prefix, count, length, width, height, mpm):
    return [
        {
            'id': '%s%d' % (prefix, i), 'length': length, 'width': width,
            'height': height, 'weight': 1.0, 'min_pack_multiple': mpm,
            'is_small_box': False, 'pallet_dims': PALLET,
        }
        for i in range(count)
    ]


def _regular_order():
    """规则单订单：288×(350×265×240)=576 指数 → 3 个满盘（每盘 32 柱×6=192）。"""
    return _mk('A', 288, 350, 265, 240, 2)


def test_contract_and_conservation():
    """pack_group 返回契约 + 守恒 + 门禁。"""
    boxes = _regular_order()
    gcp = GlobalColumnPacker(constraint_config=ConstraintConfig())
    plan, runtime, diag = gcp.pack_group('MH423C', 'T', boxes, 192.0)
    assert isinstance(plan, list) and 'packing' in runtime
    out_ids = [b['id'] for p in plan for b in p['packed_items']]
    assert set(out_ids) == {b['id'] for b in boxes}, '守恒：箱 id 一致'
    assert len(out_ids) == len(boxes), '守恒：无重复无丢失'
    for p in plan:
        assert {'pallet_id', 'pallet_type', 'sales_order_no', 'packed_items',
                'mpm_total', 'mpm_status'} <= set(p.keys())
        g = validate_pallet_constraints(
            {'packed_items': p['packed_items']}, PALLET, constraint_config=ConstraintConfig())
        assert g['is_valid'], f"盘门禁须过：{g['violations'][:2]}"
    print('[PASS] 契约 + 守恒 + 逐盘门禁')


def test_regular_reaches_target():
    """规则单订单应全部达标（单一底面满盘）。"""
    boxes = _regular_order()
    gcp = GlobalColumnPacker(constraint_config=ConstraintConfig())
    plan, _, _ = gcp.pack_group('MH423C', 'T', boxes, 192.0)
    succ = sum(1 for p in plan if p['mpm_status'] == 'SUCCESS')
    assert succ >= 3, f'96 箱应出 3 个达标盘，实际 {succ}'
    print(f'[PASS] 规则单订单达标 {succ} 盘')


def test_suits_group():
    """自适应判定：规则数据 True；底面大指数低的非满柱数据 False。"""
    gcp = GlobalColumnPacker(constraint_config=ConstraintConfig())
    assert gcp.suits_group(_regular_order(), 192.0) is True
    # 底面大、指数低（满盘都不够 192）→ 不适合
    big_low = _mk('B', 40, 700, 530, 240, 4)  # 700×530 满盘根数少 × mpm4 < 192
    assert gcp.suits_group(big_low, 192.0) is False
    print('[PASS] 自适应判定（规则→GCP / 非满柱大底面→回退）')


def test_no_target_returns_plan():
    """无目标指数时仍出盘且守恒（退化为尽量装）。"""
    boxes = _mk('C', 32, 350, 265, 240, 2)
    gcp = GlobalColumnPacker(constraint_config=ConstraintConfig())
    plan, _, _ = gcp.pack_group('MH423C', 'T', boxes, None)
    out_ids = [b['id'] for p in plan for b in p['packed_items']]
    assert set(out_ids) == {b['id'] for b in boxes}
    print('[PASS] 无目标也守恒出盘')


def test_single_box_residual_fallback_is_centered():
    """beam 无法放置残料时，单箱守恒兜底也必须通过重心门禁。"""
    import src.packing.global_column_packer as gcp_module

    class NoFitPacker:
        def __init__(self, pallet_dims, constraint_config=None):
            self.size_tolerance = 2.0
            self.z_tolerance = 0.0
            self.robot_reachability_enabled = False

        def pack(self, *args, **kwargs):
            return [], []

    cfg = ConstraintConfig(suction_reachability_enabled=False)
    boxes = _mk('S', 1, 350, 265, 240, 2)
    original = gcp_module.BeamSearchPacker
    gcp_module.BeamSearchPacker = NoFitPacker
    try:
        plan, _, _ = GlobalColumnPacker(cfg).pack_group(
            'MH423C', 'T', boxes, 192.0
        )
    finally:
        gcp_module.BeamSearchPacker = original

    assert len(plan) == 1
    assert [item['id'] for item in plan[0]['packed_items']] == ['S0']
    gate = validate_pallet_constraints(
        plan[0], PALLET, constraint_config=cfg,
        target_mpm=plan[0]['mpm_target'],
    )
    assert gate['is_valid'], gate['violations']


def test_column_candidates_cover_three_strategies_and_conserve_boxes():
    from src.packing.global_column_packer import _build_column_candidates

    pallet = {'length': 300.0, 'width': 200.0, 'height': 10.0}
    boxes = [
        *_mk('A', 1, 100, 100, 6, 1),
        *_mk('B', 1, 100, 100, 6, 100),
        *_mk('C', 1, 100, 100, 4, 90),
        *_mk('D', 1, 100, 100, 4, 2),
    ]
    for box in boxes:
        box['pallet_dims'] = pallet

    candidates = _build_column_candidates(boxes, pallet, 192.0)

    assert {name for name, _ in candidates} == {
        'height_first',
        'index_balanced',
        'target_concentrated',
    }
    expected_ids = sorted(box['id'] for box in boxes)
    signatures = set()
    for _name, columns in candidates:
        actual_ids = sorted(
            box['id'] for column in columns for box in column['boxes']
        )
        assert actual_ids == expected_ids
        signatures.add(tuple(sorted(
            tuple(sorted(box['id'] for box in column['boxes']))
            for column in columns
        )))
    assert len(signatures) >= 2


def test_pack_group_evaluates_candidates_and_selects_best_rank(monkeypatch):
    import src.packing.global_column_packer as gcp_module

    boxes = _mk('Q', 1, 100, 100, 100, 1)
    candidates = [
        ('height_first', [{'token': 'height'}]),
        ('index_balanced', [{'token': 'balanced'}]),
        ('target_concentrated', [{'token': 'concentrated'}]),
    ]
    monkeypatch.setattr(
        gcp_module,
        '_build_column_candidates',
        lambda *_args, **_kwargs: candidates,
        raising=False,
    )
    monkeypatch.setattr(
        gcp_module,
        '_gcp_candidate_passes_gates',
        lambda *_args, **_kwargs: True,
        raising=False,
    )
    gcp = GlobalColumnPacker(constraint_config=ConstraintConfig())
    calls = []

    def fake_pack(
        pallet_type,
        sales_order_no,
        boxes_in_group,
        target_mpm,
        columns,
        strategy_name,
    ):
        calls.append(strategy_name)
        successes = {
            'height_first': 0,
            'index_balanced': 1,
            'target_concentrated': 2,
        }[strategy_name]
        plans = [
            {
                'packed_items': [],
                'mpm_total': 192.0,
                'mpm_status': 'SUCCESS',
            }
            for _ in range(successes)
        ]
        return plans, {'packing': 0.01}, {'strategy': strategy_name}

    monkeypatch.setattr(gcp, '_pack_group_with_columns', fake_pack, raising=False)

    plan, _runtime, diag = gcp.pack_group('MH423C', 'T', boxes, 192.0)

    assert calls == [
        'height_first',
        'index_balanced',
        'target_concentrated',
    ]
    assert len(plan) == 2
    assert diag['gcp_selected_column_strategy'] == 'target_concentrated'
    assert [
        item['strategy'] for item in diag['gcp_column_candidates']
    ] == calls


def test_pack_group_rejects_higher_ranked_candidate_that_fails_gates(
    monkeypatch,
):
    import src.packing.global_column_packer as gcp_module

    boxes = _mk('G', 1, 100, 100, 100, 1)
    candidates = [
        ('height_first', [{'token': 'height'}]),
        ('target_concentrated', [{'token': 'concentrated'}]),
    ]
    monkeypatch.setattr(
        gcp_module,
        '_build_column_candidates',
        lambda *_args, **_kwargs: candidates,
    )
    monkeypatch.setattr(
        gcp_module,
        '_gcp_candidate_passes_gates',
        lambda _boxes, plans, _config: plans[0]['candidate_valid'],
        raising=False,
    )
    gcp = GlobalColumnPacker(constraint_config=ConstraintConfig())

    def fake_pack(
        pallet_type,
        sales_order_no,
        boxes_in_group,
        target_mpm,
        columns,
        strategy_name,
    ):
        success_count = 1 if strategy_name == 'height_first' else 2
        plans = [
            {
                'packed_items': [],
                'mpm_total': 192.0,
                'mpm_status': 'SUCCESS',
                'candidate_valid': strategy_name == 'height_first',
            }
            for _ in range(success_count)
        ]
        return plans, {'packing': 0.01}, {'gcp_bailout': False}

    monkeypatch.setattr(gcp, '_pack_group_with_columns', fake_pack)

    plan, _runtime, diag = gcp.pack_group('MH423C', 'T', boxes, 192.0)

    assert len(plan) == 1
    assert diag['gcp_selected_column_strategy'] == 'height_first'
    status = {
        item['strategy']: item['gates_passed']
        for item in diag['gcp_column_candidates']
    }
    assert status == {
        'height_first': True,
        'target_concentrated': False,
    }

if __name__ == '__main__':
    test_contract_and_conservation()
    test_regular_reaches_target()
    test_suits_group()
    test_no_target_returns_plan()
    print('\n[PASS] 所有 GCP 测试通过！')
