# PLC DB19 Communication Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Integrate the proven Siemens S7 DB19 handshake into the existing PySide6 packing simulator, with DBW12 as the sole 1/A or 2/B control.

**Architecture:** A pure `plc_protocol` module owns validation, encoding and the S7 handshake. A Qt worker module owns background connection and sequential sending, while `PackingMainWindow` only validates UI state, starts threads and displays progress.

**Tech Stack:** Python 3.13, PySide6 6.9, python-snap7 3.x, pytest 8

## Global Constraints

- DB19 offsets remain DBW0..DBW20 exactly as documented.
- DBW12 accepts only `1` or `2`: `1 = no rotation + A/x_min_y_min`, `2 = rotate 90° + B/x_max_y_min`.
- No separate PLC register carries A/B.
- No automatic resend after an ambiguous write or handshake failure.
- Every command is validated before the first command of a pallet is written.
- Production code is added only after its focused test has failed for the expected missing behavior.

---

### Task 1: Protocol command mapping and encoding

**Files:**
- Create: `packing_ui/plc_protocol.py`
- Create: `tests/test_plc_protocol.py`

**Interfaces:**
- Consumes: `packing_ui.data.RobotAction`
- Produces: `PlcCommand`, `S7Config`, `build_plc_command`, `pack_int`, `pack_payload`

- [ ] **Step 1: Write failing mapping and encoding tests**

Test that `build_plc_command` maps dimensions, placement, top Z, state and seq;
parameterize state `1/2` and assert DBW12 is exactly that value. Test half-up
rounding, invalid state, INT16 overflow and Siemens big-endian bytes.

- [ ] **Step 2: Run focused tests and verify RED**

Run: `python -m pytest tests/test_plc_protocol.py -q`
Expected: collection fails because `packing_ui.plc_protocol` does not exist.

- [ ] **Step 3: Implement the smallest pure protocol mapping**

Implement immutable dataclasses, validation helpers, action mapping and packers.
Do not add network calls yet.

- [ ] **Step 4: Run focused tests and verify GREEN**

Run: `python -m pytest tests/test_plc_protocol.py -q`
Expected: all mapping and encoding tests pass.

### Task 2: S7 connection and handshake

**Files:**
- Modify: `packing_ui/plc_protocol.py`
- Modify: `tests/test_plc_protocol.py`

**Interfaces:**
- Consumes: a snap7-compatible object with `connect`, `disconnect`, `get_connected`, `db_read`, `db_write`
- Produces: `S7Client.connect`, `disconnect`, `wait_for_box`, `send_command`, `create_snap7_client`

- [ ] **Step 1: Add failing fake-driver handshake tests**

Cover connection retry, DBW0..12 payload, DBW16 seq, SEND_OK written last,
FP_OVER result capture, reset order, timeout and no automatic resend.

- [ ] **Step 2: Run focused tests and verify RED**

Run: `python -m pytest tests/test_plc_protocol.py -q`
Expected: failures identify missing `S7Client` behavior.

- [ ] **Step 3: Implement handshake behavior**

Port the tested DB19 logic from `D:\research_code\tongxun\s7_json_client.py`,
keeping the current project module independent from the old folder.

- [ ] **Step 4: Run focused tests and verify GREEN**

Run: `python -m pytest tests/test_plc_protocol.py -q`
Expected: all protocol tests pass without accessing the network.

### Task 3: Background Qt workers

**Files:**
- Create: `packing_ui/plc_worker.py`
- Create: `tests/test_plc_worker.py`

**Interfaces:**
- Consumes: `S7Config`, tuple of `(item_id, PlcCommand)`, injectable client factory
- Produces: `PlcConnectionWorker`, `PlcSendWorker` and progress/result/error Qt signals

- [ ] **Step 1: Write failing worker tests**

Test ordered send, DBW16 result propagation, stop between boxes, connection
failure and guaranteed disconnect.

- [ ] **Step 2: Run focused tests and verify RED**

Run: `python -m pytest tests/test_plc_worker.py -q`
Expected: collection fails because `packing_ui.plc_worker` does not exist.

- [ ] **Step 3: Implement workers**

Use `QObject` workers moved to `QThread`; keep network operations out of the UI
thread and treat stop as a boundary between completed handshakes.

- [ ] **Step 4: Run focused tests and verify GREEN**

Run: `python -m pytest tests/test_plc_worker.py -q`
Expected: all worker tests pass.

### Task 4: Main-window PLC controls and lifecycle

**Files:**
- Modify: `packing_ui/main_window.py`
- Modify: `tests/test_ui_smoke.py`

**Interfaces:**
- Consumes: `build_plc_command`, `S7Config`, workers
- Produces: PLC settings/status/log controls and `_start_plc_send`, `_stop_plc_send`

- [ ] **Step 1: Write failing UI tests**

Assert default PLC settings, start rejection when camera data is incomplete,
generated commands preserve action `seq/state`, running-state control locking,
progress log content and restoration after completion/error.

- [ ] **Step 2: Run focused tests and verify RED**

Run: `python -m pytest tests/test_ui_smoke.py -q`
Expected: failures identify missing PLC widgets and handlers.

- [ ] **Step 3: Implement UI integration**

Add compact PLC controls below “视觉与 PLC”, add a read-only log, create and
clean up `QThread` instances, and ensure close requests safe stop.

- [ ] **Step 4: Run focused tests and verify GREEN**

Run: `python -m pytest tests/test_ui_smoke.py -q`
Expected: all UI smoke tests pass in offscreen mode.

### Task 5: Dependency, documentation and full verification

**Files:**
- Modify: `requirements.txt`
- Modify: `README.md`
- Modify: `data_act/导出动作JSON字段说明.md`

**Interfaces:**
- Consumes: completed implementation
- Produces: reproducible installation/startup and accurate field documentation

- [ ] **Step 1: Add `python-snap7>=3,<4`**

Keep runtime import lazy so non-PLC UI inspection reports a clear error rather
than failing at module import time.

- [ ] **Step 2: Document operation and DBW12 contract**

Document connect/start/stop flow, DB19 map and the invariant 1/A versus 2/B
binding. Clarify that exported A/B fields are explanatory and only state is
transmitted.

- [ ] **Step 3: Run full verification**

Run: `python -m pytest -q`
Expected: zero failures.

- [ ] **Step 4: Run import and offscreen smoke checks**

Run: `python -c "from packing_ui.main_window import PackingMainWindow; print('ok')"`
Expected: `ok`.

