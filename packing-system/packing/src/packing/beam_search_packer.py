"""
Beam Search装箱器

使用束搜索算法进行装箱的核心实现。
"""

from typing import Dict, List, Optional, Tuple
import random
from copy import deepcopy

from .candidate_generator import CandidatePointGenerator
from .placement_validator import PlacementValidator
from .stacking_policy import (
    build_height_multiple_bonus_by_size,
    stacking_tiebreak_key,
)
from .suction_planner import SuctionPlanner
from ..geometry.gap_checker import side_gap_flags
from ..geometry.weight_limit import box_weight, fits_weight, pallet_weight_cap
from ..utils.dimensions import raw_dims


class BeamSearchPacker:
    """
    Beam Search装箱器

    使用束搜索算法进行装箱，整合候选点生成、放置验证和吸盘规划。
    """

    def __init__(
        self,
        pallet_dims: Dict[str, float],
        support_ratio_threshold: float = 0.8,
        size_tolerance: Optional[float] = None,
        z_tolerance: Optional[float] = None,
        max_candidate_points: int = 200,
        max_points_per_layer: int = 40,
        robot_reachability_enabled: bool = True,
        suction_cup_length: float = 600.0,
        suction_cup_width: float = 800.0,
        suction_xy_clearance: float = 0.0,
        suction_z_clearance: float = 0.0,
        allow_suction_rotation_90: bool = True,
        constraint_config=None,
    ):
        """
        初始化Beam Search装箱器

        Args:
            pallet_dims: 托盘尺寸 {'length': float, 'width': float, 'height': float}
            support_ratio_threshold: 支撑比例阈值
            size_tolerance: XY方向尺寸容差（毫米）。None = 从 constraint_config
                读 xy_tolerance（配置未给则 2.0）。救援链的「紧贴塞洞」路径显式
                传 0.0 覆盖，不受配置影响。
            z_tolerance: Z方向尺寸容差（毫米）。None 同上，读 z_tolerance。
            max_candidate_points: 最大候选点数量
            max_points_per_layer: 每层最大候选点数量
            robot_reachability_enabled: 是否启用机器人可达性检查
            suction_cup_length: 吸盘长度（毫米）
            suction_cup_width: 吸盘宽度（毫米）
            suction_xy_clearance: XY方向间隙（毫米）
            suction_z_clearance: Z方向间隙（毫米）
            allow_suction_rotation_90: 是否允许吸盘旋转90度
            constraint_config: 可选的 ConstraintConfig。提供时统一覆盖支撑率、
                间隙、吸盘几何与各可关约束开关；不提供时沿用上面的逐参默认值
                （保持向后兼容，行为不变）。
        """
        # 约束统一配置：提供则覆盖对应的逐参默认值，单一事实来源。
        if constraint_config is not None:
            support_ratio_threshold = constraint_config.support_ratio_threshold
            robot_reachability_enabled = (
                constraint_config.suction_reachability_enabled
            )
            suction_cup_length = constraint_config.suction_cup_length
            suction_cup_width = constraint_config.suction_cup_width
            suction_xy_clearance = constraint_config.suction_xy_clearance
            suction_z_clearance = constraint_config.suction_z_clearance
            allow_suction_rotation_90 = (
                constraint_config.suction_allow_rotation_90
            )
            self.max_gap = constraint_config.max_box_gap_mm
            self.center_of_mass_tolerance = (
                constraint_config.center_of_mass_tolerance
            )
            self.footprint_area_below_enabled = (
                constraint_config.footprint_area_below_enabled
            )
            self.same_size_heavier_below_enabled = (
                constraint_config.same_size_heavier_below_enabled
            )
            self.height_multiple_layering_enabled = (
                constraint_config.height_multiple_layering_enabled
            )
            # 放置容差：仅在调用方未显式指定时才从配置取。救援链的紧贴塞洞
            # 路径显式传 0.0，必须保留其覆盖能力。
            if size_tolerance is None:
                size_tolerance = getattr(constraint_config, 'xy_tolerance', 2.0)
            if z_tolerance is None:
                z_tolerance = getattr(constraint_config, 'z_tolerance', 0.0)
        else:
            from ..config.constants import MAX_BOX_GAP_MM
            self.max_gap = MAX_BOX_GAP_MM
            self.center_of_mass_tolerance = 1.0 / 3.0
            self.footprint_area_below_enabled = True
            self.same_size_heavier_below_enabled = True
            self.height_multiple_layering_enabled = True

        if size_tolerance is None:
            size_tolerance = 2.0
        if z_tolerance is None:
            z_tolerance = 0.0

        self.pallet_dims = pallet_dims
        self.support_ratio_threshold = support_ratio_threshold
        self.size_tolerance = size_tolerance
        self.z_tolerance = z_tolerance
        self.robot_reachability_enabled = robot_reachability_enabled
        # 整盘限重（kg）；None = 不限重。约束与几何无关，故不进
        # PlacementValidator，而在束搜索按状态逐箱累加判定。
        self.max_pallet_weight = pallet_weight_cap(constraint_config)
        self.placed_boxes = []

        # 初始化组件
        self.candidate_generator = CandidatePointGenerator(
            max_candidate_points=max_candidate_points,
            max_points_per_layer=max_points_per_layer
        )

        self.placement_validator = PlacementValidator(
            pallet_dims=pallet_dims,
            support_ratio_threshold=support_ratio_threshold,
            size_tolerance=size_tolerance,
            z_tolerance=z_tolerance
        )

        self.suction_planner = SuctionPlanner(
            pallet_dims=pallet_dims,
            suction_cup_length=suction_cup_length,
            suction_cup_width=suction_cup_width,
            suction_xy_clearance=suction_xy_clearance,
            suction_z_clearance=suction_z_clearance,
            allow_suction_rotation_90=allow_suction_rotation_90
        )

    def pack(
        self,
        items_to_pack: List[Dict],
        num_restarts: int = 30,
        beam_width: int = 6,
        candidate_limit: int = 30,
        random_seed: Optional[int] = None,
        target_mpm: Optional[float] = None,
        stop_when_target_met: bool = True,
        allow_skip_items: bool = True
    ) -> Tuple[List[Dict], List[Dict]]:
        """
        使用多起点 + Beam Search 进行装箱

        Args:
            items_to_pack: 待装箱的物品列表
            num_restarts: 多起点次数
            beam_width: Beam Search 宽度
            candidate_limit: 每个状态保留的候选放置数量上限
            random_seed: 随机种子
            target_mpm: 当前托盘类型目标最小包装量倍数和
            stop_when_target_met: 达标后是否停止继续装入箱子
            allow_skip_items: 是否允许跳过当前箱子并留给后续托盘

        Returns:
            (placed_boxes, unfitted_items) 元组
        """
        # 初始化随机数生成器
        rng = random.Random(random_seed)
        best_state = None

        # 预过滤：分离能装入托盘和不能装入托盘的物品
        prefiltered_items = []
        pre_unfitted = []
        for item in items_to_pack:
            if self.placement_validator.can_fit_in_pallet(item):
                prefiltered_items.append(item)
            else:
                pre_unfitted.append(item)

        # 如果没有可装入的物品，直接返回空结果
        if not prefiltered_items:
            self.placed_boxes = []
            return [], list(pre_unfitted)

        # 定义物品排序策略列表
        # 底面积策略随「小面积在下」开关换方向：开启时用升序——先喂大底面箱
        # 等于自断后路（大底面落地后上方只能再放同样大的箱），升序让小底面先
        # 铺地、大底面往上叠，才是该约束允许的堆法；关闭时沿用改造前的降序，
        # 保证开关是真开关。策略数恒为 5，restart_idx % len 映射不变，
        # 重启次数不变故不增耗时。
        order_strategies = [
            "volume_asc",
            "volume_desc",
            "weight_desc",
            (
                "base_area_asc" if self.footprint_area_below_enabled
                else "base_area_desc"
            ),
            "random"
        ]

        # 执行多次重启搜索，每次使用不同的排序策略
        for restart_idx in range(num_restarts):
            strategy = order_strategies[restart_idx % len(order_strategies)]
            ordered_items = self._order_items(prefiltered_items, strategy, rng)
            state = self._pack_with_beam_search(
                ordered_items,
                beam_width=beam_width,
                candidate_limit=candidate_limit,
                rng=rng,
                target_mpm=target_mpm,
                stop_when_target_met=stop_when_target_met,
                allow_skip_items=allow_skip_items
            )

            # 将预过滤中无法装入的物品合并到当前状态的未拟合列表中
            if pre_unfitted:
                state['unfitted_items'] = list(state['unfitted_items']) + list(pre_unfitted)

            # 更新最佳状态：如果当前状态评分更高，则替换最佳状态
            if best_state is None or self._state_score(state, target_mpm) > self._state_score(best_state, target_mpm):
                best_state = state

        # 保存最佳结果的已放置箱子，并返回最终结果
        from ..utils.helpers import refresh_support_metrics
        from ..geometry.gap_checker import passes_box_gap_constraint
        from ..geometry.center_of_mass import validate_center_of_mass
        from ..utils.helpers import has_box_above, repack_ready_item

        # 清理不合法的放置（间隙约束、支撑约束、重心约束）
        sanitized_packed, sanitized_removed = self._sanitize_packed_items(
            best_state['placed_boxes']
        )
        sanitized_unfitted = list(best_state['unfitted_items']) + sanitized_removed

        self.placed_boxes = sanitized_packed
        return sanitized_packed, sanitized_unfitted

    def _order_items(
        self,
        items: List[Dict],
        strategy: str,
        rng: random.Random
    ) -> List[Dict]:
        """
        根据指定策略对物品列表进行排序

        Args:
            items: 待排序的物品列表
            strategy: 排序策略，可选值：
                     - "volume_asc": 按体积升序排列
                     - "volume_desc": 按体积降序排列
                     - "weight_desc": 按重量降序排列
                     - "base_area_asc": 按底面积（长×宽）升序排列
                     - "base_area_desc": 按底面积（长×宽）降序排列
                     - "random": 随机打乱顺序
            rng: 随机数生成器对象

        Returns:
            排序后的物品列表副本
        """
        items_copy = list(items)
        # 按倍数凑层（可关的软偏好）：关闭时不计算高度倍数 bonus，回退为
        # 中性的同尺寸重箱优先排序（保持稳定性，不影响硬约束）。
        if self.height_multiple_layering_enabled:
            size_bonus = build_height_multiple_bonus_by_size(items_copy)
        else:
            size_bonus = {}
        items_copy.sort(key=lambda item: stacking_tiebreak_key(item, size_bonus))
        if strategy == "volume_asc":
            items_copy.sort(key=lambda x: x['length'] * x['width'] * x['height'])
        elif strategy == "volume_desc":
            items_copy.sort(key=lambda x: x['length'] * x['width'] * x['height'], reverse=True)
        elif strategy == "weight_desc":
            items_copy.sort(key=lambda x: x.get('weight', 0), reverse=True)
        elif strategy == "base_area_asc":
            items_copy.sort(key=lambda x: x['length'] * x['width'])
        elif strategy == "base_area_desc":
            items_copy.sort(key=lambda x: x['length'] * x['width'], reverse=True)
        elif strategy == "random":
            rng.shuffle(items_copy)
        return items_copy

    def pack_additions(
        self,
        existing_placements: List[Dict],
        items_to_add: List[Dict],
        num_restarts: int = 4,
        beam_width: int = 4,
        candidate_limit: int = 16,
        random_seed: Optional[int] = None,
        target_mpm: Optional[float] = None,
    ) -> Tuple[List[Dict], List[Dict]]:
        """Place additions without moving or rewriting existing placements."""

        fixed = [deepcopy(item) for item in existing_placements]
        fixed_by_id = {item.get("id"): item for item in fixed}
        rng = random.Random(random_seed)
        prefiltered = []
        pre_unfitted = []
        for item in items_to_add:
            if self.placement_validator.can_fit_in_pallet(item):
                prefiltered.append(item)
            else:
                pre_unfitted.append(item)
        if not prefiltered:
            return fixed, list(items_to_add)

        strategies = [
            "volume_asc",
            "volume_desc",
            "weight_desc",
            "base_area_desc",
        ]
        best_state = None
        for restart_idx in range(max(1, num_restarts)):
            strategy = strategies[restart_idx % len(strategies)]
            ordered = self._order_items(prefiltered, strategy, rng)
            state = self._pack_with_beam_search(
                ordered,
                beam_width=beam_width,
                candidate_limit=candidate_limit,
                rng=rng,
                target_mpm=target_mpm,
                stop_when_target_met=True,
                allow_skip_items=True,
                initial_placed_boxes=fixed,
            )
            if pre_unfitted:
                state["unfitted_items"] = (
                    list(state["unfitted_items"]) + list(pre_unfitted)
                )
            if best_state is None or self._state_score(
                state, target_mpm
            ) > self._state_score(best_state, target_mpm):
                best_state = state

        sanitized, removed = self._sanitize_packed_items(
            best_state["placed_boxes"]
        )
        sanitized_by_id = {item.get("id"): item for item in sanitized}
        if any(box_id not in sanitized_by_id for box_id in fixed_by_id):
            return fixed, list(items_to_add)

        combined = [
            deepcopy(fixed_by_id.get(item.get("id"), item))
            for item in sanitized
        ]
        unfitted = list(best_state["unfitted_items"]) + removed
        self.placed_boxes = combined
        return combined, unfitted

    def _pack_with_beam_search(
        self,
        ordered_items: List[Dict],
        beam_width: int,
        candidate_limit: int,
        rng: random.Random,
        target_mpm: Optional[float] = None,
        stop_when_target_met: bool = True,
        allow_skip_items: bool = True,
        initial_placed_boxes: Optional[List[Dict]] = None,
    ) -> Dict:
        """
        使用束搜索算法进行装箱

        通过维护多个候选状态并在每一步保留最优的beam_width个状态，
        在解空间中进行搜索以找到较优的装箱方案。

        Args:
            ordered_items: 已排序的待装箱物品列表
            beam_width: 束宽度，每步保留的最优状态数量
            candidate_limit: 每个状态下考虑的最大候选位置数量
            rng: 随机数生成器对象
            target_mpm: 目标MPM值，用于状态评分
            stop_when_target_met: 达标后是否停止当前托盘装箱
            allow_skip_items: 是否允许把当前箱子留给后续托盘

        Returns:
            最优装箱状态，包含以下字段：
                - placed_boxes (list): 已放置的箱子列表
                - unfitted_items (list): 无法放置的物品列表
        """
        initial_state = {
            "placed_boxes": [
                deepcopy(item) for item in (initial_placed_boxes or [])
            ],
            "unfitted_items": []
        }
        states = [initial_state]
        terminal_states = []

        for item_idx, item in enumerate(ordered_items):
            next_states = []
            for state in states:
                state_mpm = sum(b.get('min_pack_multiple', 0) for b in state['placed_boxes'])
                if target_mpm is not None and stop_when_target_met and state_mpm >= target_mpm:
                    terminal_states.append({
                        "placed_boxes": list(state['placed_boxes']),
                        "unfitted_items": list(state['unfitted_items']) + list(ordered_items[item_idx:])
                    })
                    continue

                # 整盘限重：可加约束，与位置无关，故在此按状态逐箱拦截，
                # 而不是进 PlacementValidator 逐候选点算。超限的箱留给下一盘
                # （与 unfitted 语义一致）。空盘放行——单箱本身超限时若也拦下，
                # 该箱将无处可去；与整盘门禁/增量门禁的单箱豁免保持一致。
                if state['placed_boxes'] and not fits_weight(
                    state['placed_boxes'], box_weight(item),
                    self.max_pallet_weight,
                ):
                    next_states.append({
                        "placed_boxes": list(state['placed_boxes']),
                        "unfitted_items": (
                            list(state['unfitted_items']) + [item]
                        ),
                    })
                    continue

                skip_added = False
                if target_mpm is not None and allow_skip_items:
                    next_states.append({
                        "placed_boxes": list(state['placed_boxes']),
                        "unfitted_items": list(state['unfitted_items']) + [item]
                    })
                    skip_added = True

                candidates = self._generate_feasible_candidates(item, state['placed_boxes'], rng)
                if not candidates:
                    if not skip_added:
                        new_state = {
                            "placed_boxes": list(state['placed_boxes']),
                            "unfitted_items": list(state['unfitted_items']) + [item]
                        }
                        next_states.append(new_state)
                    continue

                scored_candidates = sorted(candidates, key=lambda c: c['score'])
                for candidate in scored_candidates[:candidate_limit]:
                    new_state = {
                        "placed_boxes": list(state['placed_boxes']) + [candidate['box']],
                        "unfitted_items": list(state['unfitted_items'])
                    }
                    next_states.append(new_state)

            states = sorted(next_states, key=lambda s: self._state_score(s, target_mpm), reverse=True)[:beam_width]
            if not states:
                break

        all_final_states = terminal_states + states
        return max(all_final_states, key=lambda s: self._state_score(s, target_mpm)) if all_final_states else initial_state

    def _generate_feasible_candidates(
        self,
        item: Dict,
        placed_boxes: List[Dict],
        rng: random.Random
    ) -> List[Dict]:
        """
        为待放置物品生成所有可行的候选放置位置

        该函数通过以下步骤生成候选位置：
        1. 获取所有候选放置点并按Z轴分层，同层内随机打乱
        2. 对每个候选点进行边界检查、尺寸顺序检查、重叠检查、稳定性检查和机器人可达性检查
        3. 只保留最低可行Z层的候选位置（贪心策略：优先填充底层）
        4. 计算每个候选位置的放置得分和支持面积比例

        Args:
            item: 待放置的物品信息
            placed_boxes: 已放置物品的列表
            rng: 随机数生成器

        Returns:
            可行候选位置列表，每个元素包含：
                - 'box': 放置后的箱子对象（包含位置和吸盘信息）
                - 'score': 放置得分
        """
        raw_length = float(item.get('raw_length', item.get('length', 0)) or 0)
        raw_width = float(item.get('raw_width', item.get('width', 0)) or 0)
        raw_height = float(item.get('raw_height', item.get('height', 0)) or 0)
        dims = {
            'length': raw_length + self.size_tolerance,
            'width': raw_width + self.size_tolerance,
            'height': raw_height + self.z_tolerance
        }

        # 生成候选点
        candidate_points = self.candidate_generator.generate_candidate_points(placed_boxes)

        # 按Z轴分层并随机打乱同层点
        grouped_by_z = {}
        for point in candidate_points:
            z = point['z']
            if z not in grouped_by_z:
                grouped_by_z[z] = []
            grouped_by_z[z].append(point)

        for z in grouped_by_z:
            rng.shuffle(grouped_by_z[z])

        # 按Z轴排序
        sorted_z_levels = sorted(grouped_by_z.keys())

        # 寻找最低可行Z层
        feasible_candidates = []
        for z_level in sorted_z_levels:
            layer_candidates = []
            for point in grouped_by_z[z_level]:
                # 边界检查
                if not self.placement_validator.is_within_bounds(point, dims):
                    continue

                # 同尺寸重箱在下（可关约束）
                if self.same_size_heavier_below_enabled and not (
                    self.placement_validator.satisfies_stacking_order(
                        item, point, dims, placed_boxes
                    )
                ):
                    continue

                # 小面积在下：正下方不得有投影面积更大的箱子（可关约束）
                if self.footprint_area_below_enabled and not (
                    self.placement_validator.satisfies_footprint_area_order(
                        item, point, dims, placed_boxes
                    )
                ):
                    continue

                # 重叠检查
                if self.placement_validator.check_overlap(point, dims, placed_boxes):
                    continue

                # 稳定性检查
                if not self.placement_validator.is_stable(point, dims, placed_boxes):
                    continue

                # 机器人可达性检查
                if self.robot_reachability_enabled:
                    item_raw_dims = raw_dims(item)
                    suction_pose = self.suction_planner.find_reachable_suction_pose(
                        point, dims, placed_boxes, raw_dims=item_raw_dims
                    )
                    if suction_pose is None:
                        continue
                else:
                    suction_pose = None

                # 创建放置后的箱子对象
                placed_item = deepcopy(item)
                placed_item['position'] = dict(point)
                placed_item['raw_length'] = float(
                    item.get('raw_length', item.get('length', 0)) or 0
                )
                placed_item['raw_width'] = float(
                    item.get('raw_width', item.get('width', 0)) or 0
                )
                placed_item['raw_height'] = float(
                    item.get('raw_height', item.get('height', 0)) or 0
                )
                placed_item['length'] = dims['length']
                placed_item['width'] = dims['width']
                placed_item['height'] = dims['height']

                # 添加吸盘信息
                if suction_pose:
                    placed_item['suction_box_corner'] = suction_pose['box_corner']
                    placed_item['suction_cup_corner'] = suction_pose['cup_corner']
                    placed_item['suction_orientation'] = suction_pose['orientation']
                    placed_item['suction_cup_x_size'] = suction_pose['cup_x_size']
                    placed_item['suction_cup_y_size'] = suction_pose['cup_y_size']
                    placed_item['suction_rect_x_min'] = suction_pose['cup_rect']['x_min']
                    placed_item['suction_rect_x_max'] = suction_pose['cup_rect']['x_max']
                    placed_item['suction_rect_y_min'] = suction_pose['cup_rect']['y_min']
                    placed_item['suction_rect_y_max'] = suction_pose['cup_rect']['y_max']

                # 计算放置得分
                score = self._placement_score(point, dims, placed_boxes)

                layer_candidates.append({
                    'box': placed_item,
                    'score': score
                })

            # 如果找到可行候选，只使用最低层
            if layer_candidates:
                feasible_candidates = layer_candidates
                break

        return feasible_candidates

    def _placement_score(
        self,
        point: Dict[str, float],
        dims: Dict[str, float],
        placed_boxes: List[Dict]
    ) -> Tuple:
        """
        计算放置位置的得分

        优先级：Z坐标（越低越好）> Y坐标（越小越好）> X坐标（越小越好）> 支撑比例（越高越好）

        Args:
            point: 放置位置
            dims: 箱子尺寸
            placed_boxes: 已放置的箱子列表

        Returns:
            得分元组
        """
        from ..geometry.support import direct_support_ratio
        support_ratio = direct_support_ratio(point, dims, placed_boxes)
        return (
            point['z'],
            point['y'],
            point['x'],
            -support_ratio
        )

    def _state_score(
        self,
        state: Dict,
        target_mpm: Optional[float] = None
    ) -> Tuple:
        """
        计算装箱状态的得分

        Args:
            state: 装箱状态
            target_mpm: 目标MPM值

        Returns:
            得分元组
        """
        total_mpm = sum(b.get('min_pack_multiple', 0) for b in state['placed_boxes'])
        total_volume = sum(
            b['length'] * b['width'] * b['height']
            for b in state['placed_boxes']
        )

        if target_mpm is None:
            return (
                total_volume,
                len(state['placed_boxes']),
                total_mpm,
                -len(state['unfitted_items']),
            )

        mpm_gap = target_mpm - total_mpm
        is_target_met = 1 if mpm_gap <= 0 else 0
        remaining_mpm = sum(
            b.get('min_pack_multiple', 0) for b in state['unfitted_items']
        )
        future_success = int(remaining_mpm // target_mpm) if target_mpm > 0 else 0
        remaining_tail = (
            remaining_mpm - future_success * target_mpm
            if target_mpm > 0 else 0.0
        )
        tail_floor = target_mpm * 0.35
        if remaining_mpm <= 1e-9 or remaining_tail >= tail_floor:
            tail_penalty = 0.0
        else:
            tail_penalty = -(tail_floor - remaining_tail)
        if is_target_met:
            overflow = max(0.0, total_mpm - target_mpm)
            overflow_allowance = max(16.0, target_mpm * 0.15)
            excess_overflow = max(0.0, overflow - overflow_allowance)
            return (
                is_target_met,
                total_volume,
                len(state['placed_boxes']),
                future_success,
                tail_penalty,
                -excess_overflow,
                total_mpm,
                -abs(mpm_gap),
                -len(state['unfitted_items']),
            )
        # 指数优先：是否达标 > 与目标差距（越接近越好）> mpm总量 > 未装箱数量
        return (
            is_target_met,
            -abs(mpm_gap),
            total_mpm,
            total_volume,
            len(state['placed_boxes']),
            future_success,
            tail_penalty,
            -len(state['unfitted_items']),
        )

    def _sanitize_packed_items(
        self,
        items: List[Dict]
    ) -> Tuple[List[Dict], List[Dict]]:
        """委托给 src.packing.sanitizer.sanitize_packed_items。"""
        from .sanitizer import sanitize_packed_items

        return sanitize_packed_items(
            items,
            support_ratio_threshold=self.support_ratio_threshold,
            max_gap=self.max_gap,
            pallet_dims=self.pallet_dims,
            center_of_mass_tolerance=self.center_of_mass_tolerance,
        )
