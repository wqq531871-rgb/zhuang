# Robot Packing UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a runnable PyQt5 desktop UI that loads packing JSON, filters pallets by success status, computes robot-facing pick/place data, and animates suction-cup box transfer in an isometric 3D view.

**Architecture:** Keep JSON normalization and motion calculations independent from Qt. Build the GUI from focused widgets: a main coordinator window, an isometric scene widget, and a data table/control panel. Drive animation with a deterministic phase model so calculation logic is unit-testable without showing a window.

**Tech Stack:** Python 3.9+, PyQt5, standard-library dataclasses/json/unittest, pytest for test execution.

## Global Constraints

- Suction cup is fixed at 600 × 800 mm.
- Status selector defaults to `SUCCESS` and includes `ALL`, `FAILED`, and `UNKNOWN`.
- Conveyor box orientation is manually selectable as 0° or 90°.
- Do not require OpenGL or third-party 3D packages; render an isometric 3D projection with QPainter.
- Preserve both the algorithm's box-origin placement and the derived suction-center target.

---

### Task 1: Packing data model and calculations

**Files:**
- Create: `packing_ui/__init__.py`
- Create: `packing_ui/data.py`
- Test: `tests/test_data.py`

**Interfaces:**
- Produces: `load_plan_file(path) -> list[PalletPlan]`, `normalize_document(data) -> list[PalletPlan]`, `filter_plans(plans, status)`, and `build_action(item, conveyor_orientation_deg, conveyor_z) -> RobotAction`.

- [ ] Write tests for both JSON root shapes, status filtering, sequence ordering, pick Z, suction center, corner alignment, and rotation delta.
- [ ] Run `python -m pytest tests/test_data.py -q` and confirm imports/functions fail because production modules do not exist.
- [ ] Implement dataclasses, tolerant parsing, deterministic ordering, and action calculations in `packing_ui/data.py`.
- [ ] Re-run the data tests and confirm all pass.

### Task 2: Deterministic animation model

**Files:**
- Create: `packing_ui/animation.py`
- Test: `tests/test_animation.py`

**Interfaces:**
- Consumes: `RobotAction` from `packing_ui.data`.
- Produces: `MotionState`, `MotionPose`, `set_action`, `advance`, and `reset`.

- [ ] Write tests asserting phase progression, final placement pose, and reset behavior.
- [ ] Run `python -m pytest tests/test_animation.py -q` and confirm expected missing-module failure.
- [ ] Implement a six-phase normalized trajectory with position, height, yaw, box-attached, and completed state.
- [ ] Re-run the animation tests and confirm all pass.

### Task 3: PyQt user interface and isometric scene

**Files:**
- Create: `packing_ui/scene.py`
- Create: `packing_ui/main_window.py`
- Create: `main.py`
- Test: `tests/test_ui_smoke.py`

**Interfaces:**
- Consumes: plans/actions from `packing_ui.data` and motion poses from `packing_ui.animation`.
- Produces: `PackingMainWindow` and the application entry point.

- [ ] Write an offscreen Qt smoke test that constructs the main window and verifies the default selectors.
- [ ] Run the smoke test and confirm failure because UI classes do not exist.
- [ ] Implement the QPainter isometric view with pallet, stacked boxes, conveyor, moving box, suction cup, axes, and camera reset.
- [ ] Implement the main window, selectors, playback controls, details panel, sortable action table, and row selection.
- [ ] Re-run all tests and confirm they pass.

### Task 4: Packaging, sample verification, and documentation

**Files:**
- Create: `requirements.txt`
- Create: `README.md`

**Interfaces:**
- Documents: installation, startup, field interpretation, coordinate assumptions, and limitations.

- [ ] Add exact startup and test commands plus the JSON data contract to the README.
- [ ] Run `python -m pytest -q`.
- [ ] Run `python -c "from PyQt5.QtWidgets import QApplication; from packing_ui.main_window import PackingMainWindow; app=QApplication([]); w=PackingMainWindow(); print(w.windowTitle()); w.close()"` with `QT_QPA_PLATFORM=offscreen`.
- [ ] Parse the provided sample JSON and report pallet/item counts.
- [ ] Start the application briefly against the sample file and confirm no startup exception.
