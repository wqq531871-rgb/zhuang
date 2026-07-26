# 源码模式下 WCS 下传导入切换修复设计

## 背景

实时工作台下传托盘时会执行：

```python
from src.service.wcs_service import load_data_source_config, push_plan_result
```

工程中同时存在两套同名包：

- `packing-system/packing/src`
- `packing-system/src`

UI 的接口维护功能为了访问顶层
`src/service/device_status_store.py`，会重排 `sys.path`、删除已经加载的
`src`/`src.*` 模块，再把 `packing-system/src` 作为新的 `src` 包。此后下传
功能拿到的是顶层 `src.service`；该目录没有 `wcs_service.py`，于是抛出
`ModuleNotFoundError: No module named 'src.service.wcs_service'`。

## 目标

- 源码模式下，打开接口维护功能后仍可正常下传 WCS。
- UI 进程始终以 `packing-system/packing/src` 作为规范的 `src` 包。
- 保留接口 4.7 的 `data.status` 维护功能。
- 保持 `wcs_success_box` 当前表结构，不新增或读取 `status` 字段。
- WCS 请求失败时不得把托盘标记为已下传。

## 非目标

- 不修改 `PackingWorkbench.exe`、PyInstaller spec 或发布流程。
- 不合并或重命名两套 `src` 目录。
- 不修改 `wcs_success_box.sql`。
- 不改变 WCS 请求体、接口地址或接口成功判定规则。
- 不移除接口 4.7 的 `data.status` 功能。

## 方案

### 1. 固定 UI 的规范 `src`

源码启动时把 `packing-system/packing` 固定在相关搜索路径的最前面。
路径辅助函数不能只在路径不存在时插入；如果路径已经存在但优先级不正确，
应先移除再插入到索引 0。

`app_launcher.py` 仅在 `not is_frozen()` 的源码分支中使用同一优先级：

1. `packing-system/packing`
2. `packing-system/ui`
3. `packing-system/local_wcs_receiver`
4. `packing-system`

循环中连续调用 `sys.path.insert(0, ...)` 会反转声明顺序，因此实现时必须
显式保持上述最终顺序。

### 2. 使用桥接模块访问设备状态实现

新增 `packing/src/service/device_status_store.py`。该文件遵循已有
`success_box_db.py`、`plc_queue_db.py` 桥接模式，通过
`importlib.util.spec_from_file_location` 以唯一内部模块名加载：

```text
packing-system/src/service/device_status_store.py
```

桥接模块导出设备状态实现的公开常量和函数：

- `STATUS_READY`
- `STATUS_BUSY`
- `STATUS_ERROR`
- `workspace_root`
- `runtime_dir`
- `device_status_path`
- `write_device_status`
- `read_device_status`
- `mark_busy_on_palletarrive`
- `mark_ready_on_kongxian_idle`

这样 UI 和 packing 侧代码都可以使用
`src.service.device_status_store`，同时 `src` 仍指向
`packing-system/packing/src`。

### 3. 移除运行期整包切换

修改 `ui/wcs_api_maintain_dialog.py`：

- 不再把 `packing-system` 放到 `sys.path` 首位。
- 不再遍历并删除 `sys.modules` 中的 `src` 和 `src.*`。
- 确保 `packing-system/packing` 位于导入路径首位。
- 通过新增桥接模块导入 `src.service.device_status_store`。

运行中的 Python 包不再被卸载或替换，已加载模块的类型、单例和依赖关系
保持稳定。

## 数据流

### 接口维护

```text
接口维护窗口
  -> src.service.device_status_store（packing 侧桥接）
  -> packing-system/src/service/device_status_store.py（实际实现）
  -> packing-workspace/runtime/wcs_device_status.json
```

### 托盘下传

```text
选择未下传托盘
  -> src.service.success_box_db（packing 侧桥接）
  -> 读取 wcs_success_box 中 is_send=2/NULL/空字符串的记录
  -> src.service.wcs_service
  -> POST WCS 接口 2
  -> 接口成功后把所选托盘 is_send 更新为 1
```

接口维护与托盘下传共享同一个 `packing/src` 包，不再互相改变导入环境。

## 数据库约束

`wcs_success_box` 不包含 `status` 字段，本次修复不得生成任何读取或更新
该字段的 SQL。

相关字段语义保持不变：

- `state`：箱子朝向。
- `is_send=2`、`NULL` 或空字符串：未下传。
- `is_send=1`：已下传。

接口 4.7 的 `data.status` 保存在运行时 JSON 中，与
`wcs_success_box` 表字段无关。

## 错误处理

- 桥接目标文件不存在或无法加载时，抛出包含目标路径的 `ImportError`。
- WCS HTTP 请求异常、非 2xx 响应、非法 JSON 或返回 `code != 0` 时，
  下传保持失败。
- 只有 WCS 返回成功后才能调用 `mark_sent_by_unique_ids`。
- 导入失败时继续使用现有 UI 错误弹窗和日志入口，不吞掉异常原因。

## 测试设计

### 导入回归

增加测试验证：

1. `packing-system/packing` 是规范导入根。
2. 调用接口维护的设备状态加载函数后，
   `src.service` 仍来自 `packing/src/service`。
3. 随后导入 `src.service.wcs_service` 成功。
4. 设备状态桥接导出的函数与顶层实现行为一致。

### 下传行为

通过 mock 数据库仓储和 HTTP 请求验证：

- 下传使用所选 `box_unique_id` 构造请求。
- 接口成功后才更新 `is_send=1`。
- 接口失败时不更新 `is_send`。
- 下传路径不访问 `wcs_success_box.status`。

### 现有回归

至少运行：

```powershell
python -m pytest -q packing/tests/test_wcs_service.py
python -m pytest -q tests/test_device_status_store.py
python -m pytest -q tests/test_success_box_db.py
python -m pytest -q ui/tests
```

最后执行源码级导入烟雾测试，模拟“打开接口维护后再下传”的顺序。

## 验收标准

- 源码启动实时工作台后，先打开并关闭接口维护窗口，再执行托盘下传，
  不再出现 `No module named 'src.service.wcs_service'`。
- 接口 4.7 的 `data.status` 仍可读写。
- `wcs_success_box` 的未下传查询和成功标记仍只依赖 `is_send`。
- 所有相关自动化测试通过。
