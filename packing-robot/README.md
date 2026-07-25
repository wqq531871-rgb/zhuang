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

MySQL 参数读取同级 `packing-system/config/packing_config.yaml`；密码不应提交
到代码仓库。PLC 通讯使用本程序内置的 `python-snap7` 模块，不依赖
`D:\research_code\tongxun`。

## 使用方法

1. 启动 `local_wcs_receiver` 和本程序，等待 WCS 调用
   `/adaptor/api/wcs/sendcasetask` 选定托盘；也可在调试时直接加载当前托盘。
2. 在右侧 PLC 区域确认 IP（默认 `10.19.40.70`）、端口（内部固定 `102`）、
   Rack、Slot 和 DB（默认 DB19），点击“连接 PLC”。
3. “自动下发”每次启动均默认关闭。主动打开后，新的 WCS 托盘指令会自动启动
   下发；关闭时 WCS 只加载和显示托盘。
4. 需要人工联调时，点击“手动发送当前托盘”，它与自动模式使用完全相同的
   数据库监听、序号校验和 PLC 握手。
5. 当前箱 `state` 为空时持续等待；`state=0` 只发送报警；
   `state=1/2` 才发送完整箱体数据。

## PLC 与数据库交接

本系统直接连接 Siemens PLC 的 DB19，并根据数据库最新状态逐箱下发：

- `state=1`：A / `x_min_y_min` / 不旋转；
- `state=2`：B / `x_max_y_min` / 旋转 90°。

- PLC 写 `DBW2` 请求当前箱；Python 将它与数据库 `seq` 校验，不一致时零数据
  写入并停止整盘。
- PLC 的 SEND 区 `DBW6/8/10` 提供相机测得长宽高；Python 读取后按
  `box_unique_id + seq` 写入数据库
  `camera_length/camera_width/camera_height`，不向这三个偏移写数据。
- 常驻判态监听发现相机尺寸齐全且 `state` 为空后生成 `state=0/1/2`；
  当前箱的 PLC 下传线程从相机尺寸写库成功后才开始等待该 `state`。
- REV 区小写尺寸 `DBW14/16/18` 来自 `raw_length/width/height`。
- PLC 坐标约定与数据库 XY 对调：`DBW20=pos_y`、`DBW22=pos_x`；
  `DBW24=pos_z`。
- `DBW26=state`、`DBW28=box_num`、`DBW34=stack_height_before`。
- 正常数据全部写完后最后置 `DBW30 DH_OVER=1`；观察到
  `DBW4 FP_OVER=1` 后才清 `DBW0 FP` 和 `DBW30 DH_OVER`。
- `state=0` 时只写 `DBW32 baojing=1`，不写尺寸、坐标或完成信号。
- `DBW12 KONGXIAN` 当前只读取和显示，不参与控制。

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
- `pickup_point` 和 `pickup_point_code` 用于展示与追溯；实际 PLC 旋转字段
  `DBW26 FXBC` 使用数据库最新 `state`。
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
