# -*- coding: utf-8 -*-
"""临时脚本：按垛型直判回填某托盘 wcs_success_box.state。

用法（在 packing-system 目录下）::

    python tools/tmp_backfill_layout_state.py
    python tools/tmp_backfill_layout_state.py --uid 068e80576d66478b8ff72b419bc14026
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.service.success_box_db import (
    layout_state_from_raw_dims,
    load_database_config_from_yaml,
    WcsSuccessBoxRepository,
)


DEFAULT_UID = "068e80576d66478b8ff72b419bc14026"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="回填托盘 layout state")
    parser.add_argument("--uid", default=DEFAULT_UID, help="box_unique_id")
    parser.add_argument(
        "--config",
        default=str(ROOT / "config" / "packing_config.yaml"),
        help="packing_config.yaml",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只打印不写库",
    )
    args = parser.parse_args(argv)

    uid = str(args.uid).strip()
    cfg = load_database_config_from_yaml(Path(args.config))
    repo = WcsSuccessBoxRepository(cfg)

    with repo._cursor() as (_conn, cur):
        cur.execute(
            """
            SELECT id, seq, raw_length, raw_width, state
            FROM wcs_success_box
            WHERE box_unique_id = %s
            ORDER BY seq ASC
            """,
            (uid,),
        )
        rows = list(cur.fetchall() or [])

    if not rows:
        print(f"未找到托盘 box_unique_id={uid}")
        return 1

    print(f"托盘 {uid}：共 {len(rows)} 箱  dry_run={args.dry_run}")
    updates: list[tuple[int, int, int | None]] = []
    for row in rows:
        new_state = layout_state_from_raw_dims(
            row["raw_length"], row["raw_width"]
        )
        old = row.get("state")
        print(
            f"  seq={row['seq']:>3}  "
            f"raw={float(row['raw_length']):g}x{float(row['raw_width']):g}  "
            f"state {old!r} -> {new_state}"
        )
        updates.append((new_state, int(row["id"]), old))

    if args.dry_run:
        print("dry-run：未写库")
        return 0

    with repo._cursor() as (_conn, cur):
        for new_state, row_id, _old in updates:
            cur.execute(
                "UPDATE wcs_success_box SET state = %s WHERE id = %s",
                (new_state, row_id),
            )
        changed = sum(
            1
            for new_state, _id, old in updates
            if old is None or int(old) != int(new_state)
        )

    print(f"已更新 {len(updates)} 行（其中 state 变化 {changed} 行）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
