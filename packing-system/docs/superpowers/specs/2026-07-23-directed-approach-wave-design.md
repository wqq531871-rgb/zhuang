# 斜向推进有向空间阶梯波设计

## 目标

机械臂位于托盘 `x_max_y_max` 一侧。每次携箱先在目标位置的 `+X/+Y` 方向下降，
再沿 `-X/-Y` 方向斜向推进几十毫米到目标位置，放箱后垂直抬升。执行规划必须在
不改变最终箱子集合、相对布局、尺寸和朝向的前提下，为所有托盘生成同一套可重复、
可回放验证的有向空间阶梯波顺序。

`x_min_y_min` 是远端波源。第一物理层必须从该角点向外形成无可避免倒置的确定性
波前；上层箱按同一水平波前和支撑层级逐步抬高。旧的“按同层高差判断逐层/阶梯波”
分类不再适用，所有托盘统一使用新规划器。

## 运动模型

对目标箱 `T` 定义最终位置 `P=(x,y,z)` 和预放位置：

```text
P_pre = (x + approach_offset_x_mm,
         y + approach_offset_y_mm,
         z + approach_z_clearance_mm)
```

现场初始配置使用 `approach_offset_x_mm=35`、`approach_offset_y_mm=35`，对应约
49.5 mm 的 `-X/-Y` 斜向推进。两个分量必须为有限且非负的数；实际值由现场标定后
直接调整配置，不写死在算法中。

规划器检查四段名义扫掠：

1. 箱体和吸盘在 `P_pre` 上方的垂直下降。
2. 箱体和吸盘从 `P_pre` 到 `P` 的斜向平移。
3. 箱体在目标位置的最终下降和支撑。
4. 放箱后吸盘在目标位置的垂直抬升。

本功能验证箱体和末端吸盘的轴对齐包络，不声称完成机器人 IK、关节限位或全连杆
碰撞验证。机器人控制器仍负责这些运动学检查。

## 斜向扫掠约束

箱体和吸盘的平移扫掠使用“移动矩形与静态矩形”的线段-Minkowski 相交测试，避免
用起终点外接矩形把斜线两侧本来不会经过的区域误判为阻挡。Z 方向使用真实箱体
高度与 `approach_z_clearance_mm` 判断区间重合。

若最终箱 `B` 在已经放置时会阻挡 `T` 的预放下降或斜向推进，则增加有向边
`T -> B`。现有直接支撑边仍为 `B -> T`。吸盘和最终位置的垂直下降/抬升边继续作为
硬依赖。合并后出现环，表示当前布局无法仅靠换序完成；不得回退到旧逐层顺序。

## 有向空间阶梯波

按配置原点计算每个箱子相对 `x_min_y_min` 的 X/Y 进度。分别用
`scan_column_tolerance_mm` 对 X 和 Y 坐标做锚点聚类，得到 `x_rank`、`y_rank`：

```text
spatial_ring = max(x_rank, y_rank)
wave = spatial_ring + support_tier
```

最终软排序键：

```text
(wave, spatial_ring, x_rank, y_rank, support_tier, stable_index)
```

> 本节记录 2026-07-23 的初始设计。2026-07-25 已改为
> `wave = spatial_ring + 2 * support_tier`、排序键
> `(wave, support_tier, spatial_ring, x_rank, y_rank, stable_index)`，让地面层先铺开
> 再升高。当前公式与理由见 `docs/独立执行顺序规划说明.md` 的“有向空间阶梯波”段落
> 和变更记录，本文不再同步。

支撑、垂直扫掠和斜向扫掠依赖始终优先。相同 `wave` 时先完成更靠近远端的空间环，
因此先抬高远端，再向 `x_max_y_max` 方向铺设较低外圈。第一层的 `support_tier=0`，
自然按二维空间环严格向外扩散，不再使用足迹邻接图 BFS。

“严格向外”定义为：在所有硬依赖已经满足的候选中选择排序键最小者，不允许无原因
跳过；只有明确的硬依赖、当前扫掠碰撞或剩余可完成性要求才能偏离，并记录箱号与
原因。

## 配置变更

保留：`enabled`、`origin`、现有垂直扫掠余量、防包围参数、时间预算和
`scan_column_tolerance_mm`。

新增：

```yaml
approach_offset_x_mm: 35.0
approach_offset_y_mm: 35.0
approach_z_clearance_mm: 0.0
approach_box_xy_clearance_mm: 0.0
approach_suction_xy_clearance_mm: 2.0
```

删除：`adaptive_staircase_enabled`、`staircase_height_difference_threshold_mm`、
`staircase_transition_ratio_threshold`、`staircase_min_transition_edges` 和无实际作用的
`prefer_adjacent_occupied_sides`。配置加载器、CLI、README、独立说明和测试必须同步
删除，不保留静默兼容分支，避免现场误以为还能切换逐层模式。

## 输出与失败策略

输出格式不新增 WCS 字段。`_execution.json` 继续保存最终 `seq`、居中坐标和
`stack_height_before`；WCS cases 和 WCS map 继续使用已经还原的接口字段。

斜向依赖成环、规划超时或最终四段回放失败时，不生成 execution 三件套。原始方案
可以保留供可视化和人工分析，但不得作为已验证的机器人执行顺序自动下发。

## 验收标准

- 所有托盘无条件进入有向空间阶梯波，不再输出 layerwise/staircase 分类。
- 合成相邻箱中，远端箱必须先于会阻挡其 `+X/+Y` 预放位的近端箱。
- 第一层按 `x_min_y_min` 空间环无可避免倒置地向外扩散。
- 每个执行前缀通过支撑、预放下降、斜向推进、最终下降、垂直抬升和防包围回放。
- 配置中不存在已删除的 adaptive 参数，传入这些未知键时配置对象不会使用它们。
- 668 箱数据保持箱子守恒、连续唯一 `seq`，所有成功发布托盘通过最终门禁。
- 现有 WCS cases 和 map 不重新引入 `stack_height_before`。
