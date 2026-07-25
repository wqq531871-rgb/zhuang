# -*- coding: utf-8 -*-
"""临时脚本：把 wcs_success_box.box_num 全部写成指定值（默认 82）。

用法（在 packing-system 目录）::

    python tools/tmp_fill_box_num.py
    python tools/tmp_fill_box_num.py --value 82 --dry-run
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.service.success_box_db import (
    WcsSuccessBoxRepository,
    load_database_config_from_yaml,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="回填 wcs_success_box.box_num")
    parser.add_argument("--value", type=int, default=82, help="写入的 box_num")
    parser.add_argument(
        "--config",
        default=str(ROOT / "config" / "packing_config.yaml"),
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    cfg = load_database_config_from_yaml(Path(args.config))
    repo = WcsSuccessBoxRepository(cfg)

    with repo._cursor() as (_conn, cur):
        cur.execute("SELECT COUNT(*) AS n FROM wcs_success_box")
        total = int((cur.fetchone() or {}).get("n") or 0)
        cur.execute(
            "SELECT COUNT(*) AS n FROM wcs_success_box WHERE box_num IS NULL OR box_num <> %s",
            (args.value,),
        )
        need = int((cur.fetchone() or {}).get("n") or 0)

    print(f"总行数={total}，需更新={need}，目标 box_num={args.value}")
    if args.dry_run:
        print("dry-run：未写库")
        return 0

    with repo._cursor() as (_conn, cur):
        cur.execute("UPDATE wcs_success_box SET box_num = %s", (args.value,))
        affected = cur.rowcount

    print(f"已更新 rowcount={affected}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
