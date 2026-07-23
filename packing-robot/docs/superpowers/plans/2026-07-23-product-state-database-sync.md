# Product Code State Database Sync Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Persist calculated state 1/2 to `wcs_success_box` by exact `product_code` before the old PLC UI reads the pallet.

**Architecture:** A pure repository performs a locked, atomic batch update. A Qt worker runs the repository off the GUI thread, and the main window starts synchronization after camera actions are rebuilt.

**Tech Stack:** Python 3.13, PySide6 6.9, mysql-connector-python 9, pytest 8

## Global Constraints

- Use parameterized SQL only.
- A product_code must resolve to exactly one row.
- A batch is all-or-nothing: commit once or rollback once.
- MySQL passwords come only from `ZHUANGDB_PASSWORD` and never appear in logs.
- Automated tests never connect to real MySQL or PLC.

---

### Task 1: Transactional state repository

**Files:**
- Create: `packing_ui/state_repository.py`
- Create: `tests/test_state_repository.py`

**Interfaces:**
- Produces: `ProductState`, `MySqlConfig`, `ProductStateRepository.update_states`

- [ ] Write tests for parameterized SELECT/UPDATE, exact-one-row validation,
  state validation, one commit, rollback on failure, connection cleanup and
  password-safe errors.
- [ ] Run `python -m pytest tests/test_state_repository.py -q` and verify RED.
- [ ] Implement minimal repository with lazy mysql-connector import.
- [ ] Run the focused tests and verify GREEN.

### Task 2: Background synchronization worker

**Files:**
- Create: `packing_ui/state_sync.py`
- Create: `tests/test_state_sync.py`

**Interfaces:**
- Consumes: `MySqlConfig`, tuple of `ProductState`
- Produces: `StateSyncWorker.succeeded(int)`, `failed(str)`, `finished()`

- [ ] Write direct worker tests using an injected repository factory.
- [ ] Run `python -m pytest tests/test_state_sync.py -q` and verify RED.
- [ ] Implement the QObject worker and shared-settings config loader.
- [ ] Run focused tests and verify GREEN.

### Task 3: Main-window automatic synchronization

**Files:**
- Modify: `packing_ui/main_window.py`
- Modify: `tests/test_ui_smoke.py`

**Interfaces:**
- Consumes: camera box IDs, rebuilt `RobotAction.rotation_state`, state worker
- Produces: database status label and automatic post-camera synchronization

- [ ] Write UI tests for exact product/state extraction, synchronization status,
  launcher button locking and cleanup.
- [ ] Run focused tests and verify RED.
- [ ] Implement QThread lifecycle and UI status handlers.
- [ ] Run focused tests and verify GREEN.

### Task 4: Dependencies, documentation and verification

**Files:**
- Modify: `requirements.txt`
- Modify: `README.md`
- Modify: `data_act/导出动作JSON字段说明.md`

- [ ] Add `mysql-connector-python>=8,<10`.
- [ ] Document product_code mapping, shared settings, environment password and
  exact transaction behavior.
- [ ] Run `python -X faulthandler -m pytest -q`.
- [ ] Run `python -m compileall -q packing_ui main.py`.
- [ ] Capture and inspect the offscreen UI.

