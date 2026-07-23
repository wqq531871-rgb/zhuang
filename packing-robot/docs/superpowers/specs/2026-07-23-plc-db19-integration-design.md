# PLC DB19 通讯集成设计

## 目标

把 `D:\research_code\tongxun` 中已经通过离线测试的 Siemens S7-1214C
通讯能力集成进当前机器人装箱三维仿真系统。操作员在同一个 PySide6
界面中加载装箱计划和相机数据、连接 PLC、按 `seq` 顺序发送整盘箱子并查看
逐箱握手结果。

## 最终业务契约

- 装箱顺序只使用当前计划中已经排序后的 `PackedItem.sequence`。
- PLC 仍使用 DB19，字段和握手偏移保持不变。
- `DBW12 state` 是旋转和吸取角点的唯一通讯字段：
  - `state=1`：不旋转，吸取 A 点，A 固定表示 `x_min_y_min`。
  - `state=2`：旋转 90°，吸取 B 点，B 固定表示 `x_max_y_min`。
- 不增加 DBW22，不向 PLC 发送独立 A/B 字段。
- UI 可以显示 A/B 和角点名称，但这些只是 `state` 的语义解释。
- PLC 命令发送前要求当前托盘每个箱子都已有相机数据，避免执行到中途才发现
  缺少姿态。

## 方案选择

采用“复用协议核心、重建当前系统适配层”的方案：

1. 将旧项目的 DB19 命令校验、INT 编码、连接、握手和异常类型移入当前项目。
2. 新增适配函数，将 `RobotAction` 转为 DB19 命令。
3. 新增后台 `QThread` 工作对象，串行发送当前托盘的全部命令。
4. 在现有左侧面板加入 PLC 参数、连接、开始、停止、状态和日志。

不直接嵌入旧 `plc_gui.py`，因为它包含本系统不需要的 MySQL 查询、
`box_unique_id` FIFO 队列和独立主窗口；也不从外部目录动态导入，避免部署时
依赖两个项目目录同时存在。

## 模块边界

### `packing_ui/plc_protocol.py`

负责纯协议逻辑：

- `PlcCommand`：DBW0..12 和 DBW16 所需字段。
- `S7Config`：IP、端口、rack、slot、DB 编号、超时和轮询参数。
- `build_plc_command(action)`：从 `RobotAction` 生成并完整验证命令。
- `pack_payload()` / `pack_int()`：Siemens 大端有符号 INT 编码。
- `S7Client`：连接、状态读取和单箱握手。
- `create_snap7_client()`：延迟导入 `python-snap7`，缺少依赖时给出中文错误。

业务适配映射如下：

| PLC 地址 | 数据来源 |
|---|---|
| DBW0 | `action.box_size[0]` |
| DBW2 | `action.box_size[1]` |
| DBW4 | `action.box_size[2]` |
| DBW6 | `action.box_place[0]` |
| DBW8 | `action.box_place[1]` |
| DBW10 | `action.box_place[2] + action.box_size[2]` |
| DBW12 | `action.rotation_state`，只能为 1 或 2 |
| DBW16 | `action.sequence` |

### `packing_ui/plc_worker.py`

负责 Qt 后台执行：

- `PlcConnectionWorker`：后台连接测试，避免阻塞 UI。
- `PlcSendWorker`：逐箱发送已预验证命令。
- 工作线程通过信号上报连接状态、等待 FP、发送中、单箱完成、整盘完成、
  安全停止和错误。
- “停止”只设置停止请求。若当前箱尚未写入 PLC，则停止；若已开始
  `send_command`，必须等待本箱握手明确完成后再停止，不自动重发状态不明的箱子。

### `packing_ui/main_window.py`

负责用户操作和显示：

- PLC 参数：IP、端口、rack、slot、DB 编号。
- 按钮：连接 PLC、开始发送、停止。
- 状态：未连接、连接中、已连接、等待 PLC、发送中、已停止、失败、完成。
- 日志显示每箱 `seq`、箱号、DBW12 数值及其 A/B 解释和 DBW16 返回值。
- 开始前检查当前托盘存在、动作非空、所有动作 `plc_ready=True`、命令全部可转换。
- 发送期间锁定计划、相机和姿态相关控件，避免已校验命令与画面数据发生变化。
- 单箱完成时，将播放位置更新到该箱的 RELEASE 完成帧；下一箱等待期间保持刚放下
  的箱子为橙色，直到下一箱真正完成放置。
- 窗口关闭时请求安全停止，并等待后台线程退出后再释放资源。

## 数据流

1. 装箱 JSON 按 `seq` 生成当前托盘动作。
2. 相机 JSON 按箱号绑定姿态，计算 `rotation_state`：
   同姿态为 1/A，不同姿态为 2/B。
3. 点击“开始发送”时一次性把所有动作转换成不可变 `PlcCommand` 列表。
4. 工作线程依次等待 PLC `FP=1`，写入 DBW0..12、DBW16，最后写
   `SEND_OK=1`。
5. PLC 设置 `FP_OVER=1` 并覆盖 DBW16 返回结果。
6. 客户端保存结果，清 FP 和 SEND_OK，并等待 PLC 清 FP_OVER。
7. UI 记录结果并进入下一箱。

## 错误和安全策略

- 无相机数据、重复/非法 `seq`、非 1/2 的 state、非有限数值或超出 INT16：
  在第一箱写入前阻止整盘发送。
- 连接失败：有限次重试后报告错误，UI 恢复可编辑状态。
- 写入后通讯错误或超时：明确提示“本箱不会自动重发”，停止整盘。
- UI 不执行自动重连后的重发，防止机械臂重复动作。
- 仅允许一个 PLC 任务运行；运行中禁止二次开始。

## 测试

- 协议单元测试覆盖动作映射、DBW12 1/A 与 2/B、四舍五入、INT16 边界、
  大端编码和完整握手。
- Worker 测试使用假客户端覆盖顺序发送、逐箱结果、停止和错误信号。
- UI 冒烟测试覆盖控件、开始前校验、线程状态更新和完成后的控件恢复。
- 全量 pytest 不访问真实 PLC；现场连接只由操作员明确点击触发。

