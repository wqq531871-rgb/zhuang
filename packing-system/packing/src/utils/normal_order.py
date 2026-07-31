"""「正常订单」判定与箱级标记。

甲方口径（2026-07 需求）：正常订单 = 箱子全是「规则箱」的订单；正常订单的
达标盘必须顶面平整、四周整圈不缺角（尾盘豁免，见 geometry/flat_top.py）。

「规则箱」定义与 UI 看板 ``ui/dashboard_state.py`` 的规则/不规则计数一致：
**规格存在逐轴整数倍伙伴**——订单内另有一种规格，长/宽/高按对应轴（不旋转）
之比均为整数（如 700×265×240 与 350×265×120）。订单内**全部**规格都有伙伴
才算正常订单（实测 668 规则数据集的 8 种规格两两成对，整单判正常；混入
430×280×430 这类孤立规格即判不正常）。与 UI 口径唯一的刻意差异：**单规格
订单判为正常**（UI 把孤立规格计为不规则是看板统计口径；单规格订单是最容易
平顶满铺的主力场景，业务上显然属于"全规则箱"）。

标记方式：给每个箱子写布尔字段 ``_normal_order``。该字段随箱子字典的
deepcopy / repack_ready_item 自然流经主装箱、全部救援与重排路径；
门禁据此判断是否执行平顶校验。未打标（旧测试、外部构造箱）＝非正常订单
＝不做平顶校验，行为与历史一致。
"""

import math
from collections import defaultdict
from typing import Dict, Iterable, List, Tuple

# 箱级标记键：True=所属订单为正常订单（全规则箱）。内部字段，输出前剥离。
NORMAL_ORDER_FLAG = '_normal_order'

# 逐轴整数倍判定容差（与 UI 看板口径一致）
_INTEGER_MULTIPLE_TOLERANCE = 1e-6


def _box_spec(box: Dict) -> Tuple[float, float, float]:
    """箱子的分类规格（原始长/宽/高）。装箱前的箱子字典尺寸即原始尺寸。"""
    return (
        float(box.get('length', 0) or 0),
        float(box.get('width', 0) or 0),
        float(box.get('height', 0) or 0),
    )


def _axes_integer_multiple(
    left: Tuple[float, float, float],
    right: Tuple[float, float, float],
) -> bool:
    """两规格逐轴（不旋转）之比是否均为整数。"""
    for a, b in zip(left, right):
        ratio = max(a, b) / min(a, b)
        nearest = round(ratio)
        if nearest < 1 or abs(ratio - nearest) > _INTEGER_MULTIPLE_TOLERANCE:
            return False
    return True


def boxes_form_regular_family(boxes: Iterable[Dict]) -> bool:
    """订单内是否「全是规则箱」：每种规格都有逐轴整数倍伙伴。

    单一规格订单视为正常（见模块 docstring 的口径说明）。
    尺寸缺失、非正或非有限值 → 判为不规则（不正常订单）。
    """
    specs = set()
    for box in boxes:
        spec = _box_spec(box)
        if not all(math.isfinite(v) and v > 0 for v in spec):
            return False
        specs.add(spec)
    if not specs:
        return False
    spec_list = sorted(specs)
    if len(spec_list) == 1:
        return True
    return all(
        any(
            _axes_integer_multiple(spec, other)
            for other in spec_list if other is not spec
        )
        for spec in spec_list
    )


def annotate_normal_orders(
    boxes: List[Dict],
    pallet_types: Iterable[str] = ('MH423C',),
    enabled: bool = True,
) -> int:
    """按 (托盘类型, 原始销售订单号) 分组判定正常订单并打箱级标记。

    必须在 case_group / 组内子聚类等内部改名之前调用（分类基于原始订单
    整体，混合订单拆出的规则子集仍属于混合订单 → 不打标）。

    Args:
        boxes: 全部箱子（就地写入 ``_normal_order`` 字段）。
        pallet_types: 平顶约束适用的托盘类型（甲方口径：仅 MH423C）。
        enabled: 总开关；False 时全部箱子标 False（等价关闭平顶校验）。

    Returns:
        判定为正常订单的订单数。
    """
    scope = set(pallet_types or ())
    grouped: Dict[Tuple[str, str], List[Dict]] = defaultdict(list)
    for box in boxes:
        key = (
            str(box.get('pallet_type', '')),
            str(box.get('sales_order_no', 'UNKNOWN_ORDER')),
        )
        grouped[key].append(box)

    normal_orders = 0
    for (pallet_type, _order), group in grouped.items():
        is_normal = bool(
            enabled
            and pallet_type in scope
            and boxes_form_regular_family(group)
        )
        if is_normal:
            normal_orders += 1
        for box in group:
            box[NORMAL_ORDER_FLAG] = is_normal
    return normal_orders


def items_marked_normal(items: Iterable[Dict]) -> bool:
    """一组箱子是否全部带正常订单标记（缺标记＝False，历史行为兜底）。"""
    items = list(items)
    return bool(items) and all(
        bool(item.get(NORMAL_ORDER_FLAG)) for item in items
    )
