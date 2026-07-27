"""
配置管理模块

提供装箱系统的所有可配置参数，支持从YAML文件加载或通过API传入。
"""

from .constants import *
from .pallet_config import PalletConfig
from .constraint_config import ConstraintConfig
from .execution_sequence_config import ExecutionSequenceSettings
from .algorithm_config import (
    PackingAlgorithmConfig,
    RobotSuctionConfig,
    RescueConfig,
    SmallBoxDetectionConfig,
    ExcelDataConfig,
)
from .loader import ConfigLoader, create_default_config_yaml

__all__ = [
    # 常量
    "PALLET_INDEX_TARGETS",
    "MAX_BOX_GAP_MM",
    "ENABLE_EXPENSIVE_FAILED_REPACK",
    "REPO_ROOT",
    "CODE_ROOT",
    "PROJECT_ROOT",
    "WORKSPACE_ROOT",
    "DATA_DIR",
    "OUTPUT_DIR",
    "INPUT_DIR",
    "DEFAULT_PACKING_CONFIG",
    # 配置类
    "PalletConfig",
    "ConstraintConfig",
    "PackingAlgorithmConfig",
    "RobotSuctionConfig",
    "RescueConfig",
    "SmallBoxDetectionConfig",
    "ExcelDataConfig",
    "ExecutionSequenceSettings",
    # 加载器
    "ConfigLoader",
    "create_default_config_yaml",
]
