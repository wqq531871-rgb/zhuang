"""
WCS 接口模式常驻入口（与 Excel 单次装箱 run_packing.py 分离）。

用法:
    python run_wcs_service.py --config path/to/ui_config_api_xxx.yaml

流程：每 N 秒拉接口 1 → 本地存 input/ → 装箱 → 本地存 output/ → 推接口 2。
"""

import sys
from pathlib import Path

project_root = Path(__file__).resolve().parent
sys.path.insert(0, str(project_root))

from src.service import WcsPackingService


def _parse_cli(argv):
    config_path = None
    safe_compare = False
    run_mode = "continuous"
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--config":
            if i + 1 >= len(argv):
                raise SystemExit("错误：--config 缺少路径取值")
            config_path = argv[i + 1]
            i += 2
        elif a == "--safe":
            safe_compare = True
            i += 1
        elif a == "--run-mode":
            if i + 1 >= len(argv):
                raise SystemExit("错误：--run-mode 缺少运行方式")
            run_mode = argv[i + 1]
            i += 2
        else:
            i += 1
    valid_modes = {"continuous", "once", "until-success"}
    if run_mode not in valid_modes:
        raise SystemExit(f"错误：不支持的运行方式 {run_mode}")
    return config_path, safe_compare, run_mode


def main(argv=None):
    config_path, safe_compare, run_mode = _parse_cli(
        sys.argv[1:] if argv is None else argv
    )
    service = WcsPackingService(
        config_path=Path(config_path) if config_path else None,
        safe_compare=safe_compare,
    )
    if run_mode == "once":
        return 0 if service.run_once() else 1
    if run_mode == "until-success":
        return 0 if service.run_until_success() else 1
    service.run_loop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
