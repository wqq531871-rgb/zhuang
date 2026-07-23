# Conveyor and Corner Correction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move the conveyor to the pallet +Y side and model distinct pickup and placement corner alignment across 90-degree rotations.

**Architecture:** Correct corner semantics in `packing_ui.data`, then consume them in the pure trajectory and PyVista scene. Keep placement anchoring independent from source JSON suction rectangles.

**Tech Stack:** Python, PySide6, PyVista, pytest.

## Global Constraints

- Placement box and cup corners are always `x_max_y_max`.
- 0→90 pickup corner is `x_max_y_min`; 90→0 pickup corner is `x_min_y_max`.
- Conveyor lies beyond pallet maximum Y and remains centered in pallet X.

---

### Task 1: Corner semantics

**Files:** `packing_ui/data.py`, `tests/test_data.py`

- [ ] Add failing tests for clockwise/counterclockwise pickup corners, fixed placement corners, recomputed suction target center, and export fields.
- [ ] Implement the action fields and calculations.
- [ ] Run data tests.

### Task 2: Conveyor geometry and trajectory

**Files:** `packing_ui/animation.py`, `packing_ui/scene.py`, `tests/test_animation.py`, `tests/test_scene_geometry.py`

- [ ] Add failing tests that require the conveyor and ready box to be beyond pallet maximum Y.
- [ ] Move conveyor geometry and trajectory start to +Y, centered in X.
- [ ] Run animation and scene tests.

### Task 3: UI/output and visual verification

**Files:** `packing_ui/main_window.py`, `README.md`

- [ ] Update details/list/export terminology for separate pickup/place corners.
- [ ] Run the full test suite.
- [ ] Render READY, TRANSFER, and PLACE_DESCEND screenshots at 90° source pose and visually verify placement anchoring.
