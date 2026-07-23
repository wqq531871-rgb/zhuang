# PyVista Packing UI Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the painter-based mock 3D UI with a PyVista scene matching the supplied reference and animate conveyor pickup through pallet placement.

**Architecture:** Retain `packing_ui.data` as the data contract. Add a pure trajectory function and a PySide6 playback controller, render the trajectory through a PyVista QtInteractor, and rebuild the main window around reference-style selector/scene/details panels.

**Tech Stack:** Python 3.11+, PySide6, PyVista, pyvistaqt, pytest.

## Global Constraints

- Match the layout and visual interaction of `D:\research_code\zx-shunxu`.
- Conveyor is left of the pallet in the 3D world.
- Suction cup is 600 × 800 mm and no robot arm is displayed.
- Conveyor orientation is manually selectable as 0° or 90°.
- Status selector defaults to SUCCESS.

---

### Task 1: Eight-phase playback and trajectory

**Files:**
- Modify: `packing_ui/animation.py`
- Create: `packing_ui/playback.py`
- Modify: `tests/test_animation.py`

**Interfaces:**
- Produces: `trajectory_pose(action, phase, fraction, pallet_width) -> MotionPose` and `PlaybackController` emitting `(index, phase, fraction)`.

- [ ] Write failing tests for the eight phases, conveyor start pose, target end pose, attachment state, phase advance, seeking, and reset.
- [ ] Run `python -m pytest tests/test_animation.py -q` and confirm the new assertions fail.
- [ ] Implement the pure trajectory and PySide6 controller.
- [ ] Re-run the animation tests and confirm they pass.

### Task 2: Interactive PyVista scene

**Files:**
- Replace: `packing_ui/scene.py`
- Test: `tests/test_scene_geometry.py`

**Interfaces:**
- Consumes: `PalletPlan`, `RobotAction`, phase frames, and `trajectory_pose`.
- Produces: `PackingScene.set_plan`, `set_actions`, `show_frame`, and oriented cuboid geometry.

- [ ] Write failing pure-geometry tests for rotated cuboid bounds and conveyor placement left of the pallet.
- [ ] Run the geometry tests and confirm expected failures.
- [ ] Implement PyVista actors for pallet, future/placed boxes, conveyor, active box, and suction cup.
- [ ] Add isometric camera reset, axes, interactive rotation, zoom, and render cleanup.
- [ ] Re-run geometry and existing data tests.

### Task 3: Reference-style PySide6 window

**Files:**
- Replace: `packing_ui/main_window.py`
- Modify: `main.py`
- Replace: `tests/test_ui_smoke.py`

**Interfaces:**
- Consumes: current data actions, `PackingScene`, and `PlaybackController`.
- Produces: selector panel, center scene/playback area, details panel, import/export, and application entry point.

- [ ] Write a failing no-3D UI test for default selectors, type/pallet linking, box sequence list, and playback controls.
- [ ] Run the UI test and confirm it fails against the PyQt5 window.
- [ ] Implement the PySide6 three-column window and style it to match the reference screenshot.
- [ ] Connect selector changes and conveyor orientation changes to actions, scene, details, and playback.
- [ ] Re-run the UI and data tests.

### Task 4: Dependencies, documentation, and real-scene verification

**Files:**
- Modify: `requirements.txt`
- Modify: `README.md`

**Interfaces:**
- Documents startup, OpenGL dependency, camera controls, and animation phases.

- [ ] Replace PyQt5 requirements with PySide6, PyVista, and pyvistaqt.
- [ ] Update startup and operation instructions.
- [ ] Run `python -m pytest -q`.
- [ ] Parse the supplied JSON and assert 25 pallets, 466 boxes, 6 SUCCESS pallets, and 166 SUCCESS actions.
- [ ] Launch the real PyVista window, render a screenshot, and visually verify the reference-style layout plus conveyor, box, and suction cup.
