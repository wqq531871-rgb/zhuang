# PLC DB19 偏移重映射与内置通讯设计

## 目标与范围

在 `D:\research_code\final\zhuang\packing-robot` 内实现独立的 Siemens S7
DB19 通讯，不再通过启动 `D:\research_code\tongxun\plc_gui.py` 完成 PLC
通讯。旧项目仅作为已验证握手逻辑的只读参考，本次不修改
`D:\research_code\tongxun`。

通讯模块从 `wcs_success_box` 读取当前托盘箱子的数据，按数据库 `seq`
顺序发送。所有 PLC 数值使用 Siemens 大端有符号 `INT16`，写入前执行有限值、
四舍五入和 `INT16` 范围校验。

程序由操作员手动启动并常驻运行。正常生产时，WCS 调用
`/adaptor/api/wcs/sendcasetask` 选定托盘；只有操作员已经打开“自动下发”时，
程序才自动启动该托盘的状态监听和 PLC 发送。界面同时保留“手动启动当前托盘”
按钮，供联调和 WCS 不可用时使用。

通讯能力随 `packing-robot` 主程序加载，但不得在程序启动时自动连接或写入
PLC。“自动下发”在每次程序启动时均默认为关闭，避免历史托盘或残留指令导致
意外发送。

## 方案选择

采用“迁移协议核心并重建当前系统适配层”的方案：

1. 在 `packing_ui` 内新增独立 PLC 协议模块，承载字段编码、偏移、握手和异常。
2. 复用当前项目已有的数据库读取和界面模型，不复制旧项目的整套独立窗口。
3. 当前界面直接连接 PLC、发送当前数据库托盘并显示状态和日志。
4. 删除运行时对 `D:\research_code\tongxun` 的依赖。

没有采用整套复制旧 PLC 界面的方案，因为它会保留重复数据库读取、重复窗口和
无关任务队列代码；没有把硬件通讯放进 `packing-system` 后端，因为本次操作入口
和展示状态都属于 `packing-robot`，扩大后端修改范围没有必要。

## DB19 字段映射

| 偏移 | 字段 | 方向 | 数据来源或行为 |
|---:|---|---|---|
| DBW0 | `FP` | PLC → Python；Python复位 | PLC 请求发送；收到完成回执后由 Python 清零 |
| DBW2 | `FP_ZYXH` | PLC → Python | PLC 请求的箱子 `seq`，与当前数据库记录校验 |
| DBW4 | `FP_OVER` | PLC → Python | PLC 接收完成回执 |
| DBW6 | `CHANG` | Python → PLC | `camera_length` |
| DBW8 | `KUAN` | Python → PLC | `camera_width` |
| DBW10 | `GAO` | Python → PLC | `camera_height` |
| DBW12 | `KONGXIAN` | PLC → Python | 读取并记录 `0/1`，本阶段不触发控制操作 |
| DBW14 | `chang` | Python → PLC | `raw_length` |
| DBW16 | `kuan` | Python → PLC | `raw_width` |
| DBW18 | `gao` | Python → PLC | `raw_height` |
| DBW20 | `x` | Python → PLC | `pos_y`（与数据库 XY 对调） |
| DBW22 | `y` | Python → PLC | `pos_x`（与数据库 XY 对调） |
| DBW24 | `z` | Python → PLC | `pos_z` |
| DBW26 | `FXBC` | Python → PLC | 数据库 `state`，正常箱只允许 `1` 或 `2` |
| DBW28 | `ZYXH` | Python → PLC | 数据库 `box_num`；不写入 DBW2 |
| DBW30 | `DH_OVER` | Python → PLC | 本箱正常数据全部写完后的完成信号 |
| DBW32 | `baojing` | Python → PLC | `state=0` 写 `1`；`state=1/2` 写 `0` |
| DBW34 | `gaodu` | Python → PLC | `stack_height_before`，替换原 `ceshi : Bool` |

数据库查询需要包含：

- `camera_length`、`camera_width`、`camera_height`
- `raw_length`、`raw_width`、`raw_height`
- `pos_x`、`pos_y`、`pos_z`
- `state`、`box_num`、`stack_height_before`、`seq`

## 正常箱握手

正常箱指数据库 `state` 为 `1` 或 `2`。

1. Python 按数据库 `seq` 选定当前待发送箱子。
2. 按 `box_unique_id + seq` 定时重新查询该箱最新 `state`，不依赖托盘首次
   加载时缓存的旧值。
3. `state IS NULL` 时保持等待，不向 PLC 写任何字段；得到 `0/1/2` 后才进入
   报警或正常发送分支。
4. 正常分支轮询 DBW0、DBW2、DBW4、DBW12 和 DBW30。
5. 仅当 `FP=1`、`FP_OVER=0`、`DH_OVER=0` 时进入本箱发送。
6. 比较 PLC 的 DBW2 与当前数据库箱子的 `seq`。
7. 若不一致，不写任何本箱字段，立即停止整盘发送，并在界面显示
   “PLC请求 seq=X，当前数据库箱子 seq=Y”。
8. 若一致，先写 DBW6..DBW28 和 DBW34，且写 `baojing=0`。
9. 所有本箱数据写完后，最后写 `DH_OVER=1`，防止 PLC 读取半包数据。
10. Python 等待 `FP_OVER=1`。
11. 收到回执后清 `FP=0` 和 `DH_OVER=0`。
12. 等待 PLC 将 `FP_OVER` 清零；确认 `FP=0`、`FP_OVER=0`、
    `DH_OVER=0` 后，本箱完成并进入下一箱。

偏移通过命名常量集中定义。读取、等待和清零必须引用同一组常量，避免出现已经
读取新地址、仍然清旧 DBW18/DBW20 的错误。

## WCS 自动触发与 state 监听

现有链路继续作为托盘选择入口：

1. WCS 调用 `/adaptor/api/wcs/sendcasetask`，传入 `box_unique_id`。
2. `local_wcs_receiver` 写当前现场会话和 `load_pallet` 指令。
3. `packing-robot` 现有 500 ms 指令轮询读取 `load_pallet`，按
   `box_unique_id` 从数据库加载托盘。
4. 若界面启用“自动下发”，加载成功且 PLC 已连接时启动当前托盘的后台任务。
   若尚未连接，只保留已加载托盘并明确显示“等待 PLC 连接”，不得静默丢弃任务。
5. 后台任务按 `seq` 处理箱子，并按 `box_unique_id + seq` 定时重新查询数据库
   最新 `state`，不得只使用首次加载时的缓存值。

每箱的 state 门禁为：

- `state IS NULL`：继续等待，不向 PLC 写任何字段；
- `state=0`：进入报警箱路径；
- `state=1` 或 `state=2`：进入正常箱握手；
- 其他值：停止整盘并报告非法 state。

数据库轮询需支持停止请求和超时配置。收到新的 `sendcasetask` 时，若上一托盘仍在
发送，不得静默切换或并行发送；界面报告“上一托盘仍在执行”，保持当前任务不变，
由操作员停止或完成后再处理新托盘。

手动模式使用界面当前选中的托盘，执行与自动模式完全相同的 state 监听、预检、
DBW2 校验和握手，不维护第二套发送逻辑。

## 报警箱行为

报警箱指数据库 `state=0`。

1. 仍按数据库顺序确定当前箱，并执行 DBW2 与数据库 `seq` 校验。
2. 校验一致后只写 `DBW32 baojing=1`。
3. 不写尺寸、坐标、`FXBC`、`ZYXH`、`gaodu` 或 `DH_OVER`。
4. 停止本箱的正常发送流程，在界面明确显示数据库 `state=0` 报警。

这样可保证报警箱不会向 PLC 下发可能被误执行的运动数据。

## 空闲字段

`DBW12 KONGXIAN` 由 PLC 写入。当前版本只读取其 `0/1` 值并显示在状态或
通讯日志中，不依据它开始、停止、跳过或重发箱子。后续现场确定空闲信号语义后，
再单独扩展控制行为。

## 通讯启动与停止

1. 操作员通过 `启动程序.bat` 或 `python main.py` 启动 `packing-robot`。
2. 主界面加载 PLC 通讯面板，但不自动连接 PLC。
3. 操作员通过现场指令或界面加载一个 `box_unique_id` 对应的托盘。
4. 操作员确认 PLC IP、端口、Rack、Slot 和 DB 编号后点击“连接 PLC”。
5. 连接成功后点击“开始发送”。程序先完成整盘静态字段预检，再从第一条数据库
   `seq` 开始执行 `state` 就绪监听和 PLC 握手。
6. 点击“停止”只请求安全停止：未开始写入的箱子立即停止；已开始握手的正常箱
   等待本箱状态明确后停止，避免留下无法判断是否执行的半箱状态。
7. 关闭主窗口时请求安全停止、断开 PLC，再退出程序。

程序启动、加载托盘或数据库 `state` 变为非空，都不会在“自动下发”关闭时触发
PLC 写入；只有操作员明确点击“手动发送当前托盘”，或已经主动打开“自动下发”
且随后收到新的 WCS 托盘指令时，后台发送线程才有写 PLC 的权限。

## 模块边界

### `packing_ui/plc_protocol.py`

- 定义 DB19 偏移常量、命令数据模型和配置。
- 从数据库箱子记录构造正常命令或报警动作。
- 编码大端 `INT16`，执行数值和字段校验。
- 实现连接、状态读取、`seq` 校验、正常握手、报警写入和安全复位。
- 延迟导入 `python-snap7`，缺少依赖时返回清晰错误。

### `packing_ui/plc_worker.py`

- 在 Qt 后台线程中连接和逐箱发送，避免阻塞界面。
- 向界面报告当前 DBW2、期望 `seq`、`KONGXIAN`、箱子完成、报警、停止和错误。
- 通讯错误、超时、错序或 `state=0` 后不自动重发，防止机械动作重复。

### 数据库与领域模型

- 扩展当前查询和箱子记录，保证字段包含 `box_num` 与
  `stack_height_before`。
- 提供按 `box_unique_id + seq` 查询最新 `state` 的轻量接口，供发送线程等待
  当前箱状态就绪。
- 在开始整盘发送前验证全部箱子的字段类型、连续唯一 `seq` 和数值范围。
- `state` 允许空值、`0`、`1`、`2`；空值继续等待，`0` 进入报警路径，
  `1/2` 进入正常路径。

### `packing_ui/main_window.py`

- 用内置 PLC 设置、连接、发送、停止、状态和日志取代外部程序启动按钮。
- 增加“自动下发”开关，每次程序启动时默认关闭，由操作员主动打开。
- 增加“手动启动当前托盘”按钮和“停止”按钮。
- 收到接口3产生的 `load_pallet` 指令并成功加载托盘后，仅在自动开关已打开且
  PLC 已连接时启动后台任务；否则只加载并显示托盘。
- 发送期间锁定会改变当前托盘或发送数据的控件。
- 错序时显示 PLC 请求值和数据库期望值。
- 显示当前 `box_unique_id`、等待的数据库 `seq/state`、PLC 请求 `seq`、
  `KONGXIAN` 和发送结果；`KONGXIAN` 不执行额外业务动作。

## 错误与安全

- DBW2 与当前 `seq` 不一致：零数据写入并停止整盘发送。
- 数据库 `state` 为空：保持等待且 PLC 零写入；查询失败则停止并报告错误。
- `state=0`：只写报警，不发送运动数据。
- 数值缺失、非有限、超出 `INT16` 或 `seq` 不连续：整盘预检失败，PLC 零写入。
- 写入数据后发生通讯错误或超时：停止整盘，不自动重发当前箱。
- 仅允许一个 PLC 发送任务运行。
- 正常数据最后才置 `DH_OVER=1`；只有观察到 `FP_OVER=1` 后才能清
  `FP` 和 `DH_OVER`。

## 测试策略

采用测试驱动实现，不连接真实 PLC 或现场 MySQL：

- 协议测试覆盖所有偏移、大小写尺寸来源、`box_num` 仅写 DBW28、
  `stack_height_before` 写 DBW34，以及大端 `INT16` 编码。
- 握手测试覆盖新 DBW0/2/4/30 地址、写入顺序、收到 `FP_OVER=1` 后才清
  DBW0/30，以及等待 PLC 清 DBW4。
- 错序测试断言不写任何箱体数据且报告两个 `seq`。
- state 监听测试覆盖空值持续等待、`0/1/2` 分流、停止请求和非法值。
- `state=0` 测试断言只写 DBW32=1。
- `state=1/2` 测试断言 DBW32=0 且发送完整正常数据。
- `KONGXIAN` 测试断言读取并报告值，但不改变发送控制流。
- WCS 自动触发测试断言 `load_pallet` 成功后启动对应托盘，已有任务运行时拒绝
  静默切换。
- UI 测试断言自动开关每次启动均默认关闭；关闭时 WCS 指令只加载托盘，不写
  PLC。
- 手动按钮测试断言复用同一发送入口。
- 状态监听测试覆盖空值持续等待、从空值变为 `0/1/2`、查询失败，以及等待期间
  PLC 零写入。
- Worker 和 UI 测试使用假客户端，覆盖完成、停止、超时、错序和报警展示。
- 全量测试不得访问真实 PLC、MySQL 或 `D:\research_code\tongxun`。
