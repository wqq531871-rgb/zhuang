# Product Code 状态数据库同步设计

## 目标

相机姿态与托盘目标姿态完成判断后，当前系统把每个箱子的
`rotation_state` 写入 MySQL `zhuangdb.wcs_success_box.state`。匹配键为
`product_code`，其值来自当前动作的 `item_id`。旧 PLC UI 继续按
`box_unique_id` 查询整盘记录，并读取更新后的 state 发送 PLC。

## 字段契约

- `product_code = RobotAction.item_id`
- `state = RobotAction.rotation_state`
- `state=1`：A / `x_min_y_min` / 不旋转
- `state=2`：B / `x_max_y_min` / 旋转 90°
- 只有已绑定相机数据的动作才允许同步。

## 数据库更新

一批相机数据对应一个事务。对每个 product_code：

1. 执行参数化查询：
   `SELECT id FROM wcs_success_box WHERE product_code=%s FOR UPDATE`
2. 必须恰好查到一条记录。没有记录或多条记录都视为错误。
3. 按主键执行：
   `UPDATE wcs_success_box SET state=%s WHERE id=%s`
4. 全部箱子成功后统一 commit；任意箱失败则 rollback。

虽然字段注释说明 product_code 是箱子唯一编号，但表结构没有唯一索引，因此同步层
必须主动检测重复记录，避免误改历史数据。

## 配置

复用旧 PLC UI 的 `QSettings("OpenAI", "PLCPalletSender")`：

- `mysql/host`，默认 `localhost`
- `mysql/port`，默认 `3306`
- `mysql/user`，默认 `root`
- `mysql/database`，默认 `zhuangdb`

密码只读取当前进程环境变量 `ZHUANGDB_PASSWORD`，不写入设置、不打印到日志。

## UI 与线程

- `receive_camera_data()` 原子绑定相机数据并重建动作后，提取本批箱子的
  `(product_code, state)`。
- MySQL 更新在 `QThread` 工作对象中执行，不阻塞三维界面。
- PLC 入口区显示“数据库 state：同步中 / 已同步 N 箱 / 同步失败”。
- 同步失败只报告错误，不启动任何 PLC 通讯，也不对失败事务做部分提交。
- 旧 PLC UI 启动按钮在同步期间禁用，结束后恢复；失败状态明确提示操作员不得执行
  旧 PLC UI 中的发送动作，重新导入相机数据可重试同步。

## 测试

- 假 MySQL 连接验证参数化 SQL、唯一记录、commit、rollback 和密码不泄漏。
- Worker 测试验证成功与失败信号。
- UI 测试验证 `item_id→product_code`、`rotation_state→state`、同步状态和按钮锁定。
- 自动测试不连接现场 MySQL 或 PLC。

