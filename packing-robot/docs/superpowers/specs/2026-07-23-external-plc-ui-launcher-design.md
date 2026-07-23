# 外部 PLC 通讯 UI 启动设计

## 目标

机器人装箱三维仿真系统不再直接连接 PLC 或写 DB19。当前系统只计算并展示
`state=1/2`；生产数据中的 `state` 由数据库承载。操作员点击一个按钮后打开原来的
`D:\research_code\tongxun\plc_gui.py`，在旧界面中手动输入
`box_unique_id`，由旧界面查询 `zhuangdb.wcs_success_box.state` 并完成 PLC 通讯。

## 方案

旧 PLC 界面以独立进程启动，不把 `plc_gui.py` 的窗口类导入当前进程。这样可以：

- 继续使用旧界面已有的 `box_unique_id` FIFO、MySQL 设置、查询、DB19 握手和日志。
- 避免两个系统的同名模块、Qt 主循环和后台线程相互影响。
- 保证 PLC 执行入口唯一，不会出现当前 UI 与旧 UI 同时写 DB19。

## 当前 UI 变化

- 删除右侧的 PLC IP、端口、Rack/Slot、DB、连接、开始发送、停止和 DB19 日志。
- 增加“打开 PLC 通讯界面”按钮。
- 增加说明文字：“state 由数据库交接；请在 PLC 界面输入 box_unique_id”。
- 点击按钮时执行当前 Python 解释器和
  `D:\research_code\tongxun\plc_gui.py`，工作目录设为
  `D:\research_code\tongxun`。
- 如果旧 UI 进程仍在运行，重复点击不会再启动第二个实例。
- 如果目录或脚本不存在，当前 UI 显示明确错误。

## state 契约

- `state=1`：A / `x_min_y_min` / 不旋转。
- `state=2`：B / `x_max_y_min` / 旋转 90°。
- 当前 UI 不把 state 直接写 DBW12。
- 旧 PLC UI 从 `wcs_success_box.state` 读取 state，再根据原有协议写 DBW12。
- 当前 UI 没有 `box_unique_id`，因此不执行仅凭 `pallet_id/seq` 猜测目标行的数据库
  UPDATE；数据库写入由产生 `wcs_success_box` 记录的上游流程负责。

## 测试

- 启动器测试命令、工作目录、缺失脚本和重复启动。
- UI 测试确认只显示启动按钮，不再显示直接 PLC 连接/发送控件。
- 全量测试不启动真实旧 UI、不连接 MySQL、不连接 PLC。

