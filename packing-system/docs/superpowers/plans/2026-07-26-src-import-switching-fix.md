# Source Import Switching Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复源码模式下打开接口维护后无法导入 `src.service.wcs_service` 的问题，同时保留接口 4.7 的 `data.status` 功能。

**Architecture:** UI 运行期统一以 `packing-system/packing/src` 为规范 `src` 包。顶层设备状态实现通过与现有数据库服务相同的文件桥接方式挂入 packing 的 `src.service`，接口维护代码不再删除或替换 `sys.modules` 中的整套 `src`。

**Tech Stack:** Python 3、PyQt5、pytest、importlib、subprocess

## Global Constraints

- 仅修改源码运行路径，不修改 `PackingWorkbench.exe`、PyInstaller spec 或发布流程。
- 不修改 `sql/wcs_success_box.sql`，不读取或更新不存在的 `wcs_success_box.status`。
- 保留接口 4.7 的 `data.status` 运行时 JSON 功能。
- `state` 继续表示箱子朝向；`is_send=2`、`NULL` 或空字符串表示未下传；`is_send=1` 表示已下传。
- WCS 请求失败时不得更新 `is_send`。
- 不合并或重命名两套 `src` 目录。

---

### Task 1: 用回归测试锁定“接口维护后仍可下传”

**Files:**
- Create: `packing-system/ui/tests/test_wcs_import_switching.py`
- Create: `packing-system/packing/src/service/device_status_store.py`
- Modify: `packing-system/ui/wcs_api_maintain_dialog.py`
- Modify: `packing-system/ui/realtime_dashboard_v3_clean.py:1559-1564`

**Interfaces:**
- Consumes: 顶层实现 `packing-system/src/service/device_status_store.py`
- Produces: `src.service.device_status_store` 桥接模块，以及保持 packing `src` 不变的 `_ensure_device_status_import(project_dir)`

- [ ] **Step 1: 写入失败回归测试**

```python
from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_interface_maintenance_keeps_packing_src_for_wcs_import():
    script = f"""
import sys
from pathlib import Path
from types import SimpleNamespace

root = Path({str(ROOT)!r})
packing = root / "packing"
ui = root / "ui"
sys.path[:0] = [str(ui), str(root), str(packing)]

from realtime_dashboard_v3_clean import IndustrialPackingWorkbenchClean

dummy = SimpleNamespace(project_dir=root)
resolved = IndustrialPackingWorkbenchClean._ensure_packing_import_path(dummy)
assert resolved == packing.resolve()
assert Path(sys.path[0]).resolve() == packing.resolve()

from wcs_api_maintain_dialog import _ensure_device_status_import

store = _ensure_device_status_import(root)
assert store.STATUS_READY == 0

import src.service
service_dir = Path(src.service.__file__).resolve().parent
assert service_dir == (packing / "src" / "service").resolve()

import src.service.wcs_service
print(src.service.wcs_service.__file__)
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
```

- [ ] **Step 2: 运行测试并确认按正确原因失败**

Run:

```powershell
python -m pytest -q ui/tests/test_wcs_import_switching.py
```

Expected: FAIL；现有 `_ensure_packing_import_path` 不会把已存在的 packing 路径移到首位，或接口维护切换到顶层 `src.service` 后无法导入 `wcs_service`。

- [ ] **Step 3: 新增设备状态桥接模块**

在 `packing/src/service/device_status_store.py` 中使用
`importlib.util.spec_from_file_location` 加载顶层实现，内部模块名固定为
`_zhuang_device_status_store_impl`。导出：

```python
STATUS_READY = _impl.STATUS_READY
STATUS_BUSY = _impl.STATUS_BUSY
STATUS_ERROR = _impl.STATUS_ERROR
workspace_root = _impl.workspace_root
runtime_dir = _impl.runtime_dir
device_status_path = _impl.device_status_path
write_device_status = _impl.write_device_status
read_device_status = _impl.read_device_status
mark_busy_on_palletarrive = _impl.mark_busy_on_palletarrive
mark_ready_on_kongxian_idle = _impl.mark_ready_on_kongxian_idle
```

目标文件路径使用：

```python
Path(__file__).resolve().parents[3] / "src" / "service" / "device_status_store.py"
```

- [ ] **Step 4: 停止接口维护模块切换整套 `src`**

将 `_ensure_device_status_import` 改为：

```python
def _ensure_device_status_import(project_dir: Optional[Path]) -> Any:
    root = _packing_system_root(project_dir)
    packing_root = (root / "packing").resolve()
    packing_s = str(packing_root)
    if not (packing_root / "src" / "service" / "device_status_store.py").is_file():
        raise FileNotFoundError(f"找不到 device_status_store 桥接：{packing_root}")
    sys.path[:] = [p for p in sys.path if p != packing_s]
    sys.path.insert(0, packing_s)
    from src.service import device_status_store as store
    return store
```

删除原函数中把仓库根放首位以及清理 `sys.modules["src*"]` 的逻辑。

- [ ] **Step 5: 让 UI 路径辅助函数真正提升 packing 优先级**

将 `_ensure_packing_import_path` 改为：

```python
def _ensure_packing_import_path(self) -> Path:
    packing_root = Path(self.project_dir).resolve() / "packing"
    root_s = str(packing_root)
    sys.path[:] = [p for p in sys.path if p != root_s]
    sys.path.insert(0, root_s)
    return packing_root
```

- [ ] **Step 6: 运行回归测试并确认通过**

Run:

```powershell
python -m pytest -q ui/tests/test_wcs_import_switching.py
```

Expected: PASS。

- [ ] **Step 7: 提交本任务**

```powershell
git add -- packing-system/ui/tests/test_wcs_import_switching.py packing-system/packing/src/service/device_status_store.py packing-system/ui/wcs_api_maintain_dialog.py packing-system/ui/realtime_dashboard_v3_clean.py
git commit -m "fix: keep packing src active after status maintenance"
```

### Task 2: 修正源码启动器的路径优先级

**Files:**
- Create: `packing-system/tests/test_app_launcher_paths.py`
- Modify: `packing-system/app_launcher.py:40-74`

**Interfaces:**
- Consumes: `app_launcher.ensure_runtime_env()`
- Produces: 非冻结源码模式下稳定的 `packing > ui > local_wcs_receiver > root` 搜索顺序

- [ ] **Step 1: 写入失败测试**

```python
from __future__ import annotations

import sys
from pathlib import Path

import app_launcher


def test_source_runtime_keeps_packing_path_first(monkeypatch, tmp_path):
    root = tmp_path / "packing-system"
    for rel in ("packing", "ui", "local_wcs_receiver", "config"):
        (root / rel).mkdir(parents=True)
    workspace = tmp_path / "packing-workspace"

    monkeypatch.setattr(app_launcher, "is_frozen", lambda: False)
    monkeypatch.setattr(app_launcher, "app_root", lambda: root)
    monkeypatch.setattr(app_launcher, "bundle_root", lambda: root)
    monkeypatch.setenv("PACKING_WORKSPACE", str(workspace))
    original = list(sys.path)
    try:
        app_launcher.ensure_runtime_env()
        expected = [
            str(root / "packing"),
            str(root / "ui"),
            str(root / "local_wcs_receiver"),
            str(root),
        ]
        assert sys.path[:4] == expected
    finally:
        sys.path[:] = original
```

- [ ] **Step 2: 运行测试并确认路径顺序失败**

Run:

```powershell
python -m pytest -q tests/test_app_launcher_paths.py
```

Expected: FAIL；当前连续 `insert(0, ...)` 得到反向顺序。

- [ ] **Step 3: 实现保持声明顺序的路径函数**

在 `app_launcher.py` 中新增：

```python
def _put_existing_paths_first(paths) -> None:
    ordered = []
    for path in paths:
        path = Path(path)
        if not path.exists():
            continue
        value = str(path)
        if value not in ordered:
            ordered.append(value)
    sys.path[:] = ordered + [p for p in sys.path if p not in ordered]
```

`ensure_runtime_env` 在 `not is_frozen()` 分支调用：

```python
_put_existing_paths_first(
    (
        root / "packing",
        root / "ui",
        root / "local_wcs_receiver",
        root,
    )
)
```

冻结分支保持现有行为，不修改 spec 或打包逻辑。

- [ ] **Step 4: 运行启动器测试并确认通过**

Run:

```powershell
python -m pytest -q tests/test_app_launcher_paths.py
```

Expected: PASS。

- [ ] **Step 5: 联合运行两项导入测试**

Run:

```powershell
python -m pytest -q tests/test_app_launcher_paths.py ui/tests/test_wcs_import_switching.py
```

Expected: 2 passed。

- [ ] **Step 6: 提交本任务**

```powershell
git add -- packing-system/tests/test_app_launcher_paths.py packing-system/app_launcher.py
git commit -m "fix: preserve source import path priority"
```

### Task 3: 相关回归与数据库契约验证

**Files:**
- Verify: `packing-system/sql/wcs_success_box.sql`
- Verify: `packing-system/src/service/success_box_db.py`
- Verify: `packing-system/packing/src/service/wcs_service.py`

**Interfaces:**
- Consumes: Task 1 和 Task 2 完成后的源码
- Produces: 导入修复、接口状态和下传数据库行为的验证证据

- [ ] **Step 1: 验证下传代码未访问表字段 `status`**

Run:

```powershell
rg -n "wcs_success_box.*status|status.*wcs_success_box" sql/wcs_success_box.sql src/service/success_box_db.py packing/src/service/wcs_service.py
```

Expected: 无匹配；接口 4.7 的 `data.status` 不计入该数据库字段检查。

- [ ] **Step 2: 运行设备状态与成功托盘仓储测试**

Run:

```powershell
python -m pytest -q tests/test_device_status_store.py tests/test_success_box_db.py
```

Expected: PASS。

- [ ] **Step 3: 运行 WCS 服务测试**

Run:

```powershell
python -m pytest -q packing/tests/test_wcs_service.py
```

Expected: PASS。

- [ ] **Step 4: 运行 UI 测试**

Run from `packing-system/ui`:

```powershell
python -m pytest -q tests
```

Expected: PASS。

- [ ] **Step 5: 检查补丁质量和工作区范围**

Run:

```powershell
git diff --check
git status --short
```

Expected: 无空白错误；只包含本计划文件和实现文件，已有运行时数据改动保持原样且未被提交。

- [ ] **Step 6: 提交计划文档**

```powershell
git add -- packing-system/docs/superpowers/plans/2026-07-26-src-import-switching-fix.md
git commit -m "docs: add src import switching implementation plan"
```
