"""「小面积在下」约束单测（放置谓词 + 最终门禁）。

约束语义：任一离地箱子的直接支撑层中不得有投影面积更大的箱子，
即投影面积沿栈自下而上单调不减。对全部箱子生效（不再区分小箱）。
"""
import sys
from pathlib import Path

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from src.utils.helpers import (
    footprint_area,
    passes_footprint_area_below_constraint,
)
from src.geometry.constraint_validator import (
    validate_pallet_constraints,
    REQUIRED_SUCTION_FIELDS,
)
from src.config.constraint_config import ConstraintConfig

PALLET = {'length': 1440, 'width': 2240, 'height': 720}
_SUCTION = {f: 1.0 for f in REQUIRED_SUCTION_FIELDS}


def _box(bid, x, y, z, l, w, h, weight=1.0):
    b = {
        'id': bid, 'position': {'x': x, 'y': y, 'z': z},
        'length': l, 'width': w, 'height': h,
        'raw_length': l, 'raw_width': w, 'raw_height': h,
        'weight': weight, 'min_pack_multiple': 1,
        'pallet_dims': PALLET,
    }
    b.update(_SUCTION)
    return b


def _dims(b):
    return {'length': b['length'], 'width': b['width'], 'height': b['height']}


def _passes(upper, lower_boxes):
    return passes_footprint_area_below_constraint(
        upper, upper['position'], _dims(upper), lower_boxes
    )


def test_smaller_footprint_on_larger_rejected():
    """小底面压大底面 → 拒绝（约束主语义）。"""
    big = _box('big', 0, 0, 0, 700, 530, 240)
    small = _box('small', 0, 0, 240, 350, 530, 240)
    assert _passes(small, [big]) is False
    print('[PASS] 小底面压大底面 → 拒绝')


def test_larger_footprint_on_smaller_ok():
    """大底面跨压两只小底面 → 通过（这是允许的堆法）。"""
    a = _box('a', 0, 0, 0, 350, 530, 240)
    b = _box('b', 352, 0, 0, 350, 530, 240)
    big = _box('big', 0, 0, 240, 700, 530, 240)
    assert _passes(big, [a, b]) is True
    print('[PASS] 大底面压小底面 → 通过')


def test_floor_box_exempt():
    """地面箱免检。"""
    small = _box('small', 0, 0, 0, 175, 265, 120)
    assert _passes(small, []) is True
    print('[PASS] 地面箱 → 通过')


def test_equal_area_ok():
    """面积相等通过（"更大"取严格大于）。"""
    base = _box('base', 0, 0, 0, 350, 530, 120)
    upper = _box('up', 0, 0, 120, 350, 530, 120)
    assert _passes(upper, [base]) is True
    print('[PASS] 等面积叠放 → 通过')


def test_equal_area_rotated_ok():
    """同面积不同朝向通过——面积对 90° 旋转不变。"""
    base = _box('base', 0, 0, 0, 530, 350, 120)
    upper = _box('up', 0, 0, 120, 350, 530, 120)
    assert _passes(upper, [base]) is True
    print('[PASS] 等面积换向叠放 → 通过')


def test_applies_to_every_box_not_only_small():
    """约束对全部箱子生效：不再有"非小箱免检"的豁免。

    改造前：非小箱压更大箱通过（旧约束只看 is_small_box）。
    改造后：一律按投影面积判定。
    """
    big_below = _box('big', 0, 0, 0, 700, 530, 240)
    normal = _box('n', 0, 0, 240, 350, 530, 240)
    assert _passes(normal, [big_below]) is False
    print('[PASS] 非小箱同样受约束')


def test_non_support_layer_ignored():
    """只看直接支撑层：中间有空腔的更大箱不参与判定。"""
    lower = _box('lower', 0, 0, 0, 700, 530, 100)     # 顶面 z=100
    upper = _box('upper', 0, 0, 240, 350, 530, 120)   # 底面 z=240，不齐平
    assert _passes(upper, [lower]) is True
    print('[PASS] 非直接支撑层 → 不参与判定')


def test_no_xy_overlap_ignored():
    """XY 投影不重叠的更大箱不参与判定。"""
    aside = _box('aside', 800, 0, 0, 700, 530, 240)
    upper = _box('upper', 0, 0, 240, 350, 530, 240)
    assert _passes(upper, [aside]) is True
    print('[PASS] XY 不重叠 → 不参与判定')


def test_edge_touching_is_not_overlap():
    """仅边缘相切（重叠面积为 0）不算压在上面。

    upper 底面左边界正好落在 big 右边界上，两者只共一条线，
    载荷不经由 big 传递，不应判违例。
    """
    big = _box('big', 0, 0, 0, 700, 530, 240)
    upper = _box('upper', 700, 0, 240, 350, 530, 240)
    assert _passes(upper, [big]) is True
    print('[PASS] 边缘相切 → 不算重叠')


def test_one_larger_supporter_among_many_rejected():
    """多个支撑者时，只要有一个面积更大就违例。"""
    ok_a = _box('ok_a', 0, 0, 0, 350, 530, 240)
    ok_b = _box('ok_b', 352, 0, 0, 350, 530, 240)
    too_big = _box('too_big', 704, 0, 0, 700, 530, 240)
    upper = _box('upper', 300, 0, 240, 600, 530, 240)
    assert _passes(upper, [ok_a, ok_b]) is True
    assert _passes(upper, [ok_a, ok_b, too_big]) is False
    print('[PASS] 多支撑者中有一个更大 → 拒绝')


def test_area_uses_raw_dims_not_effective():
    """面积口径必须是原始尺寸：含容差会让等面积不同长宽比失序。

    300×600 与 400×450 原始等面积（180000），加 2mm 容差后
    302×602=181804 > 402×452=181704，按含容差口径会误判违例。
    """
    a = _box('a', 0, 0, 0, 400, 450, 120)
    a['length'], a['width'] = 402.0, 452.0        # 放置尺寸含容差
    upper = _box('u', 0, 0, 120, 300, 600, 120)
    upper['length'], upper['width'] = 302.0, 602.0
    assert footprint_area(a) == footprint_area(upper) == 180000.0
    assert _passes(upper, [a]) is True
    print('[PASS] 面积按原始尺寸计算 → 等面积通过')


def test_gate_flags_violation():
    big = _box('big', 0, 0, 0, 700, 530, 240)
    small = _box('small', 0, 0, 240, 350, 530, 240)
    res = validate_pallet_constraints({'packed_items': [big, small]}, PALLET)
    types = [v['type'] for v in res['violations']]
    assert 'footprint_area_below' in types, types
    print('[PASS] 门禁能识别小面积在上')


def test_gate_switch_off():
    """开关关闭后门禁不再判该项违例。"""
    big = _box('big', 0, 0, 0, 700, 530, 240)
    small = _box('small', 0, 0, 240, 350, 530, 240)
    res = validate_pallet_constraints(
        {'packed_items': [big, small]}, PALLET,
        constraint_config=ConstraintConfig(footprint_area_below_enabled=False),
    )
    types = [v['type'] for v in res['violations']]
    assert 'footprint_area_below' not in types, types
    print('[PASS] 开关关闭 → 门禁放行')


if __name__ == '__main__':
    test_smaller_footprint_on_larger_rejected()
    test_larger_footprint_on_smaller_ok()
    test_floor_box_exempt()
    test_equal_area_ok()
    test_equal_area_rotated_ok()
    test_applies_to_every_box_not_only_small()
    test_non_support_layer_ignored()
    test_no_xy_overlap_ignored()
    test_edge_touching_is_not_overlap()
    test_one_larger_supporter_among_many_rejected()
    test_area_uses_raw_dims_not_effective()
    test_gate_flags_violation()
    test_gate_switch_off()
    print('[PASS] 所有测试通过！')
