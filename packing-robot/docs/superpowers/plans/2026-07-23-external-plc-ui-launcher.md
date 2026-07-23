# External PLC UI Launcher Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace embedded DB19 communication with one button that opens the existing `D:\research_code\tongxun\plc_gui.py`.

**Architecture:** A small launcher module validates and starts the old PLC UI as an independent process. The main window owns only the process handle and display state; all MySQL, box_unique_id and PLC behavior remains in the old application.

**Tech Stack:** Python 3.13, PySide6 6.9, subprocess, pytest 8

## Global Constraints

- The current packing UI must never connect to or write PLC DB19.
- Only the old PLC UI reads `wcs_success_box.state` and sends DBW12.
- `state=1` means A/no rotation; `state=2` means B/rotate 90°.
- The old PLC UI path is `D:\research_code\tongxun\plc_gui.py`.
- Repeated clicks while the child is running must not create duplicate PLC UI instances.

---

### Task 1: External process launcher

**Files:**
- Create: `packing_ui/plc_launcher.py`
- Create: `tests/test_plc_launcher.py`

**Interfaces:**
- Produces: `launch_plc_ui(directory, python_executable, popen_factory) -> subprocess.Popen`
- Consumes: existing `plc_gui.py` path

- [ ] **Step 1: Write failing tests**

Test exact executable/script arguments, exact working directory, missing script
error and injectable process factory.

- [ ] **Step 2: Verify RED**

Run: `python -m pytest tests/test_plc_launcher.py -q`
Expected: module import fails because `packing_ui.plc_launcher` does not exist.

- [ ] **Step 3: Implement minimal launcher**

Validate the directory and script, then call `subprocess.Popen` without waiting.

- [ ] **Step 4: Verify GREEN**

Run: `python -m pytest tests/test_plc_launcher.py -q`
Expected: all launcher tests pass.

### Task 2: Replace embedded PLC controls

**Files:**
- Modify: `packing_ui/main_window.py`
- Modify: `tests/test_ui_smoke.py`

**Interfaces:**
- Consumes: `launch_plc_ui`
- Produces: `open_plc_ui_button`, `_open_plc_ui`, duplicate-process guard

- [ ] **Step 1: Write failing UI tests**

Assert the external button and database handoff note exist, old direct controls do
not exist, one click launches once, and a running child suppresses duplicates.

- [ ] **Step 2: Verify RED**

Run: `python -m pytest tests/test_ui_smoke.py -q`
Expected: failures identify missing launcher UI and remaining embedded controls.

- [ ] **Step 3: Implement UI replacement**

Remove direct protocol/worker imports, settings widgets, QThreads and send
handlers. Add the external process button, status label and error reporting.

- [ ] **Step 4: Verify GREEN**

Run: `python -m pytest tests/test_ui_smoke.py -q`
Expected: all UI smoke tests pass.

### Task 3: Documentation and verification

**Files:**
- Modify: `README.md`
- Modify: `data_act/导出动作JSON字段说明.md`
- Modify: `requirements.txt`

**Interfaces:**
- Produces: accurate operator workflow and dependency boundary

- [ ] **Step 1: Document database handoff**

State that current UI calculates state but does not write DB19, and the old UI
reads state from MySQL after manual box_unique_id selection.

- [ ] **Step 2: Align dependencies**

Remove direct `python-snap7` ownership from the packing UI documentation; retain
the old PLC project's own requirements and setup command.

- [ ] **Step 3: Run full verification**

Run: `python -X faulthandler -m pytest -q`
Expected: zero failures.

- [ ] **Step 4: Run offscreen UI capture**

Create and inspect an offscreen screenshot verifying the compact launcher panel
does not reduce the box list or 3D viewport.

