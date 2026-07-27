# -*- coding: utf-8 -*-
"""扫描成品方案 JSON 的「小面积在下」违例，并给出按托盘状态的分布。

用途：改约束后的守护检查。默认配置下对任意新产出的方案，违例数应为 0；
也可以拿它扫历史方案，量化新约束会影响多少既有布局。

与 tests/verify_solution.py 的区别：verify_solution 跑全部硬约束、聚焦单份方案；
本脚本只看这一条约束，但支持批量文件与通配符，并区分达标/未达标盘，
便于回答"新约束会掉多少达标盘"。

用法：
    python tests/probe/scan_footprint_violations.py <plan.json> [更多文件...]
    python tests/probe/scan_footprint_violations.py "output/success/packing_plan_*.json"

退出码：有违例返回 1，无违例返回 0（便于接进脚本化守护）。
"""
from __future__ import annotations

import glob
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Dict, List, Tuple

try:
    sys.stdout.reconfigure(encoding='utf-8')
except (AttributeError, ValueError):
    pass

project_root = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(project_root))

from src.geometry.overlap import has_positive_xy_overlap as _has_positive_xy_overlap
from src.utils.helpers import passes_footprint_area_below_constraint


def _dims(box: Dict) -> Dict[str, float]:
    return {
        'length': float(box.get('length', 0) or 0),
        'width': float(box.get('width', 0) or 0),
        'height': float(box.get('height', 0) or 0),
    }


def _raw_area(box: Dict) -> float:
    return (
        float(box.get('raw_length', box.get('length', 0)) or 0)
        * float(box.get('raw_width', box.get('width', 0)) or 0)
    )


def scan_pallet(items: List[Dict]) -> List[Tuple]:
    """返回违例三元组列表 [(上方箱 id, 上方面积, 下方箱 id, 下方面积)]。"""
    hits: List[Tuple] = []
    for i, box in enumerate(items):
        pos = box.get('position')
        if not pos:
            continue
        others = items[:i] + items[i + 1:]
        if passes_footprint_area_below_constraint(box, pos, _dims(box), others):
            continue
        # 复算一次拿到具体的违例对，便于定位箱型组合。判定条件必须与谓词逐项
        # 一致（含 XY 投影重叠），否则会把"同高度但错开摆放"的更大箱也算进来，
        # 明细数远大于真实违例数。
        box_dims = _dims(box)
        for other in others:
            other_pos = other.get('position')
            if not other_pos:
                continue
            top = float(other_pos['z']) + float(other.get('height', 0) or 0)
            if abs(top - float(pos['z'])) > 1e-5:
                continue
            if _raw_area(other) <= _raw_area(box) + 1e-6:
                continue
            if not _has_positive_xy_overlap(pos, box_dims, other):
                continue
            hits.append((box.get('id'), _raw_area(box),
                         other.get('id'), _raw_area(other)))
    return hits


def scan_file(path: str) -> Dict:
    with open(path, encoding='utf-8') as handle:
        plan = json.load(handle)
    pallets = [p for p in plan.get('pallets', []) if p.get('packed_items')]
    stats = Counter()
    pair_shapes = Counter()
    bad_ids: List[str] = []
    for pallet in pallets:
        stats['pallets'] += 1
        status = pallet.get('mpm_status')
        if status == 'SUCCESS':
            stats['success'] += 1
        hits = scan_pallet(pallet['packed_items'])
        if not hits:
            continue
        stats['bad_pallets'] += 1
        stats['bad_pairs'] += len(hits)
        if status == 'SUCCESS':
            stats['bad_success_pallets'] += 1
        bad_ids.append(str(pallet.get('pallet_id')))
        by_id = {str(b.get('id')): b for b in pallet['packed_items']}
        for upper_id, upper_area, lower_id, lower_area in hits:
            up = by_id.get(str(upper_id), {})
            low = by_id.get(str(lower_id), {})
            pair_shapes[(
                '%gx%g' % (float(up.get('raw_length', 0) or 0),
                           float(up.get('raw_width', 0) or 0)),
                '%gx%g' % (float(low.get('raw_length', 0) or 0),
                           float(low.get('raw_width', 0) or 0)),
            )] += 1
    return {'stats': stats, 'pair_shapes': pair_shapes, 'bad_ids': bad_ids}


def main(patterns: List[str]) -> int:
    paths: List[str] = []
    for pattern in patterns:
        matched = sorted(glob.glob(pattern))
        paths.extend(matched if matched else [pattern])
    if not paths:
        print('没有匹配到方案文件')
        return 2

    total = Counter()
    shapes = Counter()
    for path in paths:
        try:
            result = scan_file(path)
        except (OSError, ValueError, KeyError) as exc:
            print('  跳过 %s（%s）' % (path, exc))
            continue
        stats = result['stats']
        total.update(stats)
        shapes.update(result['pair_shapes'])
        flag = 'OK ' if not stats['bad_pallets'] else '违例'
        print('[%s] %s  盘=%d 达标=%d 违例盘=%d(其中达标 %d) 违例对=%d'
              % (flag, Path(path).name, stats['pallets'], stats['success'],
                 stats['bad_pallets'], stats['bad_success_pallets'],
                 stats['bad_pairs']))
        if result['bad_ids']:
            print('       违例盘: %s%s'
                  % (', '.join(result['bad_ids'][:5]),
                     ' ...' if len(result['bad_ids']) > 5 else ''))

    print('-' * 72)
    print('合计: 文件=%d 盘=%d 达标=%d 违例盘=%d(其中达标 %d) 违例对=%d'
          % (len(paths), total['pallets'], total['success'],
             total['bad_pallets'], total['bad_success_pallets'],
             total['bad_pairs']))
    if shapes:
        print('高频违例箱型组合（上方底面 <- 下方底面）:')
        for (upper, lower), count in shapes.most_common(8):
            print('  %-12s <- %-12s  %d 例' % (upper, lower, count))
    return 1 if total['bad_pallets'] else 0


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print(__doc__)
        raise SystemExit(2)
    raise SystemExit(main(sys.argv[1:]))
