# PLC 相机尺寸入库与 state 驱动下传设计

## 目标

修正 Siemens PLC DB19 中相机尺寸的通讯方向。三维程序从 PLC 的 SEND 区
读取 `DBW6/DBW8/DBW10`，分别写入当前
`box_unique_id + seq` 对应数据库记录的
`camera_length/camera_width/camera_height`。现有判态监听根据相机尺寸生成
`state=0/1/2`，PLC 下传线程再按当前箱的 `state` 写 REV 区。

本次不修改 `DBW34 stack_height_before: Int`，不改变已经确认的 FP/DH_OVER
握手语义，也不在三维程序中新增第二套判态算法。

## DB19 字段方向

### SEND：PLC 发给三维程序

| 偏移 | 字段 | 行为 |
|---:|---|---|
| DBW0 | `FP` | PLC 置 1 发起请求；程序收到完成回执后清 0 |
| DBW2 | `FP_ZYXH` | PLC 请求的当前箱 `seq` |
| DBW4 | `FP_OVER` | PLC 对本箱 REV 数据的完成回执 |
| DBW6 | `CHANG` | 相机测得长度，程序读取后写数据库 |
| DBW8 | `KUAN` | 相机测得宽度，程序读取后写数据库 |
| DBW10 | `GAO` | 相机测得高度，程序读取后写数据库 |
| DBW12 | `KONGXIAN` | 程序只读取和显示 |

### REV：三维程序发给 PLC

| 偏移 | 字段 | 数据来源或行为 |
|---:|---|---|
| DBW14 | `chang` | 数据库 `raw_length` |
| DBW16 | `kuan` | 数据库 `raw_width` |
| DBW18 | `gao` | 数据库 `raw_height` |
| DBW20 | `x` | 数据库 `pos_y`，按现有 PLC 坐标约定与 XY 对调 |
| DBW22 | `y` | 数据库 `pos_x`，按现有 PLC 坐标约定与 XY 对调 |
| DBW24 | `z` | 数据库 `pos_z` |
| DBW26 | `FXBC` | 数据库 `state` |
| DBW28 | `ZYXH` | 数据库 `box_num` |
| DBW30 | `DH_OVER` | REV 数据全部写完后最后置 1 |
| DBW32 | `baojing` | `state=0` 写 1，正常箱写 0 |
| DBW34 | `stack_height_before` | 保持现有 `Int` 写入，不修改 |

正常 REV 命令不得包含 DBW6、DBW8 或 DBW10。

## 组件职责

### PLC 协议层

一次读取 DBW0 至 DBW12，解析 FP、请求 seq、FP_OVER、相机长宽高和
KONGXIAN；另行读取 DBW30 的 DH_OVER。等待条件仍为：

```text
FP=1、FP_OVER=0、DH_OVER=0
```

等待成功后必须先校验 PLC 请求 seq 与当前数据库 seq。只有一致时才能向上层返回
相机尺寸；错序时不得写数据库或 REV。

正常命令只构造和写入 REV 字段。所有 REV 数据写完后最后置
`DBW30 DH_OVER=1` 并保持为 1。检测到 `DBW4 FP_OVER=1` 后，程序清
`DBW0 FP=0` 和 `DBW30 DH_OVER=0`，再等待 PLC 将 FP_OVER 清零后进入下一箱。

### 数据库适配层

新增按 `box_unique_id + seq` 更新相机尺寸的单一接口。该接口只更新：

```text
camera_length
camera_width
camera_height
```

它不直接写 `state`，也不重置已经存在的 `state`。找不到对应记录或数据库更新失败
时返回明确错误，PLC 下传线程停止当前托盘且不写 REV。

### 判态监听

现有判态监听在程序运行期间保持常驻，每 0.5 秒扫描：

```text
camera_length > 0
camera_width > 0
camera_height > 0
state IS NULL
```

符合条件的记录继续使用现有尺寸比较规则写 `state=0/1/2`。本次不复制或迁移
该算法。

### PLC 下传线程

每箱严格执行：

1. 等待 `FP=1、FP_OVER=0、DH_OVER=0`。
2. 校验 PLC 请求 seq。
3. 读取 DBW6/8/10；任一值小于等于 0 时停止并报告错误。
4. 将相机长宽高写入当前 `box_unique_id + seq` 的数据库记录。
5. 只从此时开始轮询该记录的 `state`。
6. `state IS NULL` 时继续等待，且不写 REV。
7. `state=0` 时按现有协议只写 `DBW32 baojing=1`，然后停止正常下传。
8. `state=1/2` 时再次确认 FP、seq、FP_OVER、DH_OVER，写入完整 REV，
   最后置 DH_OVER 并完成回执复位。
9. 其他 state 值停止整盘并报告错误。

判态监听是常驻的；“等待当前箱 state”仅在该箱相机尺寸成功写库后开始。

## 错误和安全

- PLC 请求 seq 不一致：数据库和 REV 均零写入。
- DBW6/8/10 任一值小于等于 0：不写数据库，不写 REV，停止当前托盘。
- 相机尺寸写库失败或目标记录不存在：不写 REV，停止当前托盘。
- 等待 state 时收到停止请求：安全退出，保持 REV 零写入。
- 正常 REV 写入开始后发生通讯错误：保持现有策略，停止整盘且不自动重发。
- 自动下发仍默认关闭；本次不改变连接或人工启停权限。

## 测试

测试不连接真实 PLC 或 MySQL，覆盖：

1. DBW0 至 DBW12 的单次读取可正确解析相机长宽高。
2. 正常 REV 命令不包含 DBW6、DBW8、DBW10。
3. DBW34 继续写入 `stack_height_before: Int`。
4. seq 不一致时数据库写入回调和 PLC 写入均不发生。
5. 相机尺寸小于等于 0 时数据库和 REV 均零写入。
6. 相机尺寸按 `box_unique_id + seq` 写入三个 camera 字段。
7. 相机尺寸写库后才开始轮询当前箱 state。
8. `state=NULL/0/1/2` 的等待、报警和正常下传分支。
9. 正常握手继续保持“DH_OVER 最后置 1、FP_OVER=1 后清 FP 与
   DH_OVER、等待 FP_OVER 清零”的顺序。
