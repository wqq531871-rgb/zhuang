"""平顶不缺角（正常订单达标盘）形状校验与降级修剪。

甲方口径（2026-07 需求，已确认）：
- 正常订单（全规则箱，见 utils/normal_order.py）的**达标盘**必须：
  1. 顶面平：所有暴露顶面同一高度，**零容差**（仅浮点 eps）；
  2. 四周不缺角：判定看**整圈周边**——垛型每个高度层的外圈四壁都必须被
     箱面铺满，缝隙（相邻箱摆放缝）不超过 seam 容忍值；缺口藏内部允许。
- 尾盘（未达标盘）整盘豁免；守恒兜底盘豁免；仅对配置内托盘类型（默认
  MH423C）生效。

几何口径：一律用原始尺寸 raw_*（不含放置容差）与放置坐标；相邻箱之间的
2mm 摆放缝是几何必然，由 seam 容忍值（默认 6mm，对齐 max_box_gap_mm 的
"贴紧"语义）吸收，不算缺口。
"""

from typing import Dict, Iterable, List, Optional, Tuple

from ..config.constants import PALLET_INDEX_TARGETS
from ..utils.dimensions import raw_dims
from ..utils.normal_order import items_marked_normal

# 顶面等高判定：甲方要求零容差，仅保留浮点比较 eps
FLAT_TOP_EPS = 1e-6

_Box = Tuple[float, float, float, float, float, float, Dict]


def _placed_boxes(items: Iterable[Dict]) -> List[_Box]:
    boxes: List[_Box] = []
    for item in items:
        pos = item.get('position') or {}
        dims = raw_dims(item)
        boxes.append((
            float(pos.get('x', 0) or 0),
            float(pos.get('y', 0) or 0),
            float(pos.get('z', 0) or 0),
            float(dims['length']),
            float(dims['width']),
            float(dims['height']),
            item,
        ))
    return boxes


def _covered_above(box: _Box, boxes: List[_Box]) -> bool:
    """箱顶是否被上方箱覆盖（存在起始高度 ≥ 本箱顶、XY 有重叠的箱）。"""
    x, y, z, l, w, h, _ = box
    top = z + h
    for other in boxes:
        if other is box:
            continue
        ox, oy, oz, ol, ow, _oh, _ = other
        if oz < top - FLAT_TOP_EPS:
            continue
        if (min(x + l, ox + ol) - max(x, ox) > FLAT_TOP_EPS
                and min(y + w, oy + ow) - max(y, oy) > FLAT_TOP_EPS):
            return True
    return False


def _max_coverage_gap(
    intervals: List[Tuple[float, float]], lo: float, hi: float
) -> float:
    """区间并集对 [lo, hi] 的最大未覆盖缺口（含首尾）。"""
    if hi - lo <= FLAT_TOP_EPS:
        return 0.0
    if not intervals:
        return hi - lo
    intervals = sorted(intervals)
    max_gap = intervals[0][0] - lo
    reach = intervals[0][1]
    for start, end in intervals[1:]:
        if start > reach:
            max_gap = max(max_gap, start - reach)
        reach = max(reach, end)
    max_gap = max(max_gap, hi - reach)
    return max_gap


def check_flat_top_full_perimeter(
    items: List[Dict],
    seam_tolerance_mm: float = 6.0,
) -> Dict:
    """校验一盘箱子的「顶面平 + 整圈周边不缺」。

    Returns:
        {'is_valid': bool, 'violations': [...]}；violation 形如
        {'type': 'flat_top_step', 'box_id', 'top', 'expected_top'} 或
        {'type': 'perimeter_notch', 'side', 'z', 'gap'}。
    """
    boxes = _placed_boxes(items)
    boxes = [b for b in boxes if b[5] > 0]
    if not boxes:
        return {'is_valid': True, 'violations': []}
    seam = max(0.0, float(seam_tolerance_mm))
    violations: List[Dict] = []

    # 1) 顶面平：所有暴露顶面 == 全盘最高点（零容差）
    stack_top = max(b[2] + b[5] for b in boxes)
    for b in boxes:
        top = b[2] + b[5]
        if top < stack_top - FLAT_TOP_EPS and not _covered_above(b, boxes):
            violations.append({
                'type': 'flat_top_step',
                'box_id': b[6].get('id'),
                'top': round(top, 3),
                'expected_top': round(stack_top, 3),
            })

    # 2) 整圈周边：每个高度层的外圈四壁被箱面铺满（缝 ≤ seam）
    x0 = min(b[0] for b in boxes)
    x1 = max(b[0] + b[3] for b in boxes)
    y0 = min(b[1] for b in boxes)
    y1 = max(b[1] + b[4] for b in boxes)
    levels = sorted({round(v, 6) for b in boxes for v in (b[2], b[2] + b[5])})
    for a, c in zip(levels, levels[1:]):
        if c - a <= FLAT_TOP_EPS:
            continue
        zc = (a + c) / 2.0
        layer = [b for b in boxes if b[2] <= zc <= b[2] + b[5]]
        if not layer:
            violations.append({'type': 'floating_layer', 'z': round(zc, 3)})
            continue
        sides = (
            ('x_min', [(b[1], b[1] + b[4]) for b in layer
                       if b[0] <= x0 + seam], y0, y1),
            ('x_max', [(b[1], b[1] + b[4]) for b in layer
                       if b[0] + b[3] >= x1 - seam], y0, y1),
            ('y_min', [(b[0], b[0] + b[3]) for b in layer
                       if b[1] <= y0 + seam], x0, x1),
            ('y_max', [(b[0], b[0] + b[3]) for b in layer
                       if b[1] + b[4] >= y1 - seam], x0, x1),
        )
        for side_name, intervals, lo, hi in sides:
            gap = _max_coverage_gap(intervals, lo, hi)
            if gap > seam + FLAT_TOP_EPS:
                violations.append({
                    'type': 'perimeter_notch',
                    'side': side_name,
                    'z': round(zc, 3),
                    'gap': round(gap, 3),
                })

    return {'is_valid': not violations, 'violations': violations}


def flat_top_required_target(
    items: List[Dict],
    pallet_plan: Optional[Dict],
    target_mpm: Optional[float],
    constraint_config,
) -> Optional[float]:
    """判断一盘是否须执行平顶校验；须执行时返回解析后的目标指数。

    触发条件（全部满足）：开关开、全部箱子带正常订单标记、托盘类型在
    适用范围、非守恒兜底盘、整盘指数达标（≥ target，尾盘豁免）。
    target 解析链：显式参数 → 盘字段 mpm_target → PALLET_INDEX_TARGETS
    （覆盖门禁被匿名 {'packed_items': ...} 调用、拿不到目标的场景）。
    """
    enabled = getattr(
        constraint_config, 'flat_top_full_perimeter_enabled', True,
    ) if constraint_config is not None else True
    if not enabled or not items:
        return None
    if not items_marked_normal(items):
        return None
    pallet_type = str(items[0].get('pallet_type', ''))
    scope = getattr(
        constraint_config, 'flat_top_pallet_types', ('MH423C',),
    ) if constraint_config is not None else ('MH423C',)
    if pallet_type not in set(scope or ()):
        return None
    if pallet_plan and pallet_plan.get('conservation_fallback'):
        return None
    target = target_mpm
    if target is None and pallet_plan:
        target = pallet_plan.get('mpm_target')
    if target is None:
        target = PALLET_INDEX_TARGETS.get(pallet_type)
    if target is None or float(target) <= 0:
        return None
    total = sum(
        float(item.get('min_pack_multiple', 0) or 0) for item in items
    )
    if total + 1e-9 < float(target):
        return None
    return float(target)


def flat_top_seam_tolerance(constraint_config) -> float:
    """形状校验的缝隙容忍值（毫米）。"""
    if constraint_config is None:
        return 6.0
    return float(getattr(constraint_config, 'flat_top_seam_tolerance_mm', 6.0))


def flat_top_group_required(
    constraint_config, pallet_type, boxes: Iterable[Dict]
) -> bool:
    """分组级判定：该组的达标盘是否须平顶不缺角（生成侧提前收紧用）。

    与门禁侧 flat_top_required_target 同源：开关开、托盘类型在范围、
    全部箱子带正常订单标记。生成侧据此切换等高柱/完整平铺等约束。
    """
    enabled = getattr(
        constraint_config, 'flat_top_full_perimeter_enabled', True,
    ) if constraint_config is not None else True
    if not enabled:
        return False
    scope = getattr(
        constraint_config, 'flat_top_pallet_types', ('MH423C',),
    ) if constraint_config is not None else ('MH423C',)
    if str(pallet_type) not in set(scope or ()):
        return False
    return items_marked_normal(boxes)


def rects_ring_complete(
    rects: List[Tuple[float, float, float, float]],
    seam_tolerance_mm: float = 6.0,
) -> bool:
    """2D 矩形集合 (x, y, w, h) 的外圈四边是否铺满（缝 ≤ seam）。

    用于生成侧柱布局的快速预检（柱等高时单层即代表整垛）。
    """
    if not rects:
        return False
    seam = max(0.0, float(seam_tolerance_mm))
    x0 = min(r[0] for r in rects)
    x1 = max(r[0] + r[2] for r in rects)
    y0 = min(r[1] for r in rects)
    y1 = max(r[1] + r[3] for r in rects)
    sides = (
        ([(r[1], r[1] + r[3]) for r in rects if r[0] <= x0 + seam], y0, y1),
        ([(r[1], r[1] + r[3]) for r in rects
          if r[0] + r[2] >= x1 - seam], y0, y1),
        ([(r[0], r[0] + r[2]) for r in rects if r[1] <= y0 + seam], x0, x1),
        ([(r[0], r[0] + r[2]) for r in rects
          if r[1] + r[3] >= y1 - seam], x0, x1),
    )
    return all(
        _max_coverage_gap(intervals, lo, hi) <= seam + FLAT_TOP_EPS
        for intervals, lo, hi in sides
    )


def trim_items_to_tail(
    items: List[Dict],
    target: float,
    seam_tolerance_mm: float = 6.0,
) -> Tuple[List[Dict], List[Dict]]:
    """把「达标但形状不合格」的盘从顶部逐箱拆箱，直到合规或降级为尾盘。

    每次移除当前暴露（上方无箱）的最高箱，保证剩余堆叠物理可行；每拆一箱
    重查形状——若剩余堆叠已「平顶不缺角」且仍达标，提前停止（保住达标盘，
    只拆掉顶部破坏形状的零头）；否则一路拆到指数 < target（尾盘豁免形状
    约束）。被移除箱由调用方退回残料池继续装下一盘。

    Returns:
        (保留的箱子, 被移除的箱子)。
    """
    kept = list(items)
    removed: List[Dict] = []

    def _total(seq: List[Dict]) -> float:
        return sum(float(b.get('min_pack_multiple', 0) or 0) for b in seq)

    while kept and _total(kept) + 1e-9 >= float(target):
        if check_flat_top_full_perimeter(
            kept, seam_tolerance_mm=seam_tolerance_mm,
        )['is_valid']:
            break  # 剩余堆叠已合规且达标，保住达标盘
        boxes = _placed_boxes(kept)
        exposed = [b for b in boxes if not _covered_above(b, boxes)]
        if not exposed:
            exposed = boxes
        pick = max(
            exposed,
            key=lambda b: (b[2] + b[5], b[2], b[0], b[1], str(b[6].get('id'))),
        )
        kept.remove(pick[6])
        removed.append(pick[6])
    return kept, removed
