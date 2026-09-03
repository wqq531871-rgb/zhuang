"""装箱约束统一配置（单一事实来源）。

把原先散落在各处的硬编码约束参数（间隙、支撑率、重心偏差、吸盘尺寸）
和约束开关（吸盘可达、小面积在下、同尺寸重箱在下、按倍数凑层）集中到
一个不可变配置对象。入口加载后全局注入主装箱、救援、门禁三条链路，
保证「放置时拦截」与「最终门禁」同源，杜绝两层不一致。

约束分两类：
- **必须约束（不可关，仅值可配）**：不超界、不重叠、箱间间隙、支撑率、
  重心稳定。这些没有开关字段，永远生效；只有数值（间隙/支撑率/重心偏差）
  可通过本配置调整。
- **可关约束（默认开启，可配置关闭）**：吸盘可达、小面积在下、
  同尺寸重箱在下、按倍数凑层。每个有一个 ``*_enabled`` 开关。

设计上 frozen，确保配置在运行期不被意外修改（符合 immutability-first）。
"""

from dataclasses import dataclass
from typing import Dict, Optional, Tuple


@dataclass(frozen=True)
class ConstraintConfig:
    """装箱约束的统一配置。

    Attributes:
        # —— 必须约束的可配数值（约束本身不可关闭）——
        max_box_gap_mm: 箱间"贴紧"判定阈值（毫米，默认 6.0）。锚定语义：
            X、Y 每个轴上箱子须贴紧一侧邻箱或托盘边（正向间隙 < 阈值）；
            贴紧后对面残余的不可避免间隙不违规；两侧均不贴紧的浮空摆放拒绝。
        support_ratio_threshold: 非底层箱子的最小直接支撑率（默认 0.8）。
        xy_tolerance: 放置尺寸容差，长/宽各 +本值（毫米，默认 2.0）。占位尺寸
            用于重叠、贴紧、越界判定；投影面积口径始终用原始尺寸，不含容差。
        z_tolerance: 放置尺寸容差，高 +本值（毫米，默认 0.0）。
        center_of_mass_tolerance: 整体重心相对托盘中心的最大允许偏移比例
            （默认 1/3，即偏移不得超过托盘对应边长的 1/3）。
        max_pallet_weight_kg: 整盘（整垛箱子）重量上限，千克，默认 1000.0。
            甲方 2026-09 需求：现场部分托盘整垛超过 1000kg。≤ 0 视为关闭约束，
            完全恢复历史行为。约束是可加、与几何无关的容量约束，故在 GCP 的
            ILP / CP-SAT 里精确入模，不是事后拦截，详见 geometry/weight_limit.py。
            单箱本身超限时该盘豁免（数据异常，重排无解，拦下会破坏守恒）。

        # —— 可关约束的开关（默认 True）——
        suction_reachability_enabled: 是否启用机器人吸盘可达性检查。
        footprint_area_below_enabled: 是否启用「小面积在下」（任一箱子的正下方
            不得有投影面积更大的箱子）。对全部箱子生效。旧配置键
            ``small_box_below_enabled`` 由 ConfigLoader 映射到本键。
        same_size_heavier_below_enabled: 是否启用「同尺寸重箱在下」。
        height_multiple_layering_enabled: 是否启用「按倍数凑层」打分偏好
            （同底面不同高度按整数倍优先同层堆叠；这是软偏好，不是硬拦截）。
        flat_top_full_perimeter_enabled: 是否启用「平顶不缺角」（甲方 2026-07
            需求）：正常订单（全规则箱，见 utils/normal_order.py）的达标盘
            必须顶面平（零容差）且整圈周边无缺口；尾盘（未达标盘）与守恒
            兜底盘豁免。校验实现见 geometry/flat_top.py。
        flat_top_pallet_types: 「平顶不缺角」适用的托盘类型（甲方口径：仅
            MH423C；MH110 不做要求）。
        flat_top_seam_tolerance_mm: 周边铺满判定允许的箱间缝隙（毫米，默认
            6.0，对齐 max_box_gap_mm 的"贴紧"语义；顶面等高判定始终零容差）。

        # —— 吸盘几何（供可达性检查用，仅在 suction_reachability_enabled 时生效）——
        suction_cup_length: 吸盘长度（毫米，默认 600.0）。
        suction_cup_width: 吸盘宽度（毫米，默认 800.0）。
        suction_xy_clearance: 吸盘 XY 方向安全间隙（毫米，默认 0.0）。
        suction_z_clearance: 吸盘 Z 方向安全间隙（毫米，默认 0.0）。
        suction_allow_rotation_90: 是否允许吸盘旋转 90 度（默认 True）。

        # —— 主装箱算法选择 ——
        main_packer: 主装箱算法。'gcp'（默认）= 全局列式装箱 + 柱级组合
            优化（Set-Partitioning ILP，达标率优先）；'beam' = 旧 beam search
            逐盘贪心 + 配方优先 + 救援链（回退/审计用，保证零回归）。
        dual_path_enabled: GCP 未捕获业务组指数上限时，是否限时运行完整
            替代路径并经过守恒、最终门禁后择优。
        dual_path_time_limit_seconds: 单业务组替代完整路径的硬超时秒数。
        directed_exchange_enabled: 是否在整盘重排前尝试同 case_group 定向换箱。
        directed_exchange_max_items: 单次允许从 donor 取出的最大箱数。
        directed_exchange_max_attempts: 单业务组的最大候选尝试次数。
        cpsat_target_subset_enabled: 未捕获指数上限时是否启用 CP-SAT 目标子集。
        cpsat_target_subset_time_limit_seconds: 单次子集选择的求解时限秒数。
        cpsat_target_subset_max_attempts: 几何失败后最多重选子集的次数。
    """

    # —— 必须约束的可配数值 ——
    max_box_gap_mm: float = 6.0
    support_ratio_threshold: float = 0.8
    center_of_mass_tolerance: float = 1.0 / 3.0
    xy_tolerance: float = 2.0
    z_tolerance: float = 0.0
    # 整盘限重（kg）。≤ 0 = 关闭。见 geometry/weight_limit.py。
    max_pallet_weight_kg: float = 1000.0

    # —— 可关约束开关 ——
    suction_reachability_enabled: bool = True
    footprint_area_below_enabled: bool = True
    same_size_heavier_below_enabled: bool = True
    height_multiple_layering_enabled: bool = True

    # —— 平顶不缺角（正常订单达标盘；尾盘豁免）——
    flat_top_full_perimeter_enabled: bool = True
    flat_top_pallet_types: Tuple[str, ...] = ('MH423C',)
    flat_top_seam_tolerance_mm: float = 6.0

    # —— 吸盘几何 ——
    suction_cup_length: float = 600.0
    suction_cup_width: float = 800.0
    suction_xy_clearance: float = 0.0
    suction_z_clearance: float = 0.0
    suction_allow_rotation_90: bool = True

    # —— 主装箱算法选择 ——
    # 'gcp' = 全局列式装箱 + 柱级组合优化（默认，达标率优先）；
    # 'beam' = 旧 beam search 逐盘贪心 + 配方优先 + 救援链（回退/审计用）。
    main_packer: str = 'gcp'

    # —— 未捕获机会组双路径棘轮 ——
    dual_path_enabled: bool = True
    dual_path_time_limit_seconds: float = 30.0

    # —— 保留 receiver 布局的定向换箱 ——
    directed_exchange_enabled: bool = True
    directed_exchange_max_items: int = 4
    directed_exchange_max_attempts: int = 40

    # —— CP-SAT 目标子集 + 精确柱式三维落地 ——
    cpsat_target_subset_enabled: bool = True
    cpsat_target_subset_time_limit_seconds: float = 3.0
    cpsat_target_subset_max_attempts: int = 6

    # —— baseline 朝向规整（允许箱子 90° 旋转）——
    # baseline(beam+配方) 入口为每个箱子选「托盘上每层格数更大」的朝向，
    # 修复固定朝向对旋转敏感箱型（如 530×350、740×330）系统性装不满的缺陷。
    # 仅作用于 baseline 路径；GCP 有独立朝向处理(_fp_orient/CP-SAT)，不受影响。
    allow_box_rotation_90: bool = True

    @classmethod
    def from_dict(cls, data: Optional[Dict]) -> 'ConstraintConfig':
        """从字典创建配置；未提供的键回退默认值，未知键忽略。

        容错设计：甲方在 YAML 里漏写或拼错某个键时，不抛异常，而是用安全
        默认值兜底。这样误配置只会退回标准行为，不会让整个流程崩溃。
        """
        if not data:
            return cls()
        known = {k: v for k, v in data.items() if k in cls.__annotations__}
        # YAML 列表 → 元组（frozen dataclass 保持不可变语义）
        if 'flat_top_pallet_types' in known:
            value = known['flat_top_pallet_types']
            if isinstance(value, str):
                value = (value,)
            known['flat_top_pallet_types'] = tuple(
                str(item) for item in (value or ())
            )
        return cls(**known)

    def to_dict(self) -> Dict:
        """导出为普通字典（便于落盘 / 日志记录 / 复现实验配置）。"""
        return {field: getattr(self, field) for field in self.__annotations__}
