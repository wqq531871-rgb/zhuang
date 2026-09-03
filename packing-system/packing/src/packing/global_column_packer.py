"""全局列式装箱 + 柱级 Set-Partitioning 组合优化（主装箱算法）。

思路（两步降维 + 组合优化）：
1. 凑柱：同底面箱按高度凑成 ≤ 托盘高的"柱"（同底面垂直堆叠→支撑率天然
   1.0），把 3D 装箱降为"柱的 2D 底面布局"。高度任意（不假设 120 倍数），
   规则箱凑满、不规则箱凑次满，均成合法柱。
2. 柱级组合优化：柱按 (底面, 指数) 聚合成柱类型，枚举"几何可装 + 指数达标"
   的候选盘 pattern，用 OR-Tools Set-Partitioning ILP **最大化达标盘数**。
3. 落地：选中盘用 265-单元列网格定坐标（530=2×265 对齐、消碎片）；残料柱
   再尽量装满成盘（达标优先，不达标则尽量满）。允许 90° 旋转。

约束：支撑率（柱内同底面=1.0）、旋转（落地选朝向 + layered_oriented 标记）、
吸盘/间隙/重心/小箱在下/同尺寸重箱在下 由整盘门禁逐盘复核。
不规则底面/高度的柱按 ceil 单元安全占格（不重叠），几何不佳时由门禁兜底。

无 OR-Tools 时自动回退为贪心装盘（仍正确，达标率略降）。
"""

import itertools
from collections import defaultdict
from typing import Dict, List, Optional, Tuple

from ..config.constants import PALLET_INDEX_TARGETS
from ..geometry.constraint_validator import validate_pallet_constraints
from ..geometry.flat_top import (
    check_flat_top_full_perimeter,
    flat_top_group_required,
    flat_top_seam_tolerance,
    rects_ring_complete,
    trim_items_to_tail,
)
from ..geometry.weight_limit import (
    box_weight,
    column_weight,
    weight_cap_for_group,
)
from .beam_search_packer import BeamSearchPacker
from .direct_layer_packer import build_centered_single_box_solution
from .layered_packer import _assemble, _ffd_columns

try:
    from ortools.sat.python import cp_model
    _HAS_ORTOOLS = True
except ImportError:
    _HAS_ORTOOLS = False

_UNIT = 265.0  # y 向基本单元（mm）；规则底面 ylen ∈ {265, 530=2×265}
_OVERFLOW = 12.0  # 达标盘允许的指数溢出上限（控制候选规模）
_PATTERN_TYPE_CAP = 40  # 单类型在一盘内的枚举上限
_ILP_MAX_TYPES = 14  # 柱类型数 ≤ 此值才考虑精确 ILP（否则贪心，避免组合爆炸）
_MAX_ENUM = 2_000_000  # itertools.product 枚举空间上限（超过即改走贪心）
_ILP_TIME = 15.0  # 单组 ILP 时间上限（秒）
_CPSAT_TIME = 15.0  # 单盘 CP-SAT 精确摆柱时间上限（秒，首盘/每 pattern 首次）
_CPSAT_RETRY_TIME = 4.0  # 同 pattern 先前装不满时的短重试时限（秒）
_CPSAT_MAX_FAILS = 2  # 同 pattern 累计装不满次数上限，超过即余盘全退残料
_FLAT_RESOLVE_ROUNDS = 3  # 平顶模式：铺砌失败 pattern 拉黑后 ILP 重解的最大轮数


def _fp_key(col: Dict) -> Tuple[int, int]:
    """柱的底面缓存键（原始 xlen/ylen 取整；同 pattern 内按此配对复用布局）。"""
    return (int(round(float(col['xlen']))), int(round(float(col['ylen']))))


def _col_weight_key(col: Dict) -> float:
    """柱的重量键（kg，取整到 mg）。限重生效时并入柱类型键，使同类型柱重量
    唯一 ⇒ pattern 的总重有确定值 ⇒ 枚举阶段能精确剪枝而非保守估计。"""
    return round(column_weight(col), 6)


def _col_height_key(col: Dict) -> float:
    """柱总高键（箱高求和，round 到 1e-3）。平顶模式下并入柱类型键，
    使同 pattern 的柱严格等高（盘内所有柱同顶 → 顶面天然平）。"""
    return round(sum(
        float(b.get('height', 0) or 0) for b in col.get('boxes', [])
    ), 3)


def _pattern_key(types: List[tuple], combo) -> tuple:
    """pattern 的跨轮稳定键：(柱类型, 用量) 非零对。

    平顶模式的 ILP 重解在不同轮次里 types 列表会收缩（空池类型剔除），
    按索引记失败会串位；用 (类型, 数量) 组合做键在轮间保持一致，
    黑名单/布局缓存都靠它。铺砌可行性只由底面 multiset 决定，同键必同判。
    """
    return tuple(
        (t, n) for t, n in zip(types, combo) if n
    )


def _apply_layout(layout: List[tuple], plate: List[Dict]) -> List[tuple]:
    """把已解出的满解布局套到同 pattern 的另一盘柱上。

    layout = [(fp_key, rotated, x, y)]（来自首盘 CP-SAT 满解）。同 pattern 的
    盘柱型构成完全相同（2D 摆放只看底面），逐槽位按底面键配对即可完全复用，
    免去重复求解：零耗时且消除 CP-SAT 多线程在同 run 内的随机波动。
    配不齐（防御性，理论不可能）返回 []，调用方回退正常求解。
    """
    pool: Dict[Tuple[int, int], List[Dict]] = defaultdict(list)
    for c in plate:
        pool[_fp_key(c)].append(c)
    placed: List[tuple] = []
    for fp_key, rotated, x, y in layout:
        cands = pool.get(fp_key)
        if not cands:
            return []
        c = cands.pop()
        col2 = dict(c)
        col2['_src'] = c
        if rotated:
            col2['xlen'], col2['ylen'] = c['ylen'], c['xlen']
        placed.append((col2, x, y))
    if any(cands for cands in pool.values()):
        return []  # 有柱没被布局覆盖 → 不是满解复用场景
    return placed


def _fp_orient(fp: Tuple[int, int]) -> Tuple[float, float]:
    """底面 (短,长) → (沿x, 沿y)：350/700 公共边沿 x，使列宽统一。"""
    a, b = fp
    if b == 700:
        return 700.0, float(a)
    if a == 350:
        return 350.0, float(b)
    if b == 350:
        return 350.0, float(a)
    return float(a), float(b)


def _orient_per(xl: float, yl: float, pallet_dims: Dict[str, float], tol: float) -> int:
    """单一底面满盘根数（floor 网格，取两朝向较优）。

    用于 suits_group 的真实 per 估算，替代 _grid_pack 的 350/265 量化估算——
    后者对非模数箱型严重低估（如 430×280：量化 16 vs 真实 25），会让本可旋转
    达标的非模数订单被误判"不适合"而回退固定朝向 baseline（L2 缺陷）。
    模数箱型两者相等，故对 668/5000 零回归。
    """
    pl = float(pallet_dims.get('length', 0) or 0)
    pw = float(pallet_dims.get('width', 0) or 0)
    if xl <= 0 or yl <= 0:
        return 0
    p1 = int(pl // (xl + tol)) * int(pw // (yl + tol))
    p2 = int(pl // (yl + tol)) * int(pw // (xl + tol))
    return max(p1, p2)


def _build_columns(
    boxes: List[Dict],
    pallet_dims: Dict[str, float],
    weight_cap: Optional[float] = None,
) -> List[Dict]:
    """按底面分组凑柱。返回柱列表 [{fp, xlen, ylen, boxes, idx}]。"""
    cap = float(pallet_dims.get('height', 0) or 0)
    by_fp: Dict[Tuple[int, int], List[Dict]] = defaultdict(list)
    for box in boxes:
        key = tuple(sorted((
            int(round(float(box.get('length', 0) or 0))),
            int(round(float(box.get('width', 0) or 0))),
        )))
        by_fp[key].append(box)
    cols: List[Dict] = []
    for fp, group in by_fp.items():
        xlen, ylen = _fp_orient(fp)
        for cb in _ffd_columns(group, cap, weight_cap):
            idx = sum(float(b.get('min_pack_multiple', 0) or 0) for b in cb)
            cols.append({'fp': fp, 'xlen': xlen, 'ylen': ylen, 'boxes': cb, 'idx': round(idx, 3)})
    return cols


def _column_signature(columns: List[Dict]) -> Tuple[Tuple[str, ...], ...]:
    """Return an order-independent signature for candidate deduplication."""

    return tuple(sorted(
        tuple(sorted(str(box.get('id')) for box in column['boxes']))
        for column in columns
    ))


def _balanced_columns(
    group: List[Dict],
    cap: float,
    weight_cap: Optional[float] = None,
) -> List[List[Dict]]:
    """Spread high-index boxes across the lowest-index feasible columns."""

    base_count = max(1, len(_ffd_columns(group, cap, weight_cap)))
    bins = [
        {'rem': cap, 'w': 0.0, 'idx': 0.0, 'boxes': []}
        for _ in range(base_count)
    ]
    ordered = sorted(
        group,
        key=lambda box: (
            -float(box.get('min_pack_multiple', 0) or 0),
            -float(box.get('height', 0) or 0),
            str(box.get('id')),
        ),
    )
    for box in ordered:
        height = float(box.get('height', 0) or 0)
        weight = box_weight(box)
        feasible = [
            (index, column)
            for index, column in enumerate(bins)
            if column['rem'] >= height - 1e-9
            and (weight_cap is None
                 or column['w'] + weight <= weight_cap + 1e-6)
        ]
        if feasible:
            _index, chosen = min(
                feasible,
                key=lambda entry: (
                    entry[1]['idx'],
                    -entry[1]['rem'],
                    entry[0],
                ),
            )
        else:
            chosen = {'rem': cap, 'w': 0.0, 'idx': 0.0, 'boxes': []}
            bins.append(chosen)
        chosen['boxes'].append(box)
        chosen['rem'] -= height
        chosen['w'] += weight
        chosen['idx'] += float(
            box.get('min_pack_multiple', 0) or 0
        )
    return [column['boxes'] for column in bins if column['boxes']]


def _concentrated_columns(
    group: List[Dict],
    cap: float,
    weight_cap: Optional[float] = None,
) -> List[List[Dict]]:
    """Concentrate high-index boxes using index-descending first fit."""

    columns: List[Dict] = []
    ordered = sorted(
        group,
        key=lambda box: (
            -float(box.get('min_pack_multiple', 0) or 0),
            -float(box.get('height', 0) or 0),
            str(box.get('id')),
        ),
    )
    for box in ordered:
        height = float(box.get('height', 0) or 0)
        weight = box_weight(box)
        for column in columns:
            if column['rem'] < height - 1e-9:
                continue
            if weight_cap is not None and column['w'] + weight > weight_cap + 1e-6:
                continue
            column['rem'] -= height
            column['w'] += weight
            column['boxes'].append(box)
            break
        else:
            columns.append({'rem': cap - height, 'w': weight, 'boxes': [box]})
    return [column['boxes'] for column in columns]


def _build_column_candidates(
    boxes: List[Dict],
    pallet_dims: Dict[str, float],
    target_mpm: Optional[float],
    weight_cap: Optional[float] = None,
) -> List[Tuple[str, List[Dict]]]:
    """Build distinct height, index-balanced, and target-focused columns.

    weight_cap：整盘限重（kg）。给定时三种凑柱器都保证柱重不超限（超重柱
    无法上任何盘）。None＝不限重，与历史行为完全一致。
    """

    del target_mpm  # The target affects board selection after columnization.
    cap = float(pallet_dims.get('height', 0) or 0)
    by_fp: Dict[Tuple[int, int], List[Dict]] = defaultdict(list)
    for box in boxes:
        key = tuple(sorted((
            int(round(float(box.get('length', 0) or 0))),
            int(round(float(box.get('width', 0) or 0))),
        )))
        by_fp[key].append(box)

    builders = (
        ('height_first', _ffd_columns),
        ('index_balanced', _balanced_columns),
        ('target_concentrated', _concentrated_columns),
    )
    candidates: List[Tuple[str, List[Dict]]] = []
    seen = set()
    for strategy_name, builder in builders:
        columns: List[Dict] = []
        for fp, group in by_fp.items():
            xlen, ylen = _fp_orient(fp)
            for column_boxes in builder(group, cap, weight_cap):
                index = sum(
                    float(box.get('min_pack_multiple', 0) or 0)
                    for box in column_boxes
                )
                columns.append({
                    'fp': fp,
                    'xlen': xlen,
                    'ylen': ylen,
                    'boxes': column_boxes,
                    'idx': round(index, 3),
                })
        signature = _column_signature(columns)
        if signature in seen:
            continue
        seen.add(signature)
        candidates.append((strategy_name, columns))
    return candidates


def _build_pools(cols, flat_required: bool, with_weight: bool):
    """柱按类型聚合。类型键 = (底面, 指数)[, 柱高][, 柱重]。

    柱高分量：平顶模式用（盘内柱等高 → 顶面天然平）。
    柱重分量：限重模式用，使同类型柱重量唯一 ⇒ pattern 总重有确定值。
    """
    pools: Dict[tuple, List[Dict]] = defaultdict(list)
    for c in cols:
        key = (c['fp'], c['idx'])
        if flat_required:
            key = key + (_col_height_key(c),)
        if with_weight:
            key = key + (_col_weight_key(c),)
        pools[key].append(c)
    return pools


def _ilp_affordable(types, counts, pallet_dims, tol) -> bool:
    """柱类型规模是否还够走精确 ILP（否则只能贪心）。

    单类型一盘内用量上界 = 该底面满盘根数（几何上界），用它收紧枚举空间预判。
    """
    if not _HAS_ORTOOLS or len(types) > _ILP_MAX_TYPES:
        return False
    prod_scale = 1
    for t, count in zip(types, counts):
        per_cap = max(1, _orient_per(*_fp_orient(t[0]), pallet_dims, tol))
        prod_scale *= min(count, per_cap) + 1
        if prod_scale > _MAX_ENUM:
            return False
    return True


def _merge_weight_classes(pools, pallet_dims, tol, w_pos):
    """限重模式：把「重量最接近」的同基柱类型逐步合并，直到枚举空间可负担。

    柱重并入类型键能让 pattern 总重精确，但会让类型数翻倍，枚举空间可能顶过
    _MAX_ENUM，把本可走精确 ILP 的组挤到贪心路径（实测 668×20：类型 5→10、
    枚举 3.1万→298万、达标 10→7）。直接退回「按底面/指数聚合 + 取组内最大柱重」
    虽然可靠，但保守放大可达 2 倍（同类型柱重 45.5～90.4kg），照样丢达标盘。

    折中：只合并必要的最少次数，每次挑「引入多余重量最少」的一对相邻重量类
    （多余重量 = 重量差 × 被抬高的柱数），合并类取组内最大柱重作上界。上界
    始终可靠（实际盘重 ≤ Σ combo·上界），保守度压到最低。

    返回合并后的 pools；无法合并到可负担时返回 None（调用方退贪心）。
    """
    bound_of = {key: key[w_pos] for key in pools}

    def _merged():
        merged = defaultdict(list)
        for key, columns in pools.items():
            merged[key[:w_pos] + (bound_of[key],)].extend(columns)
        return merged

    merged = _merged()
    while True:
        types = sorted(merged.keys())
        counts = [len(merged[t]) for t in types]
        if _ilp_affordable(types, counts, pallet_dims, tol):
            return merged
        by_base: Dict[tuple, set] = defaultdict(set)
        for key in pools:
            by_base[key[:w_pos]].add(bound_of[key])
        best = None  # (多余重量, 基类型, 低类上界, 高类上界)
        for base, bounds in by_base.items():
            ordered = sorted(bounds)
            for low, high in zip(ordered, ordered[1:]):
                lifted = sum(
                    len(columns) for key, columns in pools.items()
                    if key[:w_pos] == base and bound_of[key] == low
                )
                excess = (high - low) * lifted
                if best is None or excess < best[0]:
                    best = (excess, base, low, high)
        if best is None:
            return None  # 每个基类型只剩一个重量类，仍不可负担
        _excess, base, low, high = best
        for key in pools:
            if key[:w_pos] == base and bound_of[key] == low:
                bound_of[key] = high
        merged = _merged()


def _plan_rank(plans: List[Dict]) -> Tuple[int, int, float]:
    """Rank GCP candidates by successes, pallet count, then failed peak."""

    success = sum(plan.get('mpm_status') == 'SUCCESS' for plan in plans)
    failed_peak = max(
        (
            float(plan.get('mpm_total', 0) or 0)
            for plan in plans
            if plan.get('mpm_status') != 'SUCCESS'
        ),
        default=0.0,
    )
    return success, -len(plans), failed_peak


def _gcp_candidate_passes_gates(
    raw_boxes: List[Dict],
    plans: List[Dict],
    constraint_config,
) -> bool:
    """Require exact conservation and the final full gate on every pallet."""

    input_ids = sorted(str(box.get('id')) for box in raw_boxes)
    output_ids = sorted(
        str(box.get('id'))
        for plan in plans
        for box in plan.get('packed_items', [])
    )
    if len(output_ids) != len(input_ids) or output_ids != input_ids:
        return False
    pallet_dims = raw_boxes[0].get('pallet_dims') if raw_boxes else None
    if not pallet_dims:
        return False
    try:
        for plan in plans:
            if not plan.get('packed_items'):
                return False
            gate = validate_pallet_constraints(
                plan,
                pallet_dims,
                constraint_config=constraint_config,
                target_mpm=plan.get('mpm_target'),
            )
            if not gate.get('is_valid'):
                return False
    except (KeyError, TypeError, ValueError):
        return False
    return True


def _select_target_subset_cpsat(
    boxes: List[Dict],
    pallet_dims: Dict[str, float],
    target_mpm: float,
    excluded_signatures=None,
    time_limit: float = 3.0,
    weight_cap: Optional[float] = None,
) -> List[Dict]:
    """Select a volume-feasible target subset with minimum index overshoot.

    weight_cap：整盘限重（kg）。限重是线性可加约束，直接作为一条线性约束入模，
    求解器在「重量可行」的解空间里找最小指数溢出——不是选完再拒，因此不损失
    任何本可达标的组合。
    """

    if not _HAS_ORTOOLS or target_mpm <= 0:
        return []
    pallet_length = float(pallet_dims.get('length', 0) or 0)
    pallet_width = float(pallet_dims.get('width', 0) or 0)
    pallet_height = float(pallet_dims.get('height', 0) or 0)
    pallet_volume = int(round(
        pallet_length * pallet_width * pallet_height
    ))
    if pallet_volume <= 0:
        return []

    eligible = []
    for box in boxes:
        length = float(box.get('length', 0) or 0)
        width = float(box.get('width', 0) or 0)
        height = float(box.get('height', 0) or 0)
        mpm = float(box.get('min_pack_multiple', 0) or 0)
        footprint_fits = (
            (length <= pallet_length + 1e-9
             and width <= pallet_width + 1e-9)
            or (width <= pallet_length + 1e-9
                and length <= pallet_width + 1e-9)
        )
        if mpm > 0 and height <= pallet_height + 1e-9 and footprint_fits:
            eligible.append(box)
    if not eligible:
        return []

    scale = 1000
    target_value = int(round(float(target_mpm) * scale))
    mpm_values = [
        int(round(float(box.get('min_pack_multiple', 0) or 0) * scale))
        for box in eligible
    ]
    volumes = [
        int(round(
            float(box.get('length', 0) or 0)
            * float(box.get('width', 0) or 0)
            * float(box.get('height', 0) or 0)
        ))
        for box in eligible
    ]
    volume_units = [max(1, int(round(volume / 1_000_000.0)))
                    for volume in volumes]

    model = cp_model.CpModel()
    selected = [model.NewBoolVar(f'select_{i}') for i in range(len(eligible))]
    total_mpm = sum(mpm_values[i] * selected[i]
                    for i in range(len(eligible)))
    model.Add(total_mpm >= target_value)
    model.Add(sum(volumes[i] * selected[i]
                  for i in range(len(eligible))) <= pallet_volume)
    if weight_cap is not None:
        # 重量放大到整数（克）后入模，避免 CP-SAT 的整数系数丢精度
        weight_units = [
            int(round(box_weight(box) * 1000.0)) for box in eligible
        ]
        model.Add(sum(weight_units[i] * selected[i]
                      for i in range(len(eligible)))
                  <= int(weight_cap * 1000.0))

    footprint_indices: Dict[Tuple[int, int], List[int]] = defaultdict(list)
    for i, box in enumerate(eligible):
        footprint = tuple(sorted((
            int(round(float(box.get('length', 0) or 0))),
            int(round(float(box.get('width', 0) or 0))),
        )))
        footprint_indices[footprint].append(i)
    footprint_used = []
    for fp_index, indices in enumerate(footprint_indices.values()):
        used = model.NewBoolVar(f'footprint_{fp_index}')
        footprint_used.append(used)
        for index in indices:
            model.Add(selected[index] <= used)
        model.Add(used <= sum(selected[index] for index in indices))

    ids = [str(box.get('id')) for box in eligible]
    for signature in excluded_signatures or []:
        signature_ids = {str(box_id) for box_id in signature}
        exact_match_terms = [
            selected[i] if ids[i] in signature_ids else 1 - selected[i]
            for i in range(len(eligible))
        ]
        model.Add(sum(exact_match_terms) <= len(eligible) - 1)

    max_volume_units = max(1, int(round(pallet_volume / 1_000_000.0)))
    footprint_weight = max_volume_units + 1
    overshoot_weight = (len(footprint_used) + 1) * footprint_weight
    overshoot = total_mpm - target_value
    model.Minimize(
        overshoot * overshoot_weight
        + sum(footprint_used) * footprint_weight
        - sum(volume_units[i] * selected[i] for i in range(len(eligible)))
    )

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = max(0.01, float(time_limit))
    solver.parameters.num_search_workers = 8
    solver.parameters.random_seed = 42
    status = solver.Solve(model)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return []
    return [
        box for i, box in enumerate(eligible) if solver.Value(selected[i])
    ]


def _col_units(ylen: float, tol: float) -> int:
    """柱沿 y 占用的 265-单元数（ceil，保证任意 ylen 不重叠）。"""
    return max(1, int(-(-(ylen + tol) // (_UNIT + tol))))


def _grid_pack(cols: List[Dict], pallet_dims: Dict[str, float], tol: float) -> Tuple[List[tuple], List[Dict]]:
    """265-单元列网格摆柱：700 跨 2 列、530 占 2 单元、放最空列。
    返回 (placed=[(col,x,y)], unplaced)。"""
    pall = float(pallet_dims.get('length', 0) or 0)
    palw = float(pallet_dims.get('width', 0) or 0)
    colstep = 350.0 + tol
    ncols = int(pall // colstep)
    if ncols < 1:
        return [], list(cols)
    unit_h = _UNIT + tol
    cap = int(palw // unit_h)
    xs = [c * colstep for c in range(ncols)]
    col_u = [0] * ncols
    placed, unplaced = [], []

    for c in sorted([c for c in cols if c['xlen'] > colstep], key=lambda c: -_col_units(c['ylen'], tol)):
        u = _col_units(c['ylen'], tol)
        span = int(-(-(c['xlen'] + tol) // colstep))
        best = None
        for s in range(ncols - span + 1):
            base = max(col_u[s:s + span])
            if base + u <= cap and (best is None or base < best[1]):
                best = (s, base)
        if best is None:
            unplaced.append(c)
            continue
        s, base = best
        placed.append((c, xs[s], base * unit_h))
        for k in range(s, s + span):
            col_u[k] = base + u
    for c in sorted([c for c in cols if c['xlen'] <= colstep], key=lambda c: -_col_units(c['ylen'], tol)):
        u = _col_units(c['ylen'], tol)
        cand = [(col_u[i], i) for i in range(ncols) if col_u[i] + u <= cap]
        if not cand:
            unplaced.append(c)
            continue
        _, i = min(cand)
        placed.append((c, xs[i], col_u[i] * unit_h))
        col_u[i] += u
    return placed, unplaced


def _center_placed(placed: List[tuple], pallet_dims: Dict[str, float], tol: float) -> List[tuple]:
    """把摆好的柱团整体平移到托盘中心，改善重心与边缘间隙（残料盘用）。"""
    if not placed:
        return placed
    pall = float(pallet_dims.get('length', 0) or 0)
    palw = float(pallet_dims.get('width', 0) or 0)
    x_min = min(x for _c, x, _y in placed)
    x_max = max(x + float(_c['xlen']) + tol for _c, x, _y in placed)
    y_min = min(y for _c, _x, y in placed)
    y_max = max(y + float(_c['ylen']) + tol for _c, _x, y in placed)
    dx = (pall - (x_max - x_min)) / 2.0 - x_min
    dy = (palw - (y_max - y_min)) / 2.0 - y_min
    dx = max(0.0, dx)
    dy = max(0.0, dy)
    return [(c, x + dx, y + dy) for c, x, y in placed]


def _cpsat_pack_2d(cols: List[Dict], pallet_dims: Dict[str, float],
                   time_limit: float = 8.0) -> Tuple[List[tuple], List[Dict]]:
    """CP-SAT 2D 精确摆柱（允许 90° 旋转），替代 265 固定网格的落地。

    坐标 ÷5 无损缩放（柱底面与托盘边长均为 5 的倍数）。目标：最大化装入指数
    （present 全装即达上界 OPT，找到满解即返回）。用 265 网格的部分解作
    warm-start（网格通常仅差一两根），稳定快速求解、消除多线程随机波动。无缝
    由门禁"达标盘免 gap"保证；落地后整体居中改善重心。
    返回 (placed=[(col, x, y)], unplaced)，坐标真实 mm。旋转柱返回 xlen/ylen
    互换后的浅拷贝（_assemble 据此按旋转朝向摆箱）。无 OR-Tools 回退网格。
    """
    if not cols:
        return [], []
    if not _HAS_ORTOOLS:
        return _grid_pack(cols, pallet_dims, 2.0)
    s = 5
    pw = int(round(float(pallet_dims.get('length', 0) or 0) / s))
    ph = int(round(float(pallet_dims.get('width', 0) or 0) / s))
    if pw < 1 or ph < 1:
        return [], list(cols)
    maxd = max(pw, ph)
    # 265 网格部分解作 warm-start hint：网格通常能装绝大多数柱（仅差一两根），
    # 以此为起点消除 CP-SAT 多线程在临界密度下的随机波动，稳定快速装满。
    grid_xy = {}
    _gp, _gu = _grid_pack(cols, pallet_dims, 2.0)
    for _gc, _gx, _gy in _gp:
        grid_xy[id(_gc)] = (_gx, _gy)
    m = cp_model.CpModel()
    pres, xs, ys, rots, weights = [], [], [], [], []
    xivs, yivs = [], []
    unplaced: List[Dict] = []
    model_cols: List[Dict] = []
    for c in cols:
        w0 = int(round(float(c['xlen']) / s))
        h0 = int(round(float(c['ylen']) / s))
        fit0 = (w0 <= pw and h0 <= ph)
        fit1 = (h0 <= pw and w0 <= ph)
        if not (fit0 or fit1):
            unplaced.append(c)  # 任何朝向都放不下托盘
            continue
        i = len(model_cols)
        model_cols.append(c)
        p = m.NewBoolVar(f'p{i}')
        if w0 != h0 and fit0 and fit1:  # 两朝向都可放 → 引入旋转变量
            r = m.NewBoolVar(f'r{i}')
            wi = m.NewIntVar(min(w0, h0), max(w0, h0), f'w{i}')
            hi = m.NewIntVar(min(w0, h0), max(w0, h0), f'h{i}')
            m.Add(wi == w0).OnlyEnforceIf(r.Not())
            m.Add(wi == h0).OnlyEnforceIf(r)
            m.Add(hi == h0).OnlyEnforceIf(r.Not())
            m.Add(hi == w0).OnlyEnforceIf(r)
        elif fit0:
            r, wi, hi = None, w0, h0
        else:  # 仅旋转朝向可放
            r, wi, hi = None, h0, w0
        x = m.NewIntVar(0, pw, f'x{i}')
        y = m.NewIntVar(0, ph, f'y{i}')
        xe = m.NewIntVar(0, pw + maxd, f'xe{i}')
        ye = m.NewIntVar(0, ph + maxd, f'ye{i}')
        m.Add(xe == x + wi)
        m.Add(ye == y + hi)
        m.Add(xe <= pw).OnlyEnforceIf(p)  # 仅装入的柱需在界内
        m.Add(ye <= ph).OnlyEnforceIf(p)
        xivs.append(m.NewOptionalIntervalVar(x, wi, xe, p, f'xi{i}'))
        yivs.append(m.NewOptionalIntervalVar(y, hi, ye, p, f'yi{i}'))
        pres.append(p)
        xs.append(x)
        ys.append(y)
        rots.append(r)
        weights.append(max(1, int(round(float(c.get('idx', 0) or 0) * 100))))
        gxy = grid_xy.get(id(c))
        if gxy is not None:  # warm-start：网格放好的柱作为初始解提示（present=1、不旋转）
            m.AddHint(p, 1)
            m.AddHint(x, max(0, min(pw, int(round(gxy[0] / s)))))
            m.AddHint(y, max(0, min(ph, int(round(gxy[1] / s)))))
            if r is not None:
                m.AddHint(r, 0)
    if not model_cols:
        return [], unplaced
    m.AddNoOverlap2D(xivs, yivs)
    # 目标：最大化装入指数。达标盘免 gap，不需要密铺次目标；且 present 全装即达
    # 指数上界（OPT），CP-SAT 找到满解即可立即返回——比带位置次目标快且稳得多
    # （后者要证明全局最优，对 95% 密度很慢、时快时慢）。落地后整体居中改善重心。
    m.Maximize(sum(pres[i] * weights[i] for i in range(len(model_cols))))
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = float(time_limit)
    solver.parameters.num_search_workers = 8
    solver.parameters.random_seed = 42  # 固定种子（注：多线程+时限仍有微小波动，见已知限制）
    st = solver.Solve(m)
    if st not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        unplaced.extend(model_cols)  # 求解失败 → 全退残料
        return [], unplaced
    placed: List[tuple] = []
    for i, c in enumerate(model_cols):
        if solver.Value(pres[i]):
            col2 = dict(c)
            col2['_src'] = c  # 保留原柱引用：pack_group 据此标记"已用柱"，防重复装箱
            if rots[i] is not None and solver.Value(rots[i]) == 1:
                col2['xlen'], col2['ylen'] = c['ylen'], c['xlen']
            placed.append((col2, float(solver.Value(xs[i]) * s),
                           float(solver.Value(ys[i]) * s)))
        else:
            unplaced.append(c)
    return placed, unplaced


def _cpsat_tile_2d(cols: List[Dict], pallet_dims: Dict[str, float],
                   time_limit: float = 8.0) -> Tuple[List[tuple], List[Dict]]:
    """CP-SAT 完美平铺摆柱（平顶模式的达标盘落地，允许 90° 旋转）。

    与 _cpsat_pack_2d 的区别：不是"尽量多装"，而是要求**全部柱**装入某个
    候选外接矩形 W×Hy，且 W×Hy == 柱底面积和（÷5 无损缩放后整除枚举）。
    面积恰好相等 + 无重叠 + 全在界内 ⇒ 完美平铺：无内洞、外圈四壁天然铺满
    （比"整圈周边不缺"更强，直接免疫缺角）。候选 (W, Hy) 按 W 从大到小
    尝试（贴近托盘长边、居中后更稳）。

    要求柱底面尺寸为 5 的倍数（本项目箱型均满足）；量化有损时面积等式不
    成立，自然返回无解 → 调用方按残料兜底（保守安全）。
    返回 (placed=[(col, x, y)], unplaced)；无解时 ([], cols)。
    """
    if not cols:
        return [], []
    if not _HAS_ORTOOLS:
        return [], list(cols)
    s = 5
    pw = int(round(float(pallet_dims.get('length', 0) or 0) / s))
    ph = int(round(float(pallet_dims.get('width', 0) or 0) / s))
    dims = [
        (int(round(float(c['xlen']) / s)), int(round(float(c['ylen']) / s)))
        for c in cols
    ]
    area = sum(w * h for w, h in dims)
    if area <= 0 or pw < 1 or ph < 1:
        return [], list(cols)
    min_side = min(min(w, h) for w, h in dims)
    candidates = []
    for width in range(min_side, pw + 1):
        if area % width:
            continue
        depth = area // width
        if min_side <= depth <= ph:
            candidates.append((width, depth))
    candidates.sort(key=lambda pair: -pair[0])
    candidates = candidates[:8]  # 面积整除已筛得很少；上限防病态膨胀
    if not candidates:
        return [], list(cols)
    per_limit = max(1.0, float(time_limit) / len(candidates))

    for width, depth in candidates:
        m = cp_model.CpModel()
        xs, ys, rots = [], [], []
        xivs, yivs = [], []
        feasible = True
        for i, (w0, h0) in enumerate(dims):
            fit0 = (w0 <= width and h0 <= depth)
            fit1 = (h0 <= width and w0 <= depth)
            if not (fit0 or fit1):
                feasible = False
                break
            if w0 != h0 and fit0 and fit1:
                r = m.NewBoolVar(f'r{i}')
                wi = m.NewIntVar(min(w0, h0), max(w0, h0), f'w{i}')
                hi = m.NewIntVar(min(w0, h0), max(w0, h0), f'h{i}')
                m.Add(wi == w0).OnlyEnforceIf(r.Not())
                m.Add(wi == h0).OnlyEnforceIf(r)
                m.Add(hi == h0).OnlyEnforceIf(r.Not())
                m.Add(hi == w0).OnlyEnforceIf(r)
            elif fit0:
                r, wi, hi = None, w0, h0
            else:
                r, wi, hi = None, h0, w0
            x = m.NewIntVar(0, width, f'x{i}')
            y = m.NewIntVar(0, depth, f'y{i}')
            xe = m.NewIntVar(0, width, f'xe{i}')
            ye = m.NewIntVar(0, depth, f'ye{i}')
            m.Add(xe == x + wi)
            m.Add(ye == y + hi)
            xivs.append(m.NewIntervalVar(x, wi, xe, f'xi{i}'))
            yivs.append(m.NewIntervalVar(y, hi, ye, f'yi{i}'))
            xs.append(x)
            ys.append(y)
            rots.append(r)
        if not feasible:
            continue
        m.AddNoOverlap2D(xivs, yivs)
        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = per_limit
        solver.parameters.num_search_workers = 8
        solver.parameters.random_seed = 42
        status = solver.Solve(m)
        if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            continue
        placed: List[tuple] = []
        for i, c in enumerate(cols):
            col2 = dict(c)
            col2['_src'] = c  # 同 _cpsat_pack_2d：保留原柱引用防重复装箱
            if rots[i] is not None and solver.Value(rots[i]) == 1:
                col2['xlen'], col2['ylen'] = c['ylen'], c['xlen']
            placed.append((
                col2,
                float(solver.Value(xs[i]) * s),
                float(solver.Value(ys[i]) * s),
            ))
        return placed, []
    return [], list(cols)


def _enumerate_patterns(types, counts, target, pallet_dims, tol, heights=None,
                        weights=None, weight_cap=None):
    """枚举"指数达标 + 面积可行"的候选盘 pattern（柱类型计数向量）。

    几何用**面积必要条件**（柱底面积和 ≤ 盘面积）筛，不要求 265 网格能整齐
    摆下——真正的摆放交给落地阶段（先网格、装不下用 CP-SAT 精确摆柱，允许
    旋转/混合列宽）。这样不漏"面积可行但网格量化损失差几根"的达标组合
    （如 93% 填充的混合底面订单）。仅在柱类型少时调用，规模可控、拿全局最优。

    heights：平顶模式（正常订单）时传入与 types 对齐的柱高列表，pattern 只
    允许使用同一柱高的类型（盘内柱严格等高 → 顶面天然平）。None＝不限制。

    weights/weight_cap：限重生效时传入与 types 对齐的柱重列表与整盘限重，
    pattern 总重超限即剪掉。限重是线性可加约束，同类型柱重量唯一（柱重已并入
    类型键），因此这里是**精确剪枝**而非保守估计——达标率损失恰好等于数学下界。
    """
    cap_area = (float(pallet_dims.get('length', 0) or 0)
                * float(pallet_dims.get('width', 0) or 0))
    fp_area = []  # 各类型柱底面积
    per_cap = []  # 各类型一盘内用量上界 = 该底面满盘根数（几何上界）
    for t in types:
        xl, yl = _fp_orient(t[0])
        fp_area.append(xl * yl)
        per_cap.append(max(1, _orient_per(xl, yl, pallet_dims, tol)))
    # 单类型一盘内最多放 per_cap 根同底面柱（放不下更多）；用它替代固定
    # _PATTERN_TYPE_CAP=40 收紧枚举空间，让更多组走精确 ILP，且不漏解
    # （超过 per_cap 的组合几何上不可行，面积约束本就会剪掉）。
    ranges = [range(0, min(counts[i], per_cap[i]) + 1) for i in range(len(types))]
    patterns = []
    for combo in itertools.product(*ranges):
        if sum(combo) == 0:
            continue
        if heights is not None:
            used_heights = {
                heights[i] for i in range(len(types)) if combo[i]
            }
            if len(used_heights) > 1:
                continue
        idx = sum(combo[i] * types[i][1] for i in range(len(types)))
        if idx < target - 1e-9 or idx > target + _OVERFLOW + 1e-9:
            continue
        if weights is not None and weight_cap is not None:
            total_w = sum(
                combo[i] * weights[i] for i in range(len(types))
            )
            if total_w > weight_cap + 1e-6:
                continue
        area = sum(combo[i] * fp_area[i] for i in range(len(types)))
        if area <= cap_area + 1e-6:
            patterns.append(combo)
    return patterns


def _solve_ilp(patterns, counts, time_limit=20.0):
    """Set-Partitioning：max 达标盘数，s.t. 每柱类型用量 ≤ 库存。返回每 pattern 用量。"""
    m = cp_model.CpModel()
    x = [m.NewIntVar(0, max(counts) if counts else 0, f'x{p}') for p in range(len(patterns))]
    for i in range(len(counts)):
        m.Add(sum(patterns[p][i] * x[p] for p in range(len(patterns))) <= counts[i])
    m.Maximize(sum(x))
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit
    solver.parameters.num_search_workers = 8
    solver.Solve(m)
    return [int(round(solver.Value(x[p]))) for p in range(len(patterns))]


def _same_type_boards(pools, target, pallet_dims, tol, weight_cap=None):
    """同类满盘：每个柱类型尽量铺满达标盘（无损主力）。就地消耗 pools，返回 [placed]。

    weight_cap：整盘限重（kg）。同类型柱重量不一定相同（同 (底面,指数) 可能来自
    不同箱型），故按实际取到的柱逐一累加判定，超限就不出这盘、把柱留给混合装盘。
    """
    boards = []
    for t in list(pools.keys()):
        cl = pools[t]
        if not cl or t[1] <= 0:
            continue
        xl, yl = _fp_orient(t[0])
        placed_full, _ = _grid_pack([{'xlen': xl, 'ylen': yl}] * 60, pallet_dims, tol)
        per = len(placed_full)
        if per <= 0:
            continue
        need = max(1, int(-(-(target) // t[1])))  # ceil(target/idx) 根达标
        if need > per:
            continue  # 一盘铺满都不够达标 → 留给混合
        while len(cl) >= need:
            take = cl[:need]
            if weight_cap is not None and sum(
                column_weight(c) for c in take
            ) > weight_cap + 1e-6:
                break  # 达标所需根数已超限 → 本类型整体留给混合装盘
            del cl[:need]
            placed, _u = _grid_pack(take, pallet_dims, tol)
            boards.append(placed)
    return boards


def _greedy_mixed_boards(cols, target, pallet_dims, tol, weight_cap=None):
    """贪心混合装盘：逐盘把柱塞到网格装满（最大化填充→最大化达标），收口。
    每盘优先放"放进去仍能装下、且推高指数最多"的柱；网格放满即收口。
    weight_cap 给定时，超过整盘限重的柱不再加入本盘（留给下一盘）。
    返回 (boards=[placed], leftover_cols)。"""
    remaining = list(cols)
    boards = []
    while remaining:
        plate = []
        plate_weight = 0.0
        # 反复挑一根"能装下"的柱加入，直到没有柱能再放进本盘
        progressed = True
        while progressed:
            progressed = False
            # 指数大的优先（快到 target），其次底面大的（占满空间）
            for c in sorted(remaining, key=lambda c: (-c['idx'], -(c['xlen'] * c['ylen']))):
                col_w = column_weight(c)
                if (
                    weight_cap is not None
                    and plate
                    and plate_weight + col_w > weight_cap + 1e-6
                ):
                    continue
                _, unplaced = _grid_pack(plate + [c], pallet_dims, tol)
                if not unplaced:
                    plate.append(c)
                    plate_weight += col_w
                    remaining.remove(c)
                    progressed = True
                    break
        if not plate:
            break
        boards.append(_grid_pack(plate, pallet_dims, tol)[0])
    return boards, remaining


class GlobalColumnPacker:
    """全局列式装箱 + 柱级组合优化主装箱器。pack_group 兼容现有契约。"""

    def __init__(self, constraint_config=None):
        if constraint_config is None:
            from ..config.constraint_config import ConstraintConfig
            constraint_config = ConstraintConfig()
        self._cfg = constraint_config
        self._targets = dict(PALLET_INDEX_TARGETS)
        self._cols_cache = (None, None)  # (id(boxes), cols)：suits_group 与 pack_group 复用

    def _new_board(self, pallet_type, sales_order_no, seq, placed, packer, pallet_dims, target, gap=None):
        """组装一个盘并跑整盘门禁。门禁不过返回 None（调用方把柱退回残料 beam 兜底）。

        gap：柱间落地容差。CP-SAT 精确摆柱传 0（柱已紧贴无重叠）；265 网格摆柱
        传 None（默认 size_tolerance，柱间留缝）。门禁带 target，达标盘免 gap 校验
        （剩余空隙是高密度装载的几何必然，非偷懒）。
        """
        items = _assemble(placed, packer, pallet_dims, gap=gap)
        gate = validate_pallet_constraints(
            {'packed_items': items}, pallet_dims, constraint_config=self._cfg,
            target_mpm=target)
        if not gate.get('is_valid'):
            return None
        total = sum(float(b.get('min_pack_multiple', 0) or 0) for b in items)
        status = 'SUCCESS' if (target is not None and total + 1e-9 >= target) else 'FAILED'
        return {
            'pallet_id': f'{pallet_type}-{sales_order_no}-{seq}',
            'pallet_type': pallet_type,
            'sales_order_no': sales_order_no,
            'packed_items': items,
            'mpm_total': total,
            'mpm_target': target,
            'mpm_gap': (target - total) if target is not None else None,
            'mpm_status': status,
            'stability_checks': {'status': 'SUCCESS'},
        }

    def suits_group(self, boxes_in_group, target_mpm) -> bool:
        """判断该分组是否适合 GCP（规则数据）。不适合则由调用方回退旧算法。

        判据：凑柱后，能"单类满盘达标"或"与同类拼盘易达标"的柱占绝大多数。
        若大量柱是"非满柱 + 大底面"（满盘都到不了 target，柱化注定不达标），
        说明是不规则数据，GCP 会退步，应回退 baseline。
        """
        if target_mpm is None or not boxes_in_group:
            return False
        pallet_dims = boxes_in_group[0]['pallet_dims']
        # 限重生效时按限重凑柱，使适用性判据与 pack_group 实际会造出的柱一致
        cols = _build_columns(
            boxes_in_group, pallet_dims,
            weight_cap_for_group(boxes_in_group, pallet_dims, self._cfg),
        )
        self._cols_cache = (id(boxes_in_group), cols)  # 供随后的 pack_group 复用，免重复凑柱
        if not cols:
            return False
        target = float(target_mpm)
        # 每种底面"满盘指数上界"是否够 target（够 → 该底面的柱有达标希望）
        cap_by_fp = {}
        good_idx = 0.0
        total_idx = 0.0
        for c in cols:
            total_idx += c['idx']
            fp = c['fp']
            if fp not in cap_by_fp:
                xl, yl = _fp_orient(fp)
                # 真实几何 per（取两朝向较优），替代 _grid_pack 的 350/265 量化估算。
                # 满盘最高指数 = 每盘根数 × 该底面满柱指数（用本柱指数近似上界）
                cap_by_fp[fp] = _orient_per(xl, yl, pallet_dims, 2.0)
            # 该柱所在底面，满盘装 per 根同指数柱能否达标
            if cap_by_fp[fp] * c['idx'] >= target - 1e-9:
                good_idx += c['idx']
        # 有达标希望的柱指数占比 ≥ 70% 才用 GCP
        return total_idx > 0 and good_idx / total_idx >= 0.70

    def partition_suitable(self, boxes_in_group, target_mpm):
        """把一个销售订单组按底面切成 (regular, rest)。

        regular = 满盘能达标的底面的箱（走 GCP 精确 ILP）；rest = 其余底面的箱
        （走 baseline）。用于 workflow「组内子聚类」：当一张大订单里混有规则
        可列式子集（如 668 那种）与杂箱时，把规则子集单独抽出走 ILP，避免整组
        因杂箱被拖累退化（suits_group=False 整组回退 / 柱类型超阈贪心降级）。

        判据与 suits_group 同源（逐底面：满盘根数 × 该底面最大满柱指数 ≥ target）。
        - 纯规则组 → 所有底面都达标 → (全部, [])，调用方不拆，走原 GCP（零回归）。
        - 纯杂组   → 无达标底面     → ([], 全部)，调用方不拆，走原 baseline（零回归）。
        - 混合组   → (规则子集, 杂箱)，调用方拆成两个子组分别处理。
        """
        if target_mpm is None or not boxes_in_group:
            return list(boxes_in_group), []
        pallet_dims = boxes_in_group[0]['pallet_dims']
        cols = _build_columns(
            boxes_in_group, pallet_dims,
            weight_cap_for_group(boxes_in_group, pallet_dims, self._cfg),
        )
        if not cols:
            return [], list(boxes_in_group)
        target = float(target_mpm)
        cap_by_fp: Dict[Tuple[int, int], int] = {}
        max_idx_by_fp: Dict[Tuple[int, int], float] = defaultdict(float)
        for c in cols:
            fp = c['fp']
            if fp not in cap_by_fp:
                xl, yl = _fp_orient(fp)
                cap_by_fp[fp] = _orient_per(xl, yl, pallet_dims, 2.0)
            if c['idx'] > max_idx_by_fp[fp]:
                max_idx_by_fp[fp] = c['idx']
        good_fp = {
            fp for fp in cap_by_fp
            if cap_by_fp[fp] * max_idx_by_fp[fp] >= target - 1e-9
        }

        def _fp_of(b):
            return tuple(sorted((
                int(round(float(b.get('length', 0) or 0))),
                int(round(float(b.get('width', 0) or 0))),
            )))

        regular = [b for b in boxes_in_group if _fp_of(b) in good_fp]
        rest = [b for b in boxes_in_group if _fp_of(b) not in good_fp]
        return regular, rest

    def pack_group(self, pallet_type, sales_order_no, boxes_in_group, target_mpm):
        """Evaluate distinct columnizations and keep the strongest GCP plan."""

        import time
        started = time.time()
        pallet_dims = boxes_in_group[0]['pallet_dims']
        candidates = _build_column_candidates(
            boxes_in_group, pallet_dims, target_mpm,
            weight_cap_for_group(boxes_in_group, pallet_dims, self._cfg),
        )
        if not candidates:
            candidates = [('height_first', [])]

        evaluated = []
        diagnostics = []
        for strategy_name, columns in candidates:
            plans, runtime, diag = self._pack_group_with_columns(
                pallet_type,
                sales_order_no,
                boxes_in_group,
                target_mpm,
                columns,
                strategy_name,
            )
            bailed = bool(diag.get('gcp_bailout'))
            gates_passed = _gcp_candidate_passes_gates(
                boxes_in_group, plans, self._cfg
            )
            rank = _plan_rank(plans)
            diagnostics.append({
                'strategy': strategy_name,
                'rank': list(rank),
                'pallets': len(plans),
                'success': rank[0],
                'gcp_bailout': bailed,
                'gates_passed': gates_passed,
                'packing_seconds': round(
                    float(runtime.get('packing', 0.0) or 0.0), 6
                ),
            })
            evaluated.append((
                gates_passed and not bailed,
                rank,
                strategy_name,
                plans,
                diag,
            ))

        normal_viable = [entry for entry in evaluated if entry[0]]
        captured = max(
            (entry[1][0] for entry in normal_viable), default=0
        )
        total_index = sum(
            float(box.get('min_pack_multiple', 0) or 0)
            for box in boxes_in_group
        )
        upper_bound = (
            int(total_index // float(target_mpm))
            if target_mpm is not None and target_mpm > 0 else 0
        )
        exact_enabled = bool(getattr(
            self._cfg, 'cpsat_target_subset_enabled', True
        ))
        if exact_enabled and captured < upper_bound:
            exact_result = self._build_exact_target_candidate(
                pallet_type,
                sales_order_no,
                boxes_in_group,
                target_mpm,
                pallet_dims,
            )
            if exact_result is not None:
                plans, exact_runtime, diag = exact_result
                strategy_name = 'cpsat_target_subset'
                bailed = bool(diag.get('gcp_bailout'))
                gates_passed = _gcp_candidate_passes_gates(
                    boxes_in_group, plans, self._cfg
                )
                rank = _plan_rank(plans)
                diagnostics.append({
                    'strategy': strategy_name,
                    'rank': list(rank),
                    'pallets': len(plans),
                    'success': rank[0],
                    'gcp_bailout': bailed,
                    'gates_passed': gates_passed,
                    'packing_seconds': round(float(
                        exact_runtime.get('packing', 0.0) or 0.0
                    ), 6),
                    'subset_attempts': diag.get(
                        'cpsat_target_subset_attempts', 0
                    ),
                })
                evaluated.append((
                    gates_passed and not bailed,
                    rank,
                    strategy_name,
                    plans,
                    diag,
                ))

        viable = [entry for entry in evaluated if entry[0]]
        chosen = max(viable or evaluated, key=lambda entry: entry[1])
        _valid, _rank, strategy_name, plans, diag = chosen
        diag = dict(diag)
        if not viable:
            diag['gcp_bailout'] = True
            diag['gcp_candidate_gate_failure'] = True
        diag['gcp_selected_column_strategy'] = strategy_name
        diag['gcp_column_candidates'] = diagnostics
        runtime = {'packing': time.time() - started, 'topup': 0.0, 'retry': 0.0}
        return plans, runtime, diag

    def _place_exact_target_subset(
        self,
        pallet_type,
        sales_order_no,
        selected_boxes,
        target_mpm,
        pallet_dims,
    ):
        """Place every selected box through exact 2D columns and exact stacking."""

        if not selected_boxes:
            return None
        packer = BeamSearchPacker(
            pallet_dims=pallet_dims, constraint_config=self._cfg
        )
        selected_ids = sorted(str(box.get('id')) for box in selected_boxes)
        # 平顶模式：目标子集盘同样要求柱等高 + 完美平铺落地
        flat_required = flat_top_group_required(
            self._cfg,
            selected_boxes[0].get('pallet_type', pallet_type),
            selected_boxes,
        )
        subset_time_limit = float(getattr(
            self._cfg,
            'cpsat_target_subset_time_limit_seconds',
            3.0,
        ))
        weight_cap = weight_cap_for_group(
            selected_boxes, pallet_dims, self._cfg,
        )
        for _strategy, columns in _build_column_candidates(
            selected_boxes, pallet_dims, target_mpm, weight_cap,
        ):
            if flat_required:
                if len({_col_height_key(c) for c in columns}) > 1:
                    continue  # 柱高不齐 → 顶面必不平，直接换下一种凑柱
                placed, unplaced = _cpsat_tile_2d(
                    columns, pallet_dims, time_limit=subset_time_limit,
                )
            else:
                placed, unplaced = _cpsat_pack_2d(
                    columns, pallet_dims, time_limit=subset_time_limit,
                )
            if unplaced or len(placed) != len(columns):
                continue
            placed = _center_placed(placed, pallet_dims, packer.size_tolerance)
            board = self._new_board(
                pallet_type,
                sales_order_no,
                1,
                placed,
                packer,
                pallet_dims,
                target_mpm,
                gap=0.0,
            )
            if board is None:
                continue
            actual_ids = sorted(
                str(box.get('id')) for box in board['packed_items']
            )
            if actual_ids == selected_ids and board['mpm_status'] == 'SUCCESS':
                return board
        return None

    def _build_exact_target_candidate(
        self,
        pallet_type,
        sales_order_no,
        boxes_in_group,
        target_mpm,
        pallet_dims,
    ):
        """Retry CP-SAT subsets with no-good cuts until exact placement works."""

        import time
        started = time.time()
        max_attempts = max(1, int(getattr(
            self._cfg, 'cpsat_target_subset_max_attempts', 6
        )))
        time_limit = float(getattr(
            self._cfg, 'cpsat_target_subset_time_limit_seconds', 3.0
        ))
        weight_cap = weight_cap_for_group(
            boxes_in_group, pallet_dims, self._cfg,
        )
        excluded = set()
        diag = {
            'gcp_bailout': False,
            'gcp_column_strategy': 'cpsat_target_subset',
            'cpsat_target_subset_attempts': 0,
            'cpsat_target_subset_geometry_failures': 0,
            'cpsat_target_subset_gate_failures': 0,
        }
        for _attempt in range(max_attempts):
            selected = _select_target_subset_cpsat(
                boxes_in_group,
                pallet_dims,
                float(target_mpm),
                excluded_signatures=excluded,
                time_limit=time_limit,
                weight_cap=weight_cap,
            )
            if not selected:
                break
            diag['cpsat_target_subset_attempts'] += 1
            signature = frozenset(str(box.get('id')) for box in selected)
            board = self._place_exact_target_subset(
                pallet_type,
                sales_order_no,
                selected,
                target_mpm,
                pallet_dims,
            )
            if board is None:
                diag['cpsat_target_subset_geometry_failures'] += 1
                excluded.add(signature)
                continue

            selected_ids = {box.get('id') for box in selected}
            residual = [
                box for box in boxes_in_group
                if box.get('id') not in selected_ids
            ]
            residual_plans = []
            residual_bailout = False
            if residual:
                residual_candidates = _build_column_candidates(
                    residual, pallet_dims, target_mpm,
                    weight_cap_for_group(residual, pallet_dims, self._cfg),
                )
                residual_columns = (
                    residual_candidates[0][1]
                    if residual_candidates else []
                )
                residual_plans, _runtime, residual_diag = (
                    self._pack_group_with_columns(
                        pallet_type,
                        sales_order_no,
                        residual,
                        target_mpm,
                        residual_columns,
                        'cpsat_target_residual',
                    )
                )
                residual_bailout = bool(
                    residual_diag.get('gcp_bailout')
                )
            plans = [board] + residual_plans
            for seq, plan in enumerate(plans, 1):
                plan['pallet_id'] = (
                    f'{pallet_type}-{sales_order_no}-{seq}'
                )
            if residual_bailout or not _gcp_candidate_passes_gates(
                boxes_in_group, plans, self._cfg
            ):
                diag['cpsat_target_subset_gate_failures'] += 1
                excluded.add(signature)
                continue
            return (
                plans,
                {'packing': time.time() - started,
                 'topup': 0.0, 'retry': 0.0},
                diag,
            )
        return None

    def _pack_group_with_columns(
        self,
        pallet_type,
        sales_order_no,
        boxes_in_group,
        target_mpm,
        columns,
        strategy_name,
    ):
        """Run the original GCP pipeline for one fixed columnization."""

        import time
        t0 = time.time()
        pallet_dims = boxes_in_group[0]['pallet_dims']
        packer = BeamSearchPacker(pallet_dims=pallet_dims, constraint_config=self._cfg)
        tol = packer.size_tolerance
        cols = list(columns)
        plan: List[Dict] = []
        seq = 1
        boards: List[tuple] = []  # [(placed, gap)]：gap=0=CP-SAT 紧贴落地，None=265 网格
        # 平顶模式（正常订单 × 范围内托盘类型）：达标盘须顶面平 + 整圈不缺。
        # 生成侧三处收紧：柱类型键并入柱高（盘内柱等高）、pattern 限同高、
        # 落地要求外圈铺满（网格预检不过改 CP-SAT 完美平铺）。
        flat_required = flat_top_group_required(
            self._cfg, pallet_type, boxes_in_group,
        )
        flat_seam = flat_top_seam_tolerance(self._cfg)
        # 整盘限重：仅当本组「单盘重量上界 > 限重」时才启用，否则约束恒不可能
        # 触发，全部限重逻辑短路（柱类型键/模式枚举/贪心装盘均走历史路径），
        # 零回归可证。见 geometry/weight_limit.weight_cap_for_group。
        weight_cap = weight_cap_for_group(
            boxes_in_group, pallet_dims, self._cfg,
        )

        if target_mpm is not None and cols:
            target = float(target_mpm)
            # 柱类型键：限重生效时并入柱重，使 pattern 总重有确定值 ⇒ 精确剪枝。
            # 代价是类型数翻倍、枚举空间可能顶过 _MAX_ENUM 而被迫退贪心；此时
            # 用 _merge_weight_classes 合并最接近的重量类（上界取组内最大，仍
            # 可靠），把类型数压回可负担范围。限重不会把组挤到贪心路径上。
            pools = _build_pools(cols, flat_required, weight_cap is not None)
            types = sorted(pools.keys())
            counts = [len(pools[t]) for t in types]
            use_ilp = _ilp_affordable(types, counts, pallet_dims, tol)
            if weight_cap is not None and not use_ilp:
                merged = _merge_weight_classes(
                    pools, pallet_dims, tol,
                    w_pos=(3 if flat_required else 2),
                )
                if merged is not None:
                    pools = merged
                    types = sorted(pools.keys())
                    counts = [len(pools[t]) for t in types]
                    use_ilp = True
            if use_ilp:
                # 同 pattern 的盘柱型构成完全相同（2D 摆放只看底面）：
                # - 成功布局缓存：首盘 CP-SAT 解出满解后，后续同 pattern 盘
                #   直接按底面复用该布局（零耗时、消除同 run 内多线程波动）；
                # - 失败短重试：装不满的 pattern 后续盘只给短时限重试，最多
                #   _CPSAT_MAX_FAILS 次后跳过——不再对注定失败的重复 pattern
                #   反复烧满时限（慢机器上这是 GCP 回退前的主要耗时）。
                # 平顶模式多轮重解：pattern 可能"指数/面积可行但铺不成完整
                # 矩形"——铺砌失败的 pattern 进黑名单，用剩余柱重新枚举+重解
                # ILP（最多 _FLAT_RESOLVE_ROUNDS 轮），让库存换组合再凑达标盘；
                # 否则失败 pattern 的柱整批退残料，白丢达标机会。非平顶模式
                # 单轮，行为与历史一致（零回归）。
                layout_cache: Dict[tuple, List[tuple]] = {}
                banned_patterns: set = set()
                remaining_pools = {t: list(pools[t]) for t in types}
                rounds = _FLAT_RESOLVE_ROUNDS if flat_required else 1
                for _round in range(rounds):
                    round_types = [t for t in types if remaining_pools[t]]
                    if not round_types:
                        break
                    round_counts = [
                        len(remaining_pools[t]) for t in round_types
                    ]
                    # 柱类型键的可选分量位置：flat 在前、weight 在后。
                    # 键里的重量分量始终是该类型柱重的可靠上界（未合并时即
                    # 精确值，合并后为组内最大值）。
                    _h_pos = 2 if flat_required else None
                    _w_pos = (
                        (3 if flat_required else 2)
                        if weight_cap is not None else None
                    )
                    patterns = _enumerate_patterns(
                        round_types, round_counts, target, pallet_dims, tol,
                        heights=(
                            [t[_h_pos] for t in round_types]
                            if _h_pos is not None else None
                        ),
                        weights=(
                            [t[_w_pos] for t in round_types]
                            if _w_pos is not None else None
                        ),
                        weight_cap=weight_cap,
                    )
                    if banned_patterns:
                        patterns = [
                            combo for combo in patterns
                            if _pattern_key(round_types, combo)
                            not in banned_patterns
                        ]
                    if not patterns:
                        break
                    usage = _solve_ilp(
                        patterns, round_counts, time_limit=_ILP_TIME,
                    )
                    if not any(usage):
                        break
                    pool_idx = {t: 0 for t in round_types}
                    fail_count: Dict[int, int] = {}
                    placed_col_ids: set = set()
                    round_failed = False
                    for p, v in enumerate(usage):
                        pkey = _pattern_key(round_types, patterns[p])
                        for _ in range(v):
                            plate = []
                            for i, t in enumerate(round_types):
                                for _k in range(patterns[p][i]):
                                    plate.append(
                                        remaining_pools[t][pool_idx[t]]
                                    )
                                    pool_idx[t] += 1
                            # 先试 265 网格（快、无缝）；网格量化损失装不下时用
                            # CP-SAT 精确摆柱（允许旋转/混合列宽，多装；达标盘免
                            # gap）。平顶模式额外要求网格结果外圈铺满，否则改走
                            # CP-SAT 完美平铺（面积精确 ⇒ 无内洞、四壁不缺角）。
                            placed, unpl = _grid_pack(plate, pallet_dims, tol)
                            grid_ok = not unpl and placed
                            if grid_ok and flat_required:
                                grid_ok = rects_ring_complete(
                                    [(x, y, float(c2['xlen']),
                                      float(c2['ylen']))
                                     for c2, x, y in placed],
                                    seam_tolerance_mm=flat_seam,
                                )
                            if not grid_ok:
                                cached = layout_cache.get(pkey)
                                if cached is not None:
                                    placed = _apply_layout(cached, plate)
                                    if placed:
                                        boards.append((placed, 0.0))
                                        placed_col_ids |= {
                                            id(c2.get('_src', c2))
                                            for c2, _x, _y in placed
                                        }
                                        continue
                                fails = fail_count.get(p, 0)
                                if fails >= _CPSAT_MAX_FAILS:
                                    continue  # 该 pattern 已多次证明装不满 → 退残料
                                tl = (_CPSAT_TIME if fails == 0
                                      else _CPSAT_RETRY_TIME)
                                if flat_required:
                                    placed, unpl = _cpsat_tile_2d(
                                        plate, pallet_dims, time_limit=tl)
                                else:
                                    placed, unpl = _cpsat_pack_2d(
                                        plate, pallet_dims, time_limit=tl)
                                if unpl:
                                    fail_count[p] = fails + 1
                                    banned_patterns.add(pkey)
                                    round_failed = True
                                if placed:
                                    placed = _center_placed(
                                        placed, pallet_dims, tol,
                                    )
                                    if not unpl:
                                        # 满解 → 缓存居中后布局，供同 pattern 复用
                                        layout_cache[pkey] = [
                                            (_fp_key(c2.get('_src', c2)),
                                             c2['xlen'] != c2.get(
                                                 '_src', c2)['xlen'],
                                             x, y)
                                            for c2, x, y in placed
                                        ]
                                    boards.append((placed, 0.0))
                                    placed_col_ids |= {
                                        id(c2.get('_src', c2))
                                        for c2, _x, _y in placed
                                    }
                            else:
                                boards.append((placed, None))
                                placed_col_ids |= {
                                    id(c2) for c2, _x, _y in placed
                                }
                    for t in round_types:
                        remaining_pools[t] = [
                            c for c in remaining_pools[t]
                            if id(c) not in placed_col_ids
                        ]
                    if not round_failed:
                        break
            else:
                # 2) 大组 → 同类满盘（无损）+ 贪心混合（快、鲁棒）
                for placed in _same_type_boards(
                    pools, target, pallet_dims, tol, weight_cap,
                ):
                    boards.append((placed, None))
                rest = [c for cl in pools.values() for c in cl]
                mixed, _rest = _greedy_mixed_boards(
                    rest, target, pallet_dims, tol, weight_cap,
                )
                for placed in mixed:
                    boards.append((placed, None))

            # 落地：每盘跑整盘门禁，过则进 plan、其柱计为已用；不过则其柱退回残料。
            used_ids = set()
            for placed, gap in boards:
                board = self._new_board(
                    pallet_type, sales_order_no, seq, placed, packer, pallet_dims,
                    target_mpm, gap=gap)
                if board is None:  # 门禁不过 → 柱退回残料，由 beam 兜底
                    continue
                plan.append(board)
                seq += 1
                # CP-SAT 落地的 col 是旋转浅拷贝，经 _src 找回原柱；网格落地即原柱
                used_ids |= {id(c.get('_src', c)) for c, _x, _y in placed}
            cols = [c for c in cols if id(c) not in used_ids]  # 残料柱（含门禁不过盘的柱）

        # 残料柱（或无 ILP 时全部柱）：拆回箱子交给 beam 装箱兜底。
        # beam 放置时逐箱校验全部约束（间隙/支撑/吸盘），保证残料盘必过门禁；
        # 达标优先、装不满则尽量满。半空柱造成的内部缝由 beam 自然避免。
        residual_boxes = [b for c in cols for b in c['boxes']]

        # 提前止损：盘数只增不减、剩余箱至少还需 ceil(体积/托盘容积) 盘。
        # 一旦「已成盘数 + 残料体积下界」注定超过 workflow 的爆盘回退阈值
        # （理论盘数+1），继续装只是白烧时间——立即带 gcp_bailout 标记返回，
        # 调用方按原语义丢弃并回退 baseline（结果等价，只是更快）。
        bail_cap = None
        pallet_vol = (
            float(pallet_dims.get('length', 0) or 0)
            * float(pallet_dims.get('width', 0) or 0)
            * float(pallet_dims.get('height', 0) or 0))
        if target_mpm is not None and pallet_vol > 0:
            _tm = sum(float(b.get('min_pack_multiple', 0) or 0)
                      for b in boxes_in_group)
            bail_cap = max(1, int(-(-_tm // float(target_mpm)))) + 1

        def _doomed() -> bool:
            if bail_cap is None:
                return False
            vol = sum(
                float(b.get('length', 0) or 0)
                * float(b.get('width', 0) or 0)
                * float(b.get('height', 0) or 0)
                for b in residual_boxes)
            lb = int(-(-vol // pallet_vol)) if vol > 0 else 0
            return len(plan) + lb > bail_cap

        bailed = False
        beam_dead = False  # beam 已无法装下任何残料 → 剩余全部单柱兜底，不再空跑 beam
        while residual_boxes:
            if _doomed():
                bailed = True
                break
            placed_items = []
            if not beam_dead:
                placed_items, _unfitted = packer.pack(
                    residual_boxes, target_mpm=target_mpm,
                    num_restarts=2, beam_width=4, candidate_limit=16,
                    stop_when_target_met=True, allow_skip_items=True,
                )
            # 平顶模式：残料盘若"达标但形状不合格"，拆顶降级为尾盘（尾盘
            # 豁免形状约束）；拆下的箱仍在 residual_boxes（按保留箱 id 过滤），
            # 留给下一盘。拆箱在"暴露合规子堆"上提前停止，能保住达标盘。
            if (
                placed_items
                and flat_required
                and target_mpm is not None
                and sum(float(b.get('min_pack_multiple', 0) or 0)
                        for b in placed_items) + 1e-9 >= float(target_mpm)
                and not check_flat_top_full_perimeter(
                    placed_items, seam_tolerance_mm=flat_seam,
                )['is_valid']
            ):
                placed_items, _flat_trimmed = trim_items_to_tail(
                    placed_items, float(target_mpm), flat_seam,
                )
            if not placed_items:
                # beam 一个都装不下（极罕见）→ 取首箱单独成盘兜底，守恒优先（即便门禁
                # 不过也收下，绝不丢箱）。须经 _assemble 写 position/raw_*/吸盘，否则
                # output_formatter 取 position 会崩。剩余箱继续单柱兜底直到清空。
                beam_dead = True
                one = residual_boxes[0]
                items_one = build_centered_single_box_solution(
                    [one], pallet_dims,
                    xy_tolerance=tol,
                    z_tolerance=packer.z_tolerance,
                    constraint_config=self._cfg,
                )
                if not items_one:
                    col = {'xlen': float(one.get('length', 0) or 0),
                           'ylen': float(one.get('width', 0) or 0), 'boxes': [one]}
                    items_one = _assemble(
                        [(col, 0.0, 0.0)], packer, pallet_dims
                    )
                total_one = sum(float(b.get('min_pack_multiple', 0) or 0) for b in items_one)
                plan.append({
                    'pallet_id': f'{pallet_type}-{sales_order_no}-{seq}',
                    'pallet_type': pallet_type,
                    'sales_order_no': sales_order_no,
                    'packed_items': items_one,
                    'mpm_total': total_one,
                    'mpm_target': target_mpm,
                    'mpm_gap': (target_mpm - total_one) if target_mpm else None,
                    'mpm_status': 'FAILED',
                    'stability_checks': {'status': 'UNKNOWN'},
                })
                seq += 1
                residual_boxes = residual_boxes[1:]
                continue
            total = sum(float(b.get('min_pack_multiple', 0) or 0) for b in placed_items)
            status = 'SUCCESS' if (target_mpm is not None and total + 1e-9 >= target_mpm) else 'FAILED'
            plan.append({
                'pallet_id': f'{pallet_type}-{sales_order_no}-{seq}',
                'pallet_type': pallet_type,
                'sales_order_no': sales_order_no,
                'packed_items': placed_items,
                'mpm_total': total,
                'mpm_target': target_mpm,
                'mpm_gap': (target_mpm - total) if target_mpm is not None else None,
                'mpm_status': status,
                'stability_checks': {'status': 'SUCCESS'},
            })
            seq += 1
            placed_ids = {b['id'] for b in placed_items}
            residual_boxes = [b for b in residual_boxes if b['id'] not in placed_ids]

        success = sum(1 for b in plan if b['mpm_status'] == 'SUCCESS')
        index_diag = {
            'box_count': len(boxes_in_group),
            'total_mpm': sum(float(b.get('min_pack_multiple', 0) or 0) for b in boxes_in_group),
            'theoretical_success_pallets': int(
                sum(float(b.get('min_pack_multiple', 0) or 0) for b in boxes_in_group) // target_mpm
            ) if target_mpm else 0,
            'residual_mpm': 0,
            'global_column_packer': {'pallets': len(plan), 'success': success},
            'gcp_bailout': bailed,
            'gcp_column_strategy': strategy_name,
        }
        runtime = {'packing': time.time() - t0, 'topup': 0.0, 'retry': 0.0}
        return plan, runtime, index_diag
