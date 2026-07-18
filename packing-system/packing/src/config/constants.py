"""
全局常量定义

路径约定：
- 本仓库（packing-system）只放源码
- 输入 / 输出 / 运行时数据在同级 packing-workspace（或环境变量 PACKING_WORKSPACE）
"""

from __future__ import annotations

import os
from pathlib import Path

# packing/src/config/constants.py → 上 4 级 = 仓库根 packing-system/
REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
CODE_ROOT = Path(__file__).resolve().parent.parent.parent  # packing/
# 兼容旧名：以前 PROJECT_ROOT 指向含 data/output 的目录；现改指仓库根
PROJECT_ROOT = REPO_ROOT

# 唯一默认配置：packing-system/config/packing_config.yaml（算法/UI/部署共用）
DEFAULT_PACKING_CONFIG = REPO_ROOT / "config" / "packing_config.yaml"


def _resolve_workspace() -> Path:
    env = os.environ.get("PACKING_WORKSPACE", "").strip()
    if env:
        return Path(env).expanduser().resolve()
    return (REPO_ROOT.parent / "packing-workspace").resolve()


WORKSPACE_ROOT = _resolve_workspace()
DATA_DIR = WORKSPACE_ROOT / "data"
OUTPUT_DIR = WORKSPACE_ROOT / "output"
INPUT_DIR = WORKSPACE_ROOT / "input"

# ============================================================================
# 托盘类型和要求的指数
# ============================================================================
PALLET_INDEX_TARGETS = {
    "MH423C": 192,
    "MH110": 32,
}

# ============================================================================
# 装箱约束常量
# ============================================================================
MAX_BOX_GAP_MM = 6.0

# 全局保守开关：保留为 False，但在"近/中等缺口"明显时可选择性放行
ENABLE_EXPENSIVE_FAILED_REPACK = False

# ============================================================================
# Excel 数据源（preprocess 用）
# ============================================================================
SMALL_BOX_SOURCE_FILE = DATA_DIR / "668箱子数据集.xlsx"
SMALL_BOX_SOURCE_SHEET = "最终挑选结果"
SMALL_BOX_BMS_SHEET = "包装物料主数据(BMS)"

# 小箱子体积阈值检测参数（基于密度/体积指数曲线）
SMALL_BOX_INDEX_SMOOTH_WINDOW = 5
SMALL_BOX_INDEX_PLATEAU_WINDOW = 6
SMALL_BOX_INDEX_PLATEAU_REL_TOL = 0.02
SMALL_BOX_INDEX_PLATEAU_ABS_TOL = 0.8
SMALL_BOX_INDEX_MIN_SLOPE_WINDOW = 3
SMALL_BOX_INDEX_NEAR_PEAK_GAP = 0.15
