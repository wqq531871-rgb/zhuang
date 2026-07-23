# 导出动作 JSON 字段说明

本文说明“机器人装箱三维仿真系统”通过“导出动作”按钮生成的 JSON 文件。

## 1. 坐标与单位约定

- 距离单位：毫米（mm）。
- 角度单位：度（°）。
- 托盘坐标原点：固定为 `(0, 0, 0)`，托盘沿 `+X / +Y` 展开，传送带位于 `-Y` 一侧。
- X、Y：托盘平面方向。
- Z：竖直向上方向。
- 吸盘名义尺寸：600 × 800 mm。
- `0°` 时吸盘在 X、Y 方向的尺寸分别为 600、800 mm。
- `90°` 时吸盘在 X、Y 方向的尺寸分别为 800、600 mm。

角点名称：

| 角点值 | 含义 |
| --- | --- |
| `x_min_y_min` | X 最小、Y 最小角点，即当前界面绿色标记采用的放置对齐点 |
| `x_min_y_max` | X 最小、Y 最大角点 |
| `x_max_y_min` | X 最大、Y 最小角点 |
| `x_max_y_max` | X 最大、Y 最大角点 |

## 2. JSON 总体结构

```json
{
  "pallet_id": "MH423C-PAIN25450MN01S-2",
  "mpm_status": "SUCCESS",
  "suction_cup_mm": [600, 800],
  "conveyor_orientation_mode": "per_item",
  "conveyor_orientation_by_item": {
    "WCS-0004-ZX222-0015": 90
  },
  "actions": []
}
```

## 3. 顶层字段

| 字段 | 类型 | 单位 | 说明 |
| --- | --- | --- | --- |
| `pallet_id` | string | — | 当前导出动作所属的托盘方案编号。 |
| `mpm_status` | string | — | 装箱方案状态，例如 `SUCCESS`、`FAILED` 或 `UNKNOWN`。 |
| `suction_cup_mm` | number[2] | mm | 吸盘名义尺寸 `[X尺寸, Y尺寸]`，当前固定为 `[600, 800]`。 |
| `conveyor_orientation_mode` | string | — | 传送带箱姿态编辑模式。当前固定为 `per_item`，表示每个箱子独立设置。 |
| `conveyor_orientation_by_item` | object | ° | 箱子 ID 到传送带箱姿态的映射；每个值为 `0` 或 `90`。它是每条动作中 `pickup.conveyor_orientation_deg` 的汇总。 |
| `actions` | array | — | 按机器人装箱顺序排列的动作数组，一项对应一个箱子。 |
| `plc_commands` | array | — | 按 `seq` 顺序排列、可直接供 PLC 适配层读取的精简指令。 |

## 4. `actions[]` 动作字段

| 字段 | 类型 | 单位 | 说明 |
| --- | --- | --- | --- |
| `item_id` | string | — | 箱子的唯一编号。 |
| `box_type` | string | — | 箱子类型或包装规格代码，例如 `ZX222`。 |
| `sequence` | integer | — | 当前动作的装箱顺序值。动作数组已经按该顺序排列。 |
| `sequence_source` | string | — | `sequence` 的来源：正常输入为 `seq`；兼容缺少 `seq` 的旧文件时为 `array`。 |
| `pickup` | object | — | 传送带抓取阶段的数据。 |
| `placement` | object | — | 托盘放置阶段的数据。 |
| `camera` | object | — | 当前动作绑定的相机视觉数据及接收状态。 |
| `plc` | object | — | 当前动作的 PLC 旋转状态、A/B 点及可执行状态。 |

装箱时唯一使用的顺序字段是 `seq`，程序按 `packed_items[].seq` 数值升序执行，并导出为 `sequence_source: "seq"`。旧字段 `robot_packing_sequence` 和 `original_packing_sequence` 会被忽略。仅为兼容不含 `seq` 的旧样例，程序才保持输入数组原顺序，并导出为 `sequence_source: "array"`。

## 5. `pickup` 抓取字段

```json
"pickup": {
  "z": 480.0,
  "conveyor_orientation_deg": 90,
  "box_corner": "x_max_y_min",
  "cup_corner": "x_max_y_min"
}
```

| 字段 | 类型 | 单位 | 说明 |
| --- | --- | --- | --- |
| `z` | number | mm | 吸盘抓取接触高度，计算方式为“传送带平面 Z + 箱子原始高度”。 |
| `conveyor_orientation_deg` | integer | ° | 当前箱子在传送带上的人工设定姿态，只能为 `0` 或 `90`。每个箱子可独立编辑。 |
| `box_corner` | string | — | 抓取时用于对齐的箱子顶面角点。 |
| `cup_corner` | string | — | 抓取时用于对齐的吸盘角点。当前与 `box_corner` 使用相同名称。 |

抓取角点会根据传送带姿态和目标姿态自动切换，使旋转后能够落到放置阶段的 `x_min_y_min` 对齐点：

| 传送带姿态 | 目标姿态 | 抓取箱子角点 | 抓取吸盘角点 | 旋转 |
| ---: | ---: | --- | --- | ---: |
| 0° | 0° | `x_min_y_min` | `x_min_y_min` | 0° |
| 90° | 90° | `x_min_y_min` | `x_min_y_min` | 0° |
| 0° | 90° | `x_max_y_min` | `x_max_y_min` | 90° |
| 90° | 0° | `x_max_y_min` | `x_max_y_min` | 90° |

## 6. `placement` 放置字段

```json
"placement": {
  "box_origin": {
    "x": 702.0,
    "y": 1596.0,
    "z": 0.0
  },
  "suction_tcp_contact": {
    "x": 1002.0,
    "y": 1996.0,
    "z": 480.0
  },
  "box_corner": "x_min_y_min",
  "cup_corner": "x_min_y_min",
  "target_orientation_deg": 0,
  "rotation_deg": 90
}
```

| 字段 | 类型 | 单位 | 说明 |
| --- | --- | --- | --- |
| `box_origin` | object | mm | 箱子在托盘上的最终放置基准坐标。 |
| `box_origin.x` | number | mm | 箱子放置基准 X 坐标。 |
| `box_origin.y` | number | mm | 箱子放置基准 Y 坐标。 |
| `box_origin.z` | number | mm | 箱子底面放置 Z 坐标。 |
| `suction_tcp_contact` | object | mm | 吸盘在箱子顶面完成放置时的中心接触位置。 |
| `suction_tcp_contact.x` | number | mm | 放置吸盘中心 X 坐标。 |
| `suction_tcp_contact.y` | number | mm | 放置吸盘中心 Y 坐标。 |
| `suction_tcp_contact.z` | number | mm | 箱子顶面 Z，计算方式为 `box_origin.z + 箱子原始高度`。 |
| `box_corner` | string | — | 放置时箱子的对齐角点，当前固定为 `x_min_y_min`。 |
| `cup_corner` | string | — | 放置时吸盘的对齐角点，当前固定为 `x_min_y_min`。 |
| `target_orientation_deg` | integer | ° | 吸盘在托盘放置位置的目标姿态，只能为 `0` 或 `90`。 |
| `rotation_deg` | integer | ° | 从传送带箱姿态到目标姿态所需的旋转角度，当前为 `0` 或 `90`。 |

目标姿态由输入装箱结果中的吸盘方向字段确定：

| 输入方向 | `target_orientation_deg` |
| --- | ---: |
| `cup_600x_800y` | 0° |
| `cup_800x_600y` | 90° |

## 7. 放置吸盘中心计算

箱子与吸盘在放置阶段使用 `x_min_y_min` 角点对齐。设：

- 箱子放置基准为 `(box_x, box_y, box_z)`；
- 箱子原始尺寸为 `(box_length, box_width, box_height)`。

目标姿态为 0° 时：

```text
suction_x = box_x + 300
suction_y = box_y + 400
suction_z = box_z + box_height
```

目标姿态为 90° 时：

```text
suction_x = box_x + 400
suction_y = box_y + 300
suction_z = box_z + box_height
```

## 8. 执行端建议

- 机器人应按 `actions` 数组顺序逐项执行。
- 抓取阶段使用 `pickup.z`、`pickup.box_corner`、`pickup.cup_corner` 和 `pickup.conveyor_orientation_deg`。
- 放置阶段使用 `placement.box_origin`、`placement.suction_tcp_contact`、`placement.target_orientation_deg` 和 `placement.rotation_deg`。
- `rotation_deg` 是当前系统输出的旋转量；如果机器人控制器需要区分顺时针和逆时针，还需要在控制端约定旋转方向。

## 9. 相机与 PLC 字段

吸附点固定定义：

| 吸附点 | 几何角点 | PLC 数值 |
| --- | --- | ---: |
| A | `x_min_y_min` | 1 |
| B | `x_max_y_min` | 2 |

A/B 是箱子自身坐标中的固定角点，不会随着箱子在传送带上的 0°/90° 姿态改变名称。
三维仿真在当前姿态的 XY 包络上显示这两个点：A 为 `(x_min, y_min)`，B 为 `(x_max, y_min)`。需要换向时仿真采用负向 90°，保证抓取阶段的 B 点在放置阶段转化为 A 点；PLC 仍使用 `rotation_state = 2` 表示该动作。

数据库交接时，A/B 与旋转状态合并为同一个 `state` 字段：

| 数据库 `state` | 绑定吸附点 | 动作 |
| ---: | --- | --- |
| 1 | A / `x_min_y_min` | 不旋转 |
| 2 | B / `x_max_y_min` | 旋转 90° |

当前三维系统不直接写 DBW12。相机判断完成后，系统把动作中的 `item_id` 作为
`zhuangdb.wcs_success_box.product_code`，查询到唯一记录后把
`rotation_state` 更新到该记录的 `state`。一次相机导入中的多箱更新属于同一个
事务；任一 `product_code` 未找到、查到多条或更新失败时整批回滚。

操作员在旧 PLC 通讯 UI 中输入 `box_unique_id`，由旧 UI 查询整盘 `state` 后完成
PLC 通讯。
`pickup_point` 和 `pickup_point_code` 只保留在导出 JSON 与 UI 中，方便人员观察和追溯。

旋转状态：

| `rotation_state` | 含义 |
| ---: | --- |
| 1 | 相机姿态与托盘目标姿态一致，不旋转 |
| 2 | 两个姿态相差 90°，吸取后旋转 90° |

每条 `actions[]` 包含：

```json
{
  "camera": {
    "received": true,
    "box_id": "WCS-0004-ZX222-0007",
    "x": 420.0,
    "y": -1100.0,
    "z": 0.0,
    "orientation_deg": 0,
    "timestamp": "2026-07-23T10:30:00+08:00",
    "confidence": 0.98
  },
  "plc": {
    "ready": true,
    "rotation_state": 2,
    "pickup_point": "B",
    "pickup_point_code": 2
  }
}
```

未收到当前箱子的相机数据时，`ready` 为 `false`，软件仍允许离线三维预览，但 PLC 不应执行该条指令。

顶层 `plc_commands[]` 包含：

- `box_id`、`seq`；
- `ready`；
- `rotation_state`；
- `pickup_point`、`pickup_point_code`；
- `pickup_z`；
- `placement_x`、`placement_y`、`placement_z`；
- `target_orientation_deg`。
