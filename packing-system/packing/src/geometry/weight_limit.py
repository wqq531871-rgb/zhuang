"""托盘整体限重约束（甲方 2026-09 需求：整垛箱子重量和 ≤ 1000kg）。

与本项目其它硬约束的**结构性差异**（决定了实现方式）：

- 限重是 ``Σ weight(箱) ≤ W``，**可加且与几何无关**——只取决于「哪些箱在盘上」，
  与位置、朝向、堆叠方式无关。支撑率/间隙/重心/平顶不缺角全部是位置相关的。
- **可精确入模**：线性可加 ⇒ 能直接写进 GCP 的 Set-Partitioning ILP 与 CP-SAT
  子集选择模型。所以限重不需要「生成侧启发式收紧 + 门禁拦 + 事后修补」那一套，
  达标率的损失恰好等于数学上不可避免的下界。
- **下闭（downward-closed）**：合法箱集的任意子集仍合法 ⇒ 拿掉箱子永不破坏它，
  因此不需要任何拆顶/降级补救（与平顶约束正相反）。

约束与指数目标的竞争强度由 ρ = 重量/指数 唯一决定：MH423C 达标需 192 指数，
限重 1000kg ⇒ 只有盘内平均 ρ > 1000/192 ≈ 5.21 kg/指数 时才可能吃掉达标率。

单箱超重的边界：单箱重量 > W 时该箱在任何盘上都不合法，重排也救不了。为不破坏
守恒（绝不丢箱）也不崩溃，门禁对**单箱盘**豁免限重，由 ``overweight_single_boxes``
供调用方打印告警、交现场核对数据。
"""

from typing import Dict, Iterable, List, Optional, Tuple

# 重量比较容差（kg）。重量是浮点数，用固定小量避免边界抖动。
WEIGHT_EPS = 1e-6

# constraint_config 缺省时的兜底限重（与 ConstraintConfig.max_pallet_weight_kg
# 默认值一致）。门禁有大量不传 config 的历史调用点，此处保证语义一致。
DEFAULT_MAX_PALLET_WEIGHT_KG = 1000.0


def box_weight(box: Dict) -> float:
    """单箱重量（kg）。缺字段/空值＝0（旧测试与外部构造箱不受影响）。"""
    return float(box.get('weight', 0.0) or 0.0)


def items_total_weight(items: Iterable[Dict]) -> float:
    """一组箱子的重量和（kg）。"""
    return sum(box_weight(item) for item in items)


def pallet_weight_cap(constraint_config) -> Optional[float]:
    """取本次运行的整盘限重（kg）；返回 None 表示不限重。

    ``max_pallet_weight_kg <= 0`` 视为关闭约束（完全恢复历史行为）。
    """
    if constraint_config is None:
        cap = DEFAULT_MAX_PALLET_WEIGHT_KG
    else:
        cap = getattr(
            constraint_config,
            'max_pallet_weight_kg',
            DEFAULT_MAX_PALLET_WEIGHT_KG,
        )
    try:
        cap = float(cap)
    except (TypeError, ValueError):
        return None
    return cap if cap > 0 else None


def fits_weight(items: Iterable[Dict], extra_weight: float,
                cap: Optional[float]) -> bool:
    """在 items 之上再加 ``extra_weight`` kg 是否仍不超限。

    放置层/增量门禁的逐箱预检用。cap 为 None（不限重）时恒 True。
    """
    if cap is None:
        return True
    return items_total_weight(items) + float(extra_weight) <= cap + WEIGHT_EPS


def check_pallet_weight(
    items: List[Dict],
    cap: Optional[float],
) -> Optional[Dict]:
    """整盘限重校验。合规返回 None，超重返回违规详情。

    单箱盘豁免：单箱超重是数据异常，拆不动也重排不掉；拦下来只会让守恒兜底
    无路可走（箱子必须落在某个盘上）。此处放行并由调用方告警。
    """
    if cap is None or not items or len(items) <= 1:
        return None
    total = items_total_weight(items)
    if total <= cap + WEIGHT_EPS:
        return None
    return {
        'total_kg': round(total, 3),
        'limit_kg': round(float(cap), 3),
        'excess_kg': round(total - float(cap), 3),
        'box_count': len(items),
    }


def overweight_single_boxes(
    boxes: Iterable[Dict],
    cap: Optional[float],
) -> List[Dict]:
    """挑出「单箱就超过限重」的箱子（数据异常，供入口告警）。"""
    if cap is None:
        return []
    return [b for b in boxes if box_weight(b) > cap + WEIGHT_EPS]


def _box_volume(box: Dict) -> float:
    return (
        float(box.get('length', 0) or 0)
        * float(box.get('width', 0) or 0)
        * float(box.get('height', 0) or 0)
    )


def max_possible_pallet_weight(
    boxes: Iterable[Dict],
    pallet_dims: Dict[str, float],
) -> float:
    """单盘重量的**可靠上界**（kg），用分数背包给出。

    任一盘上箱子的体积和必 ≤ 托盘容积（箱不重叠且都在盘内），所以「按 kg/m³
    降序把箱装满盘容积」得到的重量就是任何一盘重量的上界。比「最大密度 ×
    盘容积」紧得多——后者会被个别异常密度箱放大（实测 5000 数据集里 4 只
    异常箱使粗略上界达 19.6t，分数背包上界只有 654kg）。

    体积 ≤ 0 的箱（异常数据）按无穷密度处理 → 返回 inf（保守判定为可能触发）。
    """
    pallet_volume = (
        float(pallet_dims.get('length', 0) or 0)
        * float(pallet_dims.get('width', 0) or 0)
        * float(pallet_dims.get('height', 0) or 0)
    )
    entries: List[Tuple[float, float, float]] = []  # (密度, 体积, 重量)
    total_weight = 0.0
    for box in boxes:
        weight = box_weight(box)
        total_weight += weight
        volume = _box_volume(box)
        if weight <= 0.0:
            continue
        if volume <= 0.0:
            return float('inf')
        entries.append((weight / volume, volume, weight))
    if pallet_volume <= 0.0:
        return total_weight
    # 全部箱都装得进一盘时，上界就是总重（比分数背包更紧）
    if sum(e[1] for e in entries) <= pallet_volume:
        return total_weight

    entries.sort(key=lambda e: -e[0])
    remaining = pallet_volume
    bound = 0.0
    for density, volume, _weight in entries:
        if remaining <= 0.0:
            break
        take = volume if volume <= remaining else remaining
        bound += density * take
        remaining -= take
    return bound


def weight_cap_for_group(
    boxes: List[Dict],
    pallet_dims: Dict[str, float],
    constraint_config,
) -> Optional[float]:
    """本组是否需要启用限重逻辑；需要则返回限重值，否则 None。

    单盘重量上界 ≤ 限重 ⇒ 约束在本组恒不可能触发 ⇒ 生成侧全部限重逻辑短路，
    柱类型键、模式枚举、贪心装盘一律走历史路径（**零回归可证**，不依赖实测）。
    """
    cap = pallet_weight_cap(constraint_config)
    if cap is None or not boxes:
        return None
    total = items_total_weight(boxes)
    if total <= cap + WEIGHT_EPS:
        return None  # 整组加起来都不超限 → 任何一盘都不可能超限
    if max_possible_pallet_weight(boxes, pallet_dims) <= cap + WEIGHT_EPS:
        return None
    return cap


def column_weight(column: Dict) -> float:
    """柱（同底面垂直堆叠的一摞箱）的总重量（kg）。"""
    return items_total_weight(column.get('boxes', []) or [])
