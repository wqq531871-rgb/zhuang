# 机器人装箱可视化系统

基于 PySide6、PyVista 和 OpenGL 的装箱结果解析与交互式三维仿真工具。

本目录位于 monorepo `final/zhuang/packing-robot`（由原 `zhuang-robot` 迁入）。
装箱规划仪表盘可通过「打开机器人仿真」按钮以独立进程启动本程序。

## 启动

Windows 可以双击 `启动程序.bat`，也可以在本目录执行：

```powershell
python -m pip install -r requirements.txt
$env:ZHUANGDB_PASSWORD = "数据库密码"
python main.py
```

也可从同级 `packing-system` 的 V3 仪表盘点击「打开机器人仿真」打开（默认路径为本目录；可用环境变量 `PACKING_ROBOT_DIR` 覆盖）。

MySQL 主机、端口、用户名和数据库名与旧 PLC 通讯界面共用
`OpenAI/PLCPalletSender` 的 QSettings 配置；密码只从环境变量
`ZHUANGDB_PASSWORD` 读取，不写入代码或配置文件。

## 使用方法

1. 点击“导入装箱 JSON”。程序启动时也会自动载入当前目录下第一个 `wcs_plan_map_*.json`。
2. 在“指标状态”中选择 `SUCCESS`、`ALL`、`FAILED` 或 `UNKNOWN`。默认是 `SUCCESS`。
3. 选择托盘方案。
4. 点击“导入相机 JSON”，把相机识别的箱子 ID、坐标和 `0°/90°` 姿态绑定到当前托盘箱子；判断完成后，系统以箱子 ID 作为 `product_code` 查询数据库并更新 `state`。没有相机数据时可使用手动姿态进行离线预览，但 PLC 指令保持不可执行。
5. 在箱子顺序中选择一个箱子，查看相机姿态、托盘目标姿态、PLC 旋转状态以及 A/B 吸附点。
6. 使用底部的首箱、上一箱、播放、下一箱、末箱、进度条和倍速控件检查动作。
7. 点击动作表中的任意一行可跳转到对应箱子。
8. 点击“导出动作”保存动作 JSON 和按 `seq` 排列的 `plc_commands`。
9. 点击右侧“打开 PLC 通讯界面”，启动原来的
   `D:\research_code\tongxun\plc_gui.py`。
10. 在旧 PLC 界面中手动输入 32 位 `box_unique_id`。旧界面从 MySQL
    `zhuangdb.wcs_success_box` 查询整盘数据和每箱 `state`，再按 `seq` 发送 PLC。

## PLC 与数据库交接

当前三维仿真系统不直接连接 PLC，也不写 DB19。它负责根据相机姿态和托盘目标姿态
计算并展示：

- `state=1`：A / `x_min_y_min` / 不旋转；
- `state=2`：B / `x_max_y_min` / 旋转 90°。

相机判断完成后，本系统执行如下数据库映射：

- `RobotAction.item_id` → `wcs_success_box.product_code`；
- `RobotAction.rotation_state` → `wcs_success_box.state`。

系统对一次相机导入使用一个事务。每个 `product_code` 先以参数化 SQL
`SELECT ... FOR UPDATE` 锁定；只有查询结果恰好一条时才按主键更新 `state`。
任一编号缺失、重复或数据库执行失败，整批回滚，并在右侧显示“同步失败”。该校验是
必要的，因为当前表结构虽然将 `product_code` 描述为箱子唯一编号，但没有为它声明
唯一索引。

旧 PLC 通讯界面根据操作员输入的 `box_unique_id` 查询整盘数据，并负责 DB19
握手、按 `seq` 逐箱发送、安全停止和通讯日志。本系统不直接写 PLC DBW12/DB19。

“打开 PLC 通讯界面”会以独立进程启动旧程序；旧程序仍在运行时重复点击不会启动
第二个实例。

首次使用旧通讯程序时安装它自己的依赖：

```powershell
cd D:\research_code\tongxun
python -m pip install -r .\requirements.txt
```

## 三维场景与动画

- 托盘最终堆叠以低透明度显示，已放置箱子逐步变成实体。
- 托盘原点固定为 `(0, 0, 0)`，托盘区域沿 `+X / +Y` 展开。
- 传送带关于 X 轴布置在托盘另一侧，即位于 `-Y` 区域，并在托盘 X 方向居中；每一步都会在传送带上生成当前待抓箱子。
- 600×800 mm 吸盘以半透明青色显示，不绘制机械臂。
- 鼠标左键旋转视角，滚轮缩放，中键平移。

每个箱子的动画阶段依次为：

```text
READY
PICK_DESCEND
PICK_ATTACH
LIFT
TRANSFER
PLACE_DESCEND
RELEASE
RETRACT
```

其中 `TRANSFER` 阶段同时完成水平搬运和所需的 0°/90° 旋转，`PLACE_DESCEND` 阶段从目标位置上方下降至 JSON 指定坐标。

## 输出字段

每个箱子的导出数据包含：

- `pickup.z`：传送带平面 Z 加箱子原始高度。
- `pickup.box_corner` / `pickup.cup_corner`：抓取时的箱子与吸盘对齐角点；需要旋转 90° 时会随旋转方向切换。
- `plc.rotation_state`：`1` 表示不旋转，`2` 表示旋转 90°。
- `plc.pickup_point`：无论箱子姿态如何，`A` 固定对应箱子自身的 `x_min_y_min`，`B` 固定对应 `x_max_y_min`。
- `plc.pickup_point_code`：A 为 `1`，B 为 `2`。
- 当前三维系统不直接发送 PLC；`pickup_point` 和 `pickup_point_code` 用于展示与
  数据追溯，旧 PLC UI 从数据库读取与它们绑定的 `state`。
- `placement.box_origin.x/y/z`：算法给出的箱子放置基准坐标。
- `placement.suction_tcp_contact.x/y/z`：由箱子与吸盘的 `x_min_y_min` 对齐关系及箱子顶面计算的吸盘接触目标。
- `placement.target_orientation_deg`：装箱目标吸盘姿态。
- `placement.rotation_deg`：目标姿态与手动设置的传送带姿态之差，当前为 0° 或 90°。
- `placement.box_corner` / `placement.cup_corner`：放置时固定为绿色标记位置对应的 `x_min_y_min`。

目标吸盘姿态的约定：

- `cup_600x_800y` → 0°
- `cup_800x_600y` → 90°

## 坐标说明

界面使用托盘局部坐标进行算法展示：托盘原点为 `(0, 0, 0)`，X、Y 沿托盘平面正方向展开，Z 向上；传送带位于负 Y 一侧。箱子放置坐标来自 `position`；吸盘接触 Z 为 `position.z + raw_height`。

这些数据不是已经完成标定的机械臂世界坐标。生产下发前仍需叠加：

- 传送带坐标系到机器人基坐标系的标定变换；
- 托盘坐标系到机器人基坐标系的标定变换；
- 法兰到吸盘接触面的 TCP 工具偏移；
- 抓取和放置安全高度。

## 支持的 JSON 结构

程序同时支持：

- 当前样例的根对象映射结构：`{ "随机键": { "pallet_id": ..., "packed_items": [...] } }`；
- 字段文档中的标准结构：`{ "pallets": [...] }`。

装箱顺序只读取每个箱子的 `seq` 字段并按数值升序排列。旧字段 `robot_packing_sequence` 和 `original_packing_sequence` 不再参与排序；为兼容没有 `seq` 的旧样例，缺失时仅保持输入数组原顺序。

## 相机输入

```json
{
  "box_id": "WCS-0004-ZX222-0007",
  "x": 420.0,
  "y": -1100.0,
  "z": 0.0,
  "orientation_deg": 0,
  "timestamp": "2026-07-23T10:30:00+08:00",
  "confidence": 0.98
}
```

也可以使用 `{ "boxes": [...] }` 一次导入多箱。`box_id` 必须属于当前托盘，`orientation_deg` 只能为 `0` 或 `90`。X/Y/Z 缺失时仅回退到传送带默认位置进行预览。

## 测试

```powershell
$env:QT_QPA_PLATFORM='offscreen'
$env:QT_API='pyside6'
python -m pytest -q
```
