# WCS carton layer_id 固定为 1：设计说明

## 目标

所有发送、导出或从数据库重建的 WCS case 中，`layers[].cartons[].layer_id`
固定输出整数 `1`，不再根据箱子的 Z 坐标编号。

## 不变项

- `layers` 数组仍按箱子的 Z 起点分组并按 Z 升序排列。
- 每个箱子的 `seq`、尺寸、`product_code` 和 case 的 `total_height` 保持原逻辑。
- 算法内部的几何层、界面显示和装箱计算不改变。

## 实现

在四条实际输出链路各声明语义明确的常量 `WCS_OUTPUT_LAYER_ID = 1`：

1. 主源码 WCS 适配器 `packing-system/src/adapter/wcs_adapter.py`。
2. 运行时副本 WCS 适配器 `packing-system/packing/src/adapter/wcs_adapter.py`。
3. 执行顺序 WCS 导出 `packing-system/src/execution/wcs_export.py`。
4. 数据库历史箱数据重建 `packing-system/src/service/success_box_db.py`。

各构建器继续用 `geometric_layer_id` 对 `layers` 分组，只把 carton 字段写成
`WCS_OUTPUT_LAYER_ID`。这样未来恢复按 Z 输出时，只需将该字段改回
`geometric_layer_id`，不会影响分组结构。

## 验证

用至少两个不同 Z 层的输入覆盖四条链路，确认：

- 输出仍有两个 `layers` 分组；
- 所有 carton 的 `layer_id` 都为 `1`；
- `seq` 和 `total_height` 未改变。

