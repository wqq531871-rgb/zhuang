# Multi-Path Layout State Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a runtime camera/layout state-path switch so the current pallet can write `state` directly from box X/Y layout dimensions and send to PLC without camera input.

**Architecture:** A focused `layout_state` module owns path constants, dimension rules, and the transactional pallet update keyed by `box_unique_id + seq`. The existing UI selects the path and applies layout state to the current pallet; `build_action` and `PlcSendWorker` receive the selected path explicitly so camera requirements remain unchanged in camera mode and are skipped in layout mode.

**Tech Stack:** Python 3, PySide6, PyMySQL, pytest, existing Siemens S7 protocol adapter.

## Global Constraints

- Default path on every application start is `camera`.
- `layout` maps `raw_width > raw_length` to `state=1`, `raw_length > raw_width` to `state=2`, and equality to `state=1`.
- `layout` never reads, validates, or writes `camera_length/camera_width/camera_height`.
- Database updates are atomic per `box_unique_id`, lock rows with `FOR UPDATE`, and update by primary key `id`.
- Existing camera behavior and PLC handshake semantics must remain unchanged.
- No live MySQL or PLC connection is used by automated tests.

---

### Task 1: Layout State Rule and Transactional Repository

**Files:**
- Create: `packing_ui/layout_state.py`
- Create: `tests/test_layout_state.py`

**Interfaces:**
- Produces: `STATE_PATH_CAMERA = "camera"` and `STATE_PATH_LAYOUT = "layout"`.
- Produces: `normalize_state_path(value: object) -> str`.
- Produces: `state_from_layout_dims(x_size: object, y_size: object) -> int`.
- Produces: `LayoutStateDecision(seq: int, x_size: float, y_size: float, previous_state: int | None, state: int)`.
- Produces: `LayoutStateAssignment(box_unique_id: str, box_count: int, changed_count: int, decisions: tuple[LayoutStateDecision, ...])`.
- Produces: `assign_pallet_layout_states(box_unique_id: str, *, config_path: Path | None = None, settings: Mapping[str, Any] | None = None, connect_factory: Any = pymysql.connect) -> LayoutStateAssignment`.

- [ ] **Step 1: Write failing rule and repository tests**

```python
@pytest.mark.parametrize(
    ("x_size", "y_size", "expected"),
    [(300, 400, 1), (400, 300, 2), (400, 400, 1)],
)
def test_state_from_layout_dims(x_size, y_size, expected):
    assert state_from_layout_dims(x_size, y_size) == expected

def test_repository_locks_current_pallet_updates_by_id_and_commits_once():
    connection = FakeConnection([
        {"id": 11, "seq": 1, "raw_length": 300, "raw_width": 400, "state": None},
        {"id": 12, "seq": 2, "raw_length": 500, "raw_width": 200, "state": 1},
    ])
    result = assign_pallet_layout_states(
        "a" * 32,
        settings=SETTINGS,
        connect_factory=lambda **_kwargs: connection,
    )
    assert [decision.state for decision in result.decisions] == [1, 2]
    assert result.changed_count == 2
    assert connection.commits == 1
    assert connection.rollbacks == 0
```

- [ ] **Step 2: Run the new tests and confirm failure**

Run: `python -m pytest tests/test_layout_state.py -q`

Expected: FAIL because `packing_ui.layout_state` does not exist.

- [ ] **Step 3: Implement validation and transaction**

```python
def state_from_layout_dims(x_size: object, y_size: object) -> int:
    x_value = float(x_size)
    y_value = float(y_size)
    if not math.isfinite(x_value) or not math.isfinite(y_value):
        raise LayoutStateError("箱子 X/Y 尺寸必须是有限数值")
    if x_value <= 0 or y_value <= 0:
        raise LayoutStateError("箱子 X/Y 尺寸必须大于 0")
    return 1 if y_value >= x_value else 2
```

The transaction must execute:

```sql
SELECT id, seq, raw_length, raw_width, state
FROM wcs_success_box
WHERE box_unique_id = %s
ORDER BY seq ASC
FOR UPDATE
```

and update changed rows with:

```sql
UPDATE wcs_success_box SET state = %s WHERE id = %s
```

It must reject an empty UID, no rows, duplicate/non-contiguous seq values, invalid dimensions, and connection/update errors; every failure after connection rolls back and closes resources.

- [ ] **Step 4: Run repository tests**

Run: `python -m pytest tests/test_layout_state.py -q`

Expected: all tests PASS.

- [ ] **Step 5: Commit the repository**

```powershell
git add -- packing-robot/packing_ui/layout_state.py packing-robot/tests/test_layout_state.py
git commit -m "feat: assign pallet states from layout dimensions"
```

### Task 2: Make Three-Dimensional Readiness Path-Aware

**Files:**
- Modify: `packing_ui/data.py`
- Modify: `packing_ui/main_window.py`
- Modify: `tests/test_data.py`

**Interfaces:**
- Consumes: `STATE_PATH_CAMERA`, `STATE_PATH_LAYOUT`, and `normalize_state_path`.
- Changes: `build_action(..., state_source: str = STATE_PATH_CAMERA) -> RobotAction`.
- Produces: camera mode requires complete `camera_*`; layout mode only requires a ready database state.

- [ ] **Step 1: Write failing action readiness tests**

```python
def test_layout_state_path_is_ready_without_camera_dimensions():
    item = item_with_original_state(state=1, camera_dims=(None, None, None))
    action = build_action(item, 0, 0, state_source=STATE_PATH_LAYOUT)
    assert action.show_on_conveyor is True
    assert action.plc_ready is True

def test_camera_state_path_still_waits_without_camera_dimensions():
    item = item_with_original_state(state=1, camera_dims=(None, None, None))
    action = build_action(item, 0, 0, state_source=STATE_PATH_CAMERA)
    assert action.show_on_conveyor is False
```

- [ ] **Step 2: Run the focused tests and confirm failure**

Run: `python -m pytest tests/test_data.py -q`

Expected: FAIL because `build_action` does not accept `state_source`.

- [ ] **Step 3: Implement path-aware readiness**

```python
source = normalize_state_path(state_source)
dims_required = source == STATE_PATH_CAMERA
show_on_conveyor = state_ok and (dims_ok or not dims_required)
```

Pass the selected source from `PackingMainWindow._rebuild_actions`, and change the list fallback text from `待相机` to `待判态`.

- [ ] **Step 4: Run action and UI smoke tests**

Run: `python -m pytest tests/test_data.py tests/test_ui_smoke.py -q`

Expected: all tests PASS.

- [ ] **Step 5: Commit readiness behavior**

```powershell
git add -- packing-robot/packing_ui/data.py packing-robot/packing_ui/main_window.py packing-robot/tests/test_data.py
git commit -m "feat: make 3d readiness state-path aware"
```

### Task 3: Make PLC Sending Path-Aware

**Files:**
- Modify: `packing_ui/plc_worker.py`
- Modify: `tests/test_plc_worker.py`

**Interfaces:**
- Consumes: `STATE_PATH_CAMERA`, `STATE_PATH_LAYOUT`, and `normalize_state_path`.
- Changes: `PlcSendWorker.__init__(..., state_source: str = STATE_PATH_CAMERA)`.
- Preserves: all existing worker signals and camera-path behavior.

- [ ] **Step 1: Write failing layout PLC tests**

```python
def test_layout_path_skips_camera_dimensions_and_reads_state_directly():
    calls = []
    protocol = FakeProtocol(
        inbound=SimpleNamespace(camera_length=0, camera_width=0, camera_height=0)
    )
    target = make_worker(
        protocol=protocol,
        row_loader=lambda uid, seq: calls.append(("state", uid, seq)) or ROW,
        camera_writer=lambda *_args: calls.append(("camera",)),
        state_source=STATE_PATH_LAYOUT,
    )
    target.run()
    assert calls == [("state", "a" * 32, 7)]
    assert [command.sequence for command in protocol.normal] == [7]
```

- [ ] **Step 2: Run worker tests and confirm failure**

Run: `python -m pytest tests/test_plc_worker.py -q`

Expected: FAIL because the worker does not accept `state_source`.

- [ ] **Step 3: Implement the branch**

After `wait_request(seq)`, preserve the current camera validation/write block only when:

```python
if self.state_source == STATE_PATH_CAMERA:
    ...
else:
    self.status.emit(f"seq={seq} 使用垛型直判，跳过相机尺寸并读取数据库 state")
```

Then both paths share the existing state polling, alarm, command construction, send, and handshake code.

- [ ] **Step 4: Run worker tests**

Run: `python -m pytest tests/test_plc_worker.py -q`

Expected: all tests PASS, including existing camera assertions.

- [ ] **Step 5: Commit PLC branching**

```powershell
git add -- packing-robot/packing_ui/plc_worker.py packing-robot/tests/test_plc_worker.py
git commit -m "feat: bypass camera ingest in layout state path"
```

### Task 4: Add the Runtime Path Switch and Current-Pallet Apply Flow

**Files:**
- Modify: `packing_ui/main_window.py`
- Modify: `tests/test_ui_smoke.py`
- Modify: `README.md`

**Interfaces:**
- Consumes: `assign_pallet_layout_states`, path constants, and `LayoutStateAssignment`.
- Adds constructor dependency: `layout_state_writer: Any = None`.
- Produces: `current_state_path() -> str`.
- Produces: `_apply_layout_state_to_current_plan(*, automatic: bool) -> LayoutStateAssignment`.

- [ ] **Step 1: Write failing UI switch tests**

```python
def test_window_defaults_to_camera_and_can_switch_to_layout():
    window = _test_window()
    assert window.state_path_combo.currentData() == STATE_PATH_CAMERA
    window.state_path_combo.setCurrentIndex(
        window.state_path_combo.findData(STATE_PATH_LAYOUT)
    )
    assert window.current_state_path() == STATE_PATH_LAYOUT

def test_apply_layout_path_writes_current_uid_and_refreshes_actions(monkeypatch):
    calls = []
    window = _test_window(
        layout_state_writer=lambda uid, **kwargs: calls.append((uid, kwargs))
        or assignment_for(uid)
    )
    window.load_path(SAMPLE)
    window.state_path_combo.setCurrentIndex(
        window.state_path_combo.findData(STATE_PATH_LAYOUT)
    )
    monkeypatch.setattr(window, "_reload_current_plan_after_layout", lambda: None)
    window.apply_state_path_button.click()
    assert calls[0][0] == window.current_plan.source_key
```

- [ ] **Step 2: Run UI tests and confirm failure**

Run: `python -m pytest tests/test_ui_smoke.py -q`

Expected: FAIL because the switch and apply button do not exist.

- [ ] **Step 3: Build the controls and apply flow**

Add these controls to the pallet selector form:

```python
self.state_path_combo = QComboBox()
self.state_path_combo.addItem("相机判态", STATE_PATH_CAMERA)
self.state_path_combo.addItem("垛型直判（无相机）", STATE_PATH_LAYOUT)
self.apply_state_path_button = QPushButton("应用到当前托盘")
self.state_path_status_label = QLabel("当前：相机判态")
```

The apply button must:

1. Report camera mode without changing data.
2. In layout mode call the injected writer with the current UID and config path.
3. Reload the current plan from MySQL, replace the corresponding combo/all-plans entry, rebuild actions, and log the box/changed counts.
4. Catch errors for manual clicks and keep PLC stopped.

Before manual PLC start in layout mode, apply the path automatically. During WCS live pallet load in layout mode, apply it before playback and `_maybe_auto_start_plc`. Pass the selected source into `PlcSendWorker`.

- [ ] **Step 4: Document operation**

Update `README.md` with:

```text
判态路径默认“相机判态”。选择“垛型直判（无相机）”后，当前托盘按
raw_width >= raw_length 写 state=1，否则写 state=2；该模式的 PLC 下发
忽略 DBW6/8/10。切回相机路径不会自动清空已有 state。
```

- [ ] **Step 5: Run focused integration tests**

Run: `python -m pytest tests/test_layout_state.py tests/test_data.py tests/test_plc_worker.py tests/test_ui_smoke.py -q`

Expected: all tests PASS.

- [ ] **Step 6: Commit the UI flow**

```powershell
git add -- packing-robot/packing_ui/main_window.py packing-robot/tests/test_ui_smoke.py packing-robot/README.md
git commit -m "feat: add camera and layout state path switch"
```

### Task 5: Regression Verification

**Files:**
- Modify only if a verified regression requires a focused fix.

**Interfaces:**
- Verifies all prior task interfaces together.

- [ ] **Step 1: Run the full robot suite headlessly**

Run:

```powershell
$env:QT_QPA_PLATFORM='offscreen'
$env:QT_API='pyside6'
python -m pytest -q
```

Expected: all tests PASS.

- [ ] **Step 2: Run static repository checks**

Run:

```powershell
python -m compileall -q packing_ui
git diff --check
git status --short
```

Expected: compilation succeeds, `git diff --check` prints nothing, and status contains only intentional task files or is clean after commits.

- [ ] **Step 3: Inspect the final commit range**

Run:

```powershell
git log -5 --oneline --decorate
git diff 9a9f558..HEAD --stat
```

Expected: focused commits for repository, readiness, PLC branch, and UI/docs with no unrelated files.
